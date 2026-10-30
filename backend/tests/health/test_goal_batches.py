from datetime import timedelta

import pytest
from sqlalchemy import select, func

from app.core.errors import AppError
from app.core.uow import UnitOfWork
from app.models.health import Checkin, DailyGoalBatch, DailyTask, Notification
from app.models.identity import ElderProfile
from app.schemas.health import MedicationPlanWrite, PlanPatch, SettingsPatch
from .helpers import transact
from .test_b1 import DAY, plan, med_task, intake


def test_generated_empty_category_is_not_regenerated_from_new_settings(health):
    h = health
    with UnitOfWork(h.factory) as unit:
        elder = unit.session.get(ElderProfile, h.elder)
        settings = {**elder.reminder_settings_json, "exercise": {"enabled": False, "local_time": "17:00"}}
        elder.reminder_settings_json = settings
        unit.commit()
    initial = transact(h, h.reports.daily, DAY).completion.progress
    assert initial.exercise.expected == 0 and not initial.exercise.applicable
    with h.factory() as tx:
        assert tx.get(DailyGoalBatch, (h.elder, DAY, "exercise")) is not None
    transact(h, h.medication.update_settings, 1, SettingsPatch(exercise={"enabled": True, "local_time": "18:00"}))
    assert transact(h, h.reports.daily, DAY).completion.progress == initial
    future = transact(h, h.reports.daily, DAY + timedelta(days=1)).completion.progress
    assert future.exercise.expected == 1
    h.clock.advance(seconds=86400)
    assert transact(h, h.reports.daily, DAY).completion.progress == initial


def test_removed_slot_keeps_recorded_snapshot_and_retires_only_future(health):
    h = health
    p = plan(h)
    today = med_task(h)
    record = transact(h, h.checkins.create_or_update, intake(h, p, today))
    tomorrow = DAY + timedelta(days=1)
    future = next(t for t in transact(h, h.checkins.tasks, tomorrow).items if t.category == "medication")
    transact(h, h.medication.apply_change, "update", p.plan_id, PlanPatch(schedule={"mode": "fixed",
        "slots": [{"slot_id": "replacement", "local_time": "19:00"}]}), 1)
    with h.factory() as tx:
        assert tx.get(DailyTask, today.task_id).cancelled_at is None
        assert tx.get(DailyTask, today.task_id).plan_version == 1
        assert tx.get(DailyTask, future.task_id).cancelled_at is not None
        assert tx.get(Checkin, record.checkin_id).task_id == today.task_id
    assert transact(h, h.reports.daily, DAY).completion.progress.medication.expected == 2
    assert transact(h, h.reports.daily, tomorrow).completion.progress.medication.expected == 1
    transact(h, h.medication.apply_change, "deactivate", p.plan_id, None, 2)
    current = transact(h, h.reports.daily, DAY).completion.progress.medication
    assert current.expected == current.completed == 1
    assert transact(h, h.reports.daily, tomorrow).completion.progress.medication.expected == 0


def test_removed_then_readded_future_slot_reuses_unique_row(health):
    h = health
    p = plan(h)
    tomorrow = DAY + timedelta(days=1)
    old = next(t for t in transact(h, h.checkins.tasks, tomorrow).items if t.category == "medication")
    transact(h, h.medication.apply_change, "update", p.plan_id, PlanPatch(schedule={"mode": "fixed",
        "slots": [{"slot_id": "two", "local_time": "19:00"}]}), 1)
    transact(h, h.medication.apply_change, "update", p.plan_id, PlanPatch(schedule={"mode": "fixed",
        "slots": [{"slot_id": "one", "local_time": "10:00"}]}), 2)
    new = next(t for t in transact(h, h.checkins.tasks, tomorrow).items if t.category == "medication")
    assert new.task_id == old.task_id and new.plan_version == 3
    with h.factory() as tx:
        assert tx.scalar(select(func.count()).select_from(DailyTask).where(
            DailyTask.elder_id == h.elder, DailyTask.local_date == tomorrow, DailyTask.slot_key == old.slot_key)) == 1


def test_cancelled_task_rejects_checkin_and_pending_notification_is_closed(health):
    h = health
    p = plan(h)
    task = med_task(h)
    with UnitOfWork(h.factory) as unit:
        unit.session.add(Notification(elder_id=h.elder, source_key="pending-before-change", kind="medication",
            title="既定提醒", text="待核对", due_at=task.due_at, related_task_id=task.task_id))
        unit.commit()
    transact(h, h.medication.apply_change, "deactivate", p.plan_id, None, 1)
    with pytest.raises(AppError) as exc:
        transact(h, h.checkins.create_or_update, intake(h, p, task))
    assert exc.value.status == 422
    with h.factory() as tx:
        assert tx.scalar(select(Notification).where(Notification.source_key == "pending-before-change")).task_state == "dismissed"
        assert tx.scalar(select(func.count()).select_from(Checkin)) == 0


def test_ungenerated_past_day_is_not_backfilled_by_new_plan(health):
    h = health
    plan(h)
    yesterday = DAY - timedelta(days=1)
    assert transact(h, h.reports.daily, yesterday).completion.progress.medication.expected == 0
    with h.factory() as tx:
        assert tx.scalar(select(func.count()).select_from(DailyGoalBatch).where(
            DailyGoalBatch.elder_id == h.elder, DailyGoalBatch.local_date == yesterday)) == 0


def test_future_settings_can_reactivate_same_goal_without_duplicates(health):
    h = health
    tomorrow = DAY + timedelta(days=1)
    before = next(t for t in transact(h, h.checkins.tasks, tomorrow).items if t.category == "exercise")
    transact(h, h.medication.update_settings, 1, SettingsPatch(exercise={"enabled": False, "local_time": "17:00"}))
    transact(h, h.medication.update_settings, 2, SettingsPatch(exercise={"enabled": True, "local_time": "18:00"}))
    after = next(t for t in transact(h, h.checkins.tasks, tomorrow).items if t.category == "exercise")
    assert after.task_id == before.task_id and after.due_at.hour == 10
