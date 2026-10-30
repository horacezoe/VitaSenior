"""Receipt state machine uses a ChangePort double, not A's implementation."""
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.core.errors import AppError
from app.core.uow import UnitOfWork
from app.models.health import Notification, NotificationEvent, Presence, Checkin
from app.models.identity import ChangeProposal
from app.schemas.health import NotificationEnqueue, NotificationEvent as Event, PresenceWrite
from app.schemas.identity import ChangeProposal as ProposalDTO, MediaAsset
from app.services.notification_service import NotificationService
from app.scheduler import Scanner, scan_due
from .helpers import transact
from .test_b1 import DAY, plan, med_task, meal, intake


class MediaDouble:
    def __init__(self, clock):
        self.clock = clock
    def get_asset(self, tx, actor, asset_id):
        return MediaAsset(asset_id=asset_id, purpose="agent_audio", mime_type="audio/wav", size_bytes=200,
            duration_ms=100, content_url="/test-only/audio", expires_at=self.clock.now() + timedelta(minutes=5))


class ChangeDouble:
    """Records a port invocation in SQLite. No copy of A's deadline algorithm."""
    def __init__(self):
        self.calls = 0
        self.fail = False
        self.due_calls = []

    def _dto(self, row):
        return ProposalDTO(proposal_id=row.id, elder_id=row.elder_id, created_by=row.created_by,
            target_type=row.target_type, target_id=row.target_id, operation=row.operation,
            base_version=row.base_version, patch=row.patch, before_snapshot=None,
            status=row.status, notification_id=row.notification_id, notified_at=row.notified_at,
            auto_apply_at=row.auto_apply_at, applied_at=row.applied_at, applied_by=row.applied_by,
            conflict_reason=row.conflict_reason)

    def read(self, tx, actor, proposal_id):
        return self._dto(tx.get(ChangeProposal, proposal_id))

    def mark_played(self, tx, actor, proposal_id, now):
        self.calls += 1
        row = tx.get(ChangeProposal, proposal_id)
        row.notified_at = now
        tx.flush()
        if self.fail:
            raise RuntimeError("Injected ChangePort failure")
        return self._dto(row)

    def apply_due(self, tx, now):
        self.due_calls.append(now)
        return []


@pytest.fixture
def notices(health):
    h = health
    change = ChangeDouble()
    service = NotificationService(h.clock, media=MediaDouble(h.clock), changes=change)
    return h, service, change


def make_notice(h, service, *, proposal=False, repeat_count=1, audio=True, source="one"):
    with UnitOfWork(h.factory) as uow:
        if proposal:
            uow.session.add(ChangeProposal(id="proposal", elder_id=h.elder,
                created_by=h.actors["bound_child"].user_id, target_type="profile", target_id=h.elder,
                operation="update", base_version=1, patch={"medical_notes": "演示修改"}, created_at=h.clock.now()))
            uow.session.flush()
        # Media FK exists; the MediaPort double handles access/playability only.
        if audio:
            from app.models.identity import MediaAsset as MediaRow
            if uow.session.get(MediaRow, "audio") is None:
                uow.session.add(MediaRow(id="audio", owner_user_id=h.actor.user_id, elder_id=h.elder,
                    purpose="agent_audio", mime_type="audio/wav", size_bytes=200,
                    relative_path="not-read-by-health.wav", created_at=h.clock.now()))
                uow.session.flush()
        value = NotificationEnqueue(elder_id=h.elder, category="general",
            kind="profile_change" if proposal else "medication", title="测试", text="请确认",
            due_at=h.clock.now(), proposal_id="proposal" if proposal else None,
            audio_asset_id="audio" if audio else None, repeat_count=repeat_count)
        result = service.enqueue(uow.session, h.actor, source, value)
        uow.commit()
        return result


def heartbeat(h, service, visible=True, client="tab"):
    return transact(h, service.presence, PresenceWrite(client_id=client, visible=visible))


def event(h, service, notice, kind, event_id=None, **kwargs):
    with UnitOfWork(h.factory) as uow:
        result = service.handle_event(uow.session, h.actor, notice.notification_id,
            Event(event_id=event_id or kind, event_type=kind, **kwargs), h.clock.now())
        uow.commit()
        return result


