from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import pytest
from sqlalchemy import func, select

from app.core.errors import AppError
from app.core.idempotency import Idempotency, StoredResult
from app.core.uow import UnitOfWork
from app.models.agent import MemoryDocument
from app.models.health import Checkin, DailyTask, MedicationPlan
from app.models.identity import ElderProfile
from app.schemas.health import (CheckinUpdate, DietWrite, ExerciseWrite, MedicationWrite,
    MedicationPlanWrite, PlanPatch, SettingsPatch)
from .helpers import transact

DAY = date(2026, 10, 30)


def meal(h, slot="lunch", **kwargs):
    return DietWrite(type="diet", occurred_at=h.clock.now(),
                     payload={"meal_slot": slot, "foods": ["豆腐"]}, **kwargs)


def walk(h):
    return ExerciseWrite(type="exercise", occurred_at=h.clock.now(),
                         payload={"activity": "散步", "duration_minutes": 20})


def plan(h, mode="fixed", **kwargs):
    slot = {"slot_id": "one", "local_time": "09:00"} if mode == "fixed" else {
        "slot_id": "one", "meal_slot": "lunch", "delay_minutes": 30}
    value = MedicationPlanWrite(name="用户既定药物", dose_display="档案既定用量",
        start_date=DAY, schedule={"mode": mode, "slots": [slot]}, **kwargs)
    return transact(h, h.medication.apply_change, "create", None, value, None)


def med_task(h):
    return next(t for t in transact(h, h.checkins.tasks, DAY).items if t.category == "medication")


def intake(h, p, t, status="taken"):
    return MedicationWrite(type="medication", task_id=t.task_id, occurred_at=h.clock.now(),
        payload={"plan_id": p.plan_id, "slot_id": "one", "intake_status": status})


def test_same_meal_replaces_and_persists_revisions(health):
    h = health
    first = transact(h, h.checkins.create_or_update, meal(h))
    second = transact(h, h.checkins.create_or_update, meal(h))
    assert first.checkin_id == second.checkin_id and second.version == 2
    with h.factory() as tx:
        assert tx.scalar(select(func.count()).select_from(Checkin)) == 1
        row = tx.get(Checkin, first.checkin_id)
        assert row.revisions_json[0]["version"] == 1
        assert tx.get(MemoryDocument, h.elder).revisions_json[-1]["id"] == row.id
        assert row.task_id is not None


def test_concurrent_same_meal_serialized(health):
    h = health
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: transact(h, h.checkins.create_or_update, meal(h)), range(2)))
    assert len({r.checkin_id for r in results}) == 1
    with h.factory() as tx:
        assert tx.scalar(select(func.count()).select_from(Checkin)) == 1
        assert tx.get(Checkin, results[0].checkin_id).version == 2


def test_exercise_multiple_and_idempotency(health):
    h = health
    value = walk(h)
    idem = Idempotency(h.clock)
    def run():
        with UnitOfWork(h.factory) as uow:
            result = idem.execute(uow.session, actor_id=h.actor.user_id, method="POST", path="/checkins",
                key="one", body=value.model_dump(mode="json"), operation=lambda: StoredResult(201,
                    h.checkins.create_or_update(uow.session, h.actor, h.elder, value).model_dump(mode="json")))
            uow.commit()
            return result
    assert run() == run()
    transact(h, h.checkins.create_or_update, value)
    report = transact(h, h.reports.daily, DAY)
    assert len(report.records.exercise) == 2
    assert report.completion.progress.exercise.completed == 1


def test_fixed_and_after_meal_tasks_snapshots_and_uniqueness(health):
    h = health
    p = plan(h)
    plan(h, "after_meal")
    a = transact(h, h.checkins.tasks, DAY)
    b = transact(h, h.checkins.tasks, DAY)
    assert {t.task_id for t in a.items} == {t.task_id for t in b.items}
    assert len(a.items) == 6
    fixed = next(t for t in a.items if t.plan_id == p.plan_id)
    assert fixed.due_at.hour == 1 and fixed.plan_version == 1
    waiting = next(t for t in a.items if t.waiting_for_meal)
    assert waiting.due_at is None
    h.clock.advance(seconds=4 * 3600)
    record = transact(h, h.checkins.create_or_update, meal(h))
    waiting = next(t for t in transact(h, h.checkins.tasks, DAY).items if t.waiting_for_meal is False and t.plan_id != p.plan_id and t.category == "medication")
    assert waiting.due_at == record.occurred_at + timedelta(minutes=30)
    transact(h, h.checkins.cancel, record.checkin_id, record.version)
    assert any(t.waiting_for_meal for t in transact(h, h.checkins.tasks, DAY).items)


