"""Actual A state machine + B receipts, with explicit media/memory doubles.

The starting proposal is a persisted fixture. This suite isolates receipt and
transaction behavior; test_notice_http covers the complete default HTTP path.
"""
from app.core.config import Settings
from pathlib import Path
from app.core.uow import UnitOfWork
from app.models.health import Notification, Checkin
from app.models.identity import ChangeProposal, ElderProfile
from app.schemas.identity import ChangeDecision
from app.services.change_service import ChangeService
from app.services.notification_service import NotificationService
from sqlalchemy import select, func

from .test_b2 import MediaDouble, make_notice, heartbeat, event


def setup(h):
    changes = ChangeService(h.clock, Settings(data_dir=Path(h.engine.url.database).parent, database_url=None))
    notifications = NotificationService(h.clock, media=MediaDouble(h.clock), changes=changes)
    changes.bind(medication=h.medication, notifications=notifications, memory=h.memory)
    notice = make_notice(h, notifications, proposal=True)
    with UnitOfWork(h.factory) as uow:
        uow.session.get(ChangeProposal, "proposal").notification_id = notice.notification_id
        uow.commit()
    return changes, notifications, notice


def test_b_receipt_arms_real_a_window_once_and_restart_settles(health):
    h = health
    changes, notifications, notice = setup(h)
    h.clock.advance(seconds=3600)
    with UnitOfWork(h.factory) as uow:
        assert changes.apply_due(uow.session, h.clock.now()) == []
        uow.commit()
    heartbeat(h, notifications)
    event(h, notifications, notice, "displayed")
    event(h, notifications, notice, "answered")
    played = event(h, notifications, notice, "playback_completed")
    assert played.change_proposal.status == "awaiting_decision"
    deadline = played.change_proposal.auto_apply_at
    assert (deadline - h.clock.now()).total_seconds() == 60
    h.clock.advance(seconds=10)
    assert event(h, notifications, notice, "playback_completed") == played
    restarted = ChangeService(h.clock, changes.settings).bind(
        medication=h.medication, notifications=notifications, memory=h.memory)
    h.clock.advance(seconds=49)
    with UnitOfWork(h.factory) as uow:
        assert restarted.apply_due(uow.session, h.clock.now()) == []
        uow.commit()
    h.clock.advance(seconds=2)
    with UnitOfWork(h.factory) as uow:
        settled = restarted.apply_due(uow.session, h.clock.now())
        assert len(settled) == 1 and settled[0].status == "applied"
        assert settled[0].auto_apply_at == deadline
        uow.commit()
    with h.factory() as tx:
        assert tx.get(ElderProfile, h.elder).version == 2
        assert tx.get(Notification, notice.notification_id).task_state == "handled"
        assert tx.scalar(select(func.count()).select_from(Checkin)) == 0


def test_real_a_rejection_closes_b_notice_without_applying(health):
    h = health
    changes, notifications, notice = setup(h)
    heartbeat(h, notifications)
    event(h, notifications, notice, "displayed")
    event(h, notifications, notice, "answered")
    event(h, notifications, notice, "playback_completed")
    with UnitOfWork(h.factory) as uow:
        result = changes.decide(uow.session, h.actor, "proposal", ChangeDecision(decision="reject"), h.clock.now())
        assert result.status == "rejected"
        uow.commit()
    h.clock.advance(seconds=61)
    with UnitOfWork(h.factory) as uow:
        assert changes.apply_due(uow.session, h.clock.now()) == []
        uow.commit()
    with h.factory() as tx:
        assert tx.get(ElderProfile, h.elder).version == 1
        assert tx.get(Notification, notice.notification_id).task_state == "handled"