def test_no_presence_get_or_push_delivery_side_effect(notices):
    h, service, change = notices
    notice = make_notice(h, service, proposal=True)
    with UnitOfWork(h.factory) as uow:
        uow.session.get(Notification, notice.notification_id).push_state = "sent"
        uow.commit()
    assert transact(h, service.query).items[0].delivery_state == "pending"
    h.clock.advance(seconds=61)
    with pytest.raises(AppError) as exc:
        event(h, service, notice, "displayed")
    assert exc.value.code == "APP_NOT_VISIBLE"
    assert change.calls == 0
    with h.factory() as tx:
        row = tx.get(ChangeProposal, "proposal")
        assert row.notified_at is None and row.auto_apply_at is None


def test_heartbeat_expiry_multiple_tabs_and_hidden(notices):
    h, service, _ = notices
    notice = make_notice(h, service)
    first = heartbeat(h, service)
    assert first.active_until == h.clock.now() + timedelta(seconds=25)
    h.clock.advance(seconds=10)
    heartbeat(h, service, client="second")
    heartbeat(h, service, False)
    event(h, service, notice, "displayed")
    h.clock.advance(seconds=25)
    with pytest.raises(AppError) as exc:
        event(h, service, notice, "answered")
    assert exc.value.code == "APP_NOT_VISIBLE"
    with h.factory() as tx:
        assert tx.get(Notification, notice.notification_id).delivery_state == "displayed"
        assert tx.get(Presence, (h.elder, "tab")) is None


def test_strict_order_and_only_full_repeated_playback_calls_change(notices):
    h, service, change = notices
    notice = make_notice(h, service, proposal=True, repeat_count=2)
    heartbeat(h, service)
    for kind in ["answered", "playback_completed"]:
        with pytest.raises(AppError) as exc:
            event(h, service, notice, kind)
        assert exc.value.code == "INVALID_NOTIFICATION_TRANSITION"
    event(h, service, notice, "displayed")
    event(h, service, notice, "answered")
    first = event(h, service, notice, "playback_completed", "play-1")
    assert first.notification.delivery_state == "answered" and change.calls == 0
    assert event(h, service, notice, "playback_completed", "play-1") == first
    result = event(h, service, notice, "playback_completed", "play-2")
    assert result.notification.delivery_state == "played" and change.calls == 1
    assert result.change_proposal is not None
    h.clock.advance(seconds=2)
    event(h, service, notice, "playback_completed", "play-3")
    assert change.calls == 1
    with h.factory() as tx:
        assert tx.scalar(select(func.count()).select_from(Checkin)) == 0
        assert tx.get(ChangeProposal, "proposal").notified_at == result.notification.played_at


def test_audio_missing_never_completes_playback(notices):
    h, service, change = notices
    notice = make_notice(h, service, proposal=True, audio=False)
    heartbeat(h, service)
    event(h, service, notice, "displayed")
    event(h, service, notice, "answered")
    with pytest.raises(AppError):
        event(h, service, notice, "playback_completed")
    assert change.calls == 0


def test_receipt_and_proposal_atomic_and_restart_dedup(notices):
    h, service, change = notices
    notice = make_notice(h, service, proposal=True)
    heartbeat(h, service)
    event(h, service, notice, "displayed")
    event(h, service, notice, "answered")
    change.fail = True
    with pytest.raises(RuntimeError):
        event(h, service, notice, "playback_completed")
    with h.factory() as tx:
        assert tx.get(Notification, notice.notification_id).played_at is None
        assert tx.get(ChangeProposal, "proposal").notified_at is None
        assert tx.get(NotificationEvent, "playback_completed") is None
    change.fail = False
    original = event(h, service, notice, "playback_completed")
    restarted = NotificationService(h.clock, media=MediaDouble(h.clock), changes=change)
    h.clock.advance(seconds=60)
    # Persisted event replay is allowed after heartbeat expiry; it does not
    # pretend a NEW playback happened or reset the A-owned deadline.
    assert event(h, restarted, notice, "playback_completed") == original
    assert change.calls == 2  # failed transaction + one successful invocation


@pytest.mark.parametrize("kind", ["handled", "snoozed", "dismissed"])
def test_proposal_task_events_cannot_bypass_decision(notices, kind):
    h, service, _ = notices
    notice = make_notice(h, service, proposal=True)
    args = {"snooze_minutes": 1} if kind == "snoozed" else {}
    with pytest.raises(AppError):
        event(h, service, notice, kind, **args)


def test_task_state_separate_from_playback_and_record(notices):
    h, service, _ = notices
    notice = make_notice(h, service)
    event(h, service, notice, "snoozed", snooze_minutes=1)
    heartbeat(h, service)
    with pytest.raises(AppError):
        event(h, service, notice, "displayed")
    h.clock.advance(seconds=61)
    heartbeat(h, service)
    event(h, service, notice, "displayed")
    result = event(h, service, notice, "handled")
    assert result.notification.task_state == "handled" and result.notification.delivery_state == "displayed"
    with h.factory() as tx:
        assert tx.scalar(select(func.count()).select_from(Checkin)) == 0