@pytest.mark.parametrize("status,completed", [("taken", 1), ("not_taken", 0)])
def test_medication_explicit_intake_unique(health, status, completed):
    h = health
    p, t = plan(h), med_task(h)
    first = transact(h, h.checkins.create_or_update, intake(h, p, t, status))
    with pytest.raises(AppError) as exc:
        transact(h, h.checkins.create_or_update, intake(h, p, t, status))
    assert exc.value.status == 409
    report = transact(h, h.reports.daily, DAY)
    assert report.completion.progress.medication.completed == completed
    if status == "not_taken":
        assert any(a.kind == "record_not_taken" for a in report.attention_items)
    correction = CheckinUpdate(expected_version=1, payload={"plan_id": p.plan_id,
        "slot_id": "one", "intake_status": "taken"})
    updated = transact(h, h.checkins.create_or_update, correction, first.checkin_id)
    assert updated.version == 2
    assert transact(h, h.reports.daily, DAY).completion.progress.medication.completed == 1
    transact(h, h.checkins.cancel, first.checkin_id, 2)
    assert transact(h, h.reports.daily, DAY).completion.progress.medication.completed == 0
    assert transact(h, h.checkins.create_or_update, intake(h, p, t)).version == 1


@pytest.mark.parametrize("wrong", ["plan", "slot", "task", "category", "elder"])
def test_medication_relationships_fail_atomically(health, wrong):
    h = health
    p, t = plan(h), med_task(h)
    body = intake(h, p, t).model_dump()
    if wrong in {"plan", "slot"}:
        body["payload"][wrong + "_id"] = "wrong"
    if wrong == "task":
        body["task_id"] = "missing"
    if wrong == "category":
        body["task_id"] = next(t.task_id for t in transact(h, h.checkins.tasks, DAY).items if t.category == "diet")
    if wrong == "elder":
        with UnitOfWork(h.factory) as uow:
            foreign = h.checkins.tasks(uow.session, h.actors["stranger_elder"], h.seed["stranger_elder"]["elder_id"], DAY)
            body["task_id"] = foreign.items[0].task_id
            uow.commit()
    with pytest.raises(AppError):
        transact(h, h.checkins.create_or_update, MedicationWrite.model_validate(body))
    with h.factory() as tx:
        assert tx.scalar(select(func.count()).select_from(Checkin)) == 0


@pytest.mark.parametrize("operation", ["create", "plan", "settings", "record"])
def test_child_direct_writes_denied(health, operation):
    h = health
    p = plan(h)
    with UnitOfWork(h.factory) as uow, pytest.raises(AppError) as exc:
        tx, actor = uow.session, h.actors["bound_child"]
        if operation in {"create", "plan"}:
            h.medication.apply_change(tx, actor, h.elder, "update", p.plan_id, PlanPatch(notes="x"), 1)
        elif operation == "settings":
            h.medication.update_settings(tx, actor, h.elder, 1, SettingsPatch(voice_enabled=False))
        else:
            h.checkins.create_or_update(tx, actor, h.elder, meal(h))
    assert exc.value.status == 403


def test_plan_merge_validation_stale_version_and_persistent_schedule(health):
    h = health
    p = plan(h, end_date=DAY)
    with pytest.raises(AppError) as exc:
        transact(h, h.medication.apply_change, "update", p.plan_id, PlanPatch(start_date=DAY + timedelta(days=1)), 1)
    assert exc.value.status == 422
    p = transact(h, h.medication.apply_change, "update", p.plan_id, PlanPatch(notes="正确备注"), 1)
    with pytest.raises(AppError) as exc:
        transact(h, h.medication.apply_change, "update", p.plan_id, PlanPatch(notes="stale"), 1)
    assert exc.value.status == 409
    with h.factory() as tx:
        row = tx.get(MedicationPlan, p.plan_id)
        assert row.version == 2 and row.notes == "正确备注"


def test_historical_denominator_survives_plan_change(health):
    h = health
    p = plan(h)
    initial = transact(h, h.reports.daily, DAY).completion.progress
    h.clock.advance(seconds=86400)
    transact(h, h.medication.apply_change, "update", p.plan_id, PlanPatch(schedule={"mode": "fixed",
        "slots": [{"slot_id": "one", "local_time": "09:30"}, {"slot_id": "two", "local_time": "19:00"}]}), 1)
    assert transact(h, h.reports.daily, DAY).completion.progress == initial
    assert transact(h, h.reports.daily, DAY + timedelta(days=1)).completion.progress.medication.expected == 2
    with h.factory() as tx:
        historical = tx.scalar(select(DailyTask).where(DailyTask.plan_id == p.plan_id, DailyTask.local_date == DAY))
        assert historical.plan_version == 1 and len(historical.plan_snapshot["schedule"]["slots"]) == 1


def test_settings_share_profile_version_and_persist(health):
    h = health
    result = transact(h, h.medication.update_settings, 1, SettingsPatch(voice_enabled=False))
    assert result.version == 2 and result.voice_enabled is False
    with h.factory() as tx:
        row = tx.get(ElderProfile, h.elder)
        assert row.version == 2 and row.reminder_settings_json["voice_enabled"] is False
    with pytest.raises(AppError) as exc:
        transact(h, h.medication.update_settings, 1, SettingsPatch(voice_enabled=True))
    assert exc.value.status == 409


