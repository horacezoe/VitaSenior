from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.core.errors import AppError
from app.core.uow import UnitOfWork
from app.models.health import Checkin, DailyTask, Notification
from app.models.identity import ElderProfile
from app.schemas.health import MedicationPlanWrite
from .helpers import transact
from .test_b1 import DAY


def test_history_is_explicit_demo_seed_dedup_persistent_and_silent(health):
    h = health
    with UnitOfWork(h.factory) as uow:
        uow.session.get(ElderProfile, h.elder).onboarding_status = "confirmed"
        uow.commit()
    value = MedicationPlanWrite(name="演示药物", dose_display="预置既定用量", start_date=DAY,
        schedule={"mode": "fixed", "slots": [{"slot_id": "morning", "local_time": "08:00"}]})
    transact(h, h.medication.import_draft, [value])
    transact(h, h.checkins.import_demo_history, demo_id="framework-v1", days=14)
    with h.factory() as tx:
        count = tx.scalar(select(func.count()).select_from(Checkin))
        assert count > 14
        rows = list(tx.scalars(select(Checkin)))
        assert all(r.source == "demo_seed" and r.local_date < DAY for r in rows)
        assert tx.scalar(select(func.count()).select_from(Notification)) == 0
        assert tx.scalar(select(func.count()).select_from(DailyTask).where(DailyTask.local_date < DAY)) == 70
    before = transact(h, h.reports.daily, DAY - timedelta(days=1))
    h.clock.advance(seconds=86400)
    transact(h, h.checkins.import_demo_history, demo_id="framework-v1", days=14)
    with h.factory() as tx:
        assert tx.scalar(select(func.count()).select_from(Checkin)) == count
    assert transact(h, h.reports.daily, DAY - timedelta(days=1)).completion.progress == before.completion.progress


def test_history_rejects_wrong_demo_or_unconfirmed(health):
    h = health
    with pytest.raises(AppError):
        transact(h, h.checkins.import_demo_history, demo_id="other-family", days=14)
    with pytest.raises(AppError):
        transact(h, h.checkins.import_demo_history, demo_id="framework-v1", days=14)