@pytest.mark.parametrize("label", ["bound_child", "unbound_child", "stranger_elder"])
def test_receipts_reject_other_actors(notices, label):
    h, service, _ = notices
    notice = make_notice(h, service)
    with UnitOfWork(h.factory) as uow, pytest.raises(AppError) as exc:
        service.handle_event(uow.session, h.actors[label], notice.notification_id,
            Event(event_id="e", event_type="handled"), h.clock.now())
    assert exc.value.status == 404


def test_event_id_and_source_key_conflicts(notices):
    h, service, _ = notices
    a = make_notice(h, service)
    b = make_notice(h, service, source="two")
    event(h, service, a, "handled", "same")
    with pytest.raises(AppError) as exc:
        event(h, service, b, "handled", "same")
    assert exc.value.code == "IDEMPOTENCY_CONFLICT"
    assert make_notice(h, service).notification_id == a.notification_id
    with pytest.raises(AppError):
        make_notice(h, service, repeat_count=2)


def test_scanner_waits_for_meal_dedup_and_records_handle_notice(notices):
    h, service, _ = notices
    p = plan(h, "after_meal")
    t = med_task(h)
    def scan():
        with UnitOfWork(h.factory) as uow:
            result = service.scan(uow.session, h.clock.now())
            uow.commit()
            return result
    h.clock.advance(seconds=4 * 3600)
    assert not any(n.related_task_id == t.task_id for n in scan())
    transact(h, h.checkins.create_or_update, meal(h))
    h.clock.advance(seconds=1800)
    found = next(n for n in scan() if n.related_task_id == t.task_id)
    assert next(n for n in scan() if n.related_task_id == t.task_id).notification_id == found.notification_id
    record = transact(h, h.checkins.create_or_update, intake(h, p, t))
    with h.factory() as tx:
        assert tx.get(Notification, found.notification_id).task_state == "handled"
    transact(h, h.checkins.cancel, record.checkin_id, 1)
    with h.factory() as tx:
        assert tx.get(Notification, found.notification_id).task_state == "open"


def test_system_scanner_calls_change_port_and_rolls_back_on_failure(notices):
    h, service, change = notices
    bundle = SimpleNamespace(changes=change)
    h.clock.advance(seconds=3600)
    def fail(tx, now):
        service.scan(tx, now)
        raise RuntimeError("scan rollback")
    with pytest.raises(RuntimeError):
        scan_due(h.factory, bundle, h.clock.now(), scan_hook=fail)
    with h.factory() as tx:
        assert tx.scalar(select(func.count()).select_from(Notification)) == 0
    scanner = Scanner(h.clock, factory=h.factory, services=bundle, scan_hook=service.scan)
    scanner.tick()
    assert change.due_calls == [h.clock.now(), h.clock.now()]
    assert scanner.last_tick_at == h.clock.now()
    with h.factory() as tx:
        rows = list(tx.scalars(select(Notification)))
        assert rows and all(n.delivery_state == "pending" and n.push_state == "unsupported" for n in rows)


@pytest.mark.parametrize("displayed", [False, True])
def test_corrected_after_meal_notice_reuses_delivery_without_new_call(notices, displayed):
    h, service, _ = notices
    plan(h, "after_meal")
    t = med_task(h)
    h.clock.advance(seconds=4 * 3600)
    record = transact(h, h.checkins.create_or_update, meal(h))
    h.clock.advance(seconds=1800)
    with UnitOfWork(h.factory) as uow:
        notice = next(n for n in service.scan(uow.session, h.clock.now()) if n.related_task_id == t.task_id)
        uow.commit()
    if displayed:
        heartbeat(h, service)
        event(h, service, notice, "displayed")
    transact(h, h.checkins.cancel, record.checkin_id, 1)
    if not displayed:
        assert not any(n.notification_id == notice.notification_id for n in transact(h, service.query).items)
        heartbeat(h, service)
        with pytest.raises(AppError):
            event(h, service, notice, "displayed")
    transact(h, h.checkins.create_or_update, meal(h))
    h.clock.advance(seconds=1800)
    with UnitOfWork(h.factory) as uow:
        repeated = next(n for n in service.scan(uow.session, h.clock.now()) if n.related_task_id == t.task_id)
        assert repeated.notification_id == notice.notification_id
        assert repeated.delivery_state == ("displayed" if displayed else "pending")
        uow.commit()