def test_correction_cancel_reports_calendar_dashboard_and_atomic_memory(health):
    h = health
    first = transact(h, h.checkins.create_or_update, meal(h))
    wrong = CheckinUpdate(expected_version=1, payload={"activity": "散步", "duration_minutes": 20})
    with pytest.raises(AppError) as exc:
        transact(h, h.checkins.create_or_update, wrong, first.checkin_id)
    assert exc.value.status == 422
    change = CheckinUpdate(expected_version=1, payload={"meal_slot": "breakfast", "foods": ["粥"]})
    updated = transact(h, h.checkins.create_or_update, change, first.checkin_id)
    assert updated.payload.meal_slot == "breakfast"
    with pytest.raises(AppError):
        transact(h, h.checkins.create_or_update, change, first.checkin_id)
    h.memory.fail = True
    with pytest.raises(RuntimeError):
        transact(h, h.checkins.cancel, updated.checkin_id, 2)
    with h.factory() as tx:
        assert tx.get(Checkin, first.checkin_id).version == 2
        assert len(tx.get(MemoryDocument, h.elder).revisions_json) == 1
    h.memory.fail = False
    transact(h, h.checkins.cancel, updated.checkin_id, 2)
    report = transact(h, h.reports.daily, DAY)
    dashboard = transact(h, h.reports.dashboard, DAY)
    month = transact(h, h.reports.calendar, "2026-10")
    assert report.completion == dashboard.completion == month.days[29]
    assert report.records == dashboard.today_records
    assert report.completion.state == "unrecorded"
    assert month.days[30].state == "future" and month.days[30].color is None


def test_complete_colors_and_no_medication_not_missing(health):
    h = health
    assert transact(h, h.reports.daily, DAY).completion.color == "gray"
    for slot in ["breakfast", "lunch", "dinner"]:
        transact(h, h.checkins.create_or_update, meal(h, slot))
    assert transact(h, h.reports.daily, DAY).completion.color == "yellow"
    transact(h, h.checkins.create_or_update, walk(h))
    report = transact(h, h.reports.daily, DAY)
    assert report.completion.color == "green"
    assert report.completion.progress.medication.expected == 0
    assert not report.completion.progress.medication.applicable
    assert not report.attention_items


def test_unrecorded_medication_never_means_not_taken(health):
    h = health
    plan(h)
    h.clock.advance(seconds=7200)
    report = transact(h, h.reports.daily, DAY)
    assert any(a.kind == "record_missing" for a in report.attention_items)
    assert not any(a.kind == "record_not_taken" for a in report.attention_items)


def test_access_and_cursor_isolation(health):
    h = health
    for _ in range(3):
        transact(h, h.checkins.create_or_update, walk(h))
    page = transact(h, h.checkins.list, DAY, limit=2)
    assert page.next_cursor and len(page.items) == 2
    assert len(transact(h, h.checkins.list, DAY, cursor=page.next_cursor).items) == 1
    for actor in [h.actors["unbound_child"], h.actors["stranger_elder"]]:
        with h.factory() as tx, pytest.raises(AppError) as exc:
            h.reports.daily(tx, actor, h.elder, DAY)
        assert exc.value.status == 403
    with pytest.raises(AppError):
        transact(h, h.checkins.list, DAY, cursor="foreign")


def test_retiring_future_task_fails_without_partial_plan_write(health):
    h = health
    p = plan(h)
    with pytest.raises(AppError) as exc:
        transact(h, h.medication.apply_change, "deactivate", p.plan_id, None, 1)
    assert exc.value.status == 501
    with h.factory() as tx:
        row = tx.get(MedicationPlan, p.plan_id)
        assert row.active and row.version == 1


def test_hk_day_and_future_record_rejection(health):
    h = health
    h.clock.advance(seconds=16 * 3600)
    result = transact(h, h.checkins.create_or_update, meal(h))
    assert result.local_date == DAY + timedelta(days=1)
    future = meal(h).model_copy(update={"occurred_at": h.clock.now() + timedelta(seconds=1)})
    with pytest.raises(AppError):
        transact(h, h.checkins.create_or_update, future)


def test_new_after_meal_plan_cannot_backdate_past_obligation(health):
    h = health
    transact(h, h.checkins.create_or_update, meal(h))
    h.clock.advance(seconds=3600)
    plan(h, "after_meal")
    assert not any(t.category == "medication" for t in transact(h, h.checkins.tasks, DAY).items)


def test_schedule_change_cannot_backdate_existing_future_task(health):
    h = health
    p = plan(h)
    before = med_task(h)
    h.clock.advance(seconds=1800)
    transact(h, h.medication.apply_change, "update", p.plan_id,
        PlanPatch(schedule={"mode": "fixed", "slots": [{"slot_id": "one", "local_time": "08:00"}]}), 1)
    after = med_task(h)
    assert after.due_at == before.due_at and after.plan_version == 1


def test_future_settings_retirement_is_explicit_and_atomic(health):
    h = health
    transact(h, h.checkins.tasks, DAY + timedelta(days=1))
    with pytest.raises(AppError) as exc:
        transact(h, h.medication.update_settings, 1,
            SettingsPatch(exercise={"enabled": False, "local_time": "17:00"}))
    assert exc.value.status == 501
    with h.factory() as tx:
        assert tx.get(ElderProfile, h.elder).version == 1
        assert tx.get(MemoryDocument, h.elder) is None
