"""Deterministic health operations. The caller owns the transaction.

Saved tasks are the denominator; current plans never reconstruct past goals.
"""
from __future__ import annotations
from datetime import date, datetime, time, timedelta
from typing import Literal

from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.context import Actor
from app.contracts.history import DemoHistorySeed
from app.contracts.ports import AccessPort, MediaPort, MemoryPort
from app.core.auth import require_elder_access
from app.core.clock import Clock, HK, UTC, local_date
from app.core.errors import AppError, unimplemented
from app.models.health import Checkin as CheckinRow, DailyTask as TaskRow, MedicationPlan as PlanRow, Notification, DailyGoalBatch, NotificationEvent
from app.models.identity import ElderProfile, User
from app.schemas.common import Page, SourceRef
from app.schemas.health import (
    CancelledCheckin, Checkin, CheckinUpdate, CheckinWrite, DailyTask,
    DietPayload, ExercisePayload, MedicationPayload, ReminderSettings, TaskList,
)

_PAYLOADS = {"diet": DietPayload, "exercise": ExercisePayload, "medication": MedicationPayload}
_WRITE = TypeAdapter(CheckinWrite)


def authorize(tx, actor, elder_id, scope="read", access=None):
    check = access.require_elder_access if access else require_elder_access
    return check(tx, actor, elder_id, scope)


def clock_now(clock: Clock | None):
    if clock is None:
        unimplemented()
    return clock.now()


def invalid(message):
    raise AppError(422, "VALIDATION_ERROR", message)


def conflict(message):
    raise AppError(409, "VERSION_CONFLICT", message)


def at_local(day: date, hhmm: str) -> datetime:
    return datetime.combine(day, time.fromisoformat(hhmm), HK).astimezone(UTC)


def settings_for(tx: Session, elder_id: str) -> ReminderSettings:
    row = tx.get(ElderProfile, elder_id)
    return ReminderSettings.model_validate({**row.reminder_settings_json, "version": row.version})


def checkin_dto(row: CheckinRow) -> Checkin:
    return Checkin(checkin_id=row.id, elder_id=row.elder_id, type=row.type,
        local_date=row.local_date, occurred_at=row.occurred_at, task_id=row.task_id,
        payload=_PAYLOADS[row.type].model_validate(row.payload_json), version=row.version,
        source=row.source, created_at=row.created_at, updated_at=row.updated_at,
        cancelled=row.cancelled_at is not None)


def live_records(tx, elder_id, day):
    return list(tx.scalars(select(CheckinRow).where(CheckinRow.elder_id == elder_id,
        CheckinRow.local_date == day, CheckinRow.cancelled_at.is_(None)
    ).order_by(CheckinRow.occurred_at, CheckinRow.id)))


def task_rows(tx, elder_id, day, *, include_cancelled=False):
    query = select(TaskRow).where(TaskRow.elder_id == elder_id, TaskRow.local_date == day)
    if not include_cancelled:
        query = query.where(TaskRow.cancelled_at.is_(None))
    return list(tx.scalars(query.order_by(TaskRow.category, TaskRow.slot_key)))


def mutable_task(tx, task, now):
    future = task.local_date > local_date(now) or (task.local_date == local_date(now)
        and (task.waiting_for_meal or (task.due_at is not None and task.due_at > now)))
    return bool(future and not tx.scalar(select(CheckinRow.id).where(CheckinRow.task_id == task.id))
        and not tx.scalar(select(Notification.id).where(Notification.related_task_id == task.id,
            Notification.delivery_state != "pending")))


def retire_task(tx, task, now):
    task.cancelled_at = now
    for notice in tx.scalars(select(Notification).where(Notification.related_task_id == task.id,
            Notification.delivery_state == "pending", Notification.task_state.in_(["open", "snoozed"]))):
        notice.task_state = "dismissed"


def known_goal_days(tx, elder_id, now):
    return {local_date(now), *tx.scalars(select(DailyGoalBatch.local_date).where(
        DailyGoalBatch.elder_id == elder_id, DailyGoalBatch.local_date >= local_date(now))),
        *tx.scalars(select(TaskRow.local_date).where(TaskRow.elder_id == elder_id,
            TaskRow.local_date >= local_date(now)))}


def refresh_after_meal(tx, elder_id, day):
    """Use the saved schedule, not the mutable current plan."""
    meals = {r.slot_key: r for r in live_records(tx, elder_id, day) if r.type == "diet"}
    for task in task_rows(tx, elder_id, day):
        if task.category != "medication" or not task.plan_snapshot:
            continue
        schedule = task.plan_snapshot["schedule"]
        if schedule["mode"] != "after_meal":
            continue
        slot = next(s for s in schedule["slots"] if f'{task.plan_id}:{s["slot_id"]}' == task.slot_key)
        meal = meals.get(slot["meal_slot"])
        task.waiting_for_meal = meal is None
        task.due_at = meal.occurred_at + timedelta(minutes=slot["delay_minutes"]) if meal else None
        for notice in tx.scalars(select(Notification).where(Notification.related_task_id == task.id)):
            # A delivered call never returns to pending after a correction.
            if notice.delivery_state == "pending" and notice.task_state in {"open", "snoozed"}:
                if task.due_at is not None:
                    notice.due_at = task.due_at
                # With no meal, query/receipt gates suppress this pending call.
                # Keep its task state so a later corrected meal can reuse it.
    tx.flush()


def materialize_tasks(tx, elder_id, day, now, *, refresh_categories=()):
    existing = {(r.category, r.slot_key): r for r in task_rows(tx, elder_id, day, include_cancelled=True)}
    if day < local_date(now):
        return [r for r in existing.values() if r.cancelled_at is None]
    generated = set(tx.scalars(select(DailyGoalBatch.category).where(
        DailyGoalBatch.elder_id == elder_id, DailyGoalBatch.local_date == day)))
    categories = (set(_PAYLOADS) - generated) | set(refresh_categories)
    settings = settings_for(tx, elder_id)
    meals = {r.slot_key: r for r in live_records(tx, elder_id, day) if r.type == "diet"}

    def add(category, slot_key, title, due_at=None, **kwargs):
        if category not in categories:
            return
        row = existing.get((category, slot_key))
        if row is None:
            row = TaskRow(elder_id=elder_id, local_date=day, category=category,
                slot_key=slot_key, title=title, due_at=due_at,
                source_key=f"task:{elder_id}:{day}:{category}:{slot_key}", **kwargs)
            tx.add(row)
            existing[category, slot_key] = row
        elif row.cancelled_at is not None and mutable_task(tx, row, now):
            row.cancelled_at, row.title, row.due_at = None, title, due_at
            for name, value in kwargs.items():
                setattr(row, name, value)
            for notice in tx.scalars(select(Notification).where(Notification.related_task_id == row.id,
                    Notification.delivery_state == "pending")):
                if not tx.scalar(select(NotificationEvent.id).where(NotificationEvent.notification_id == notice.id)):
                    notice.task_state, notice.title = "open", title
                    if due_at:
                        notice.due_at = due_at
    for meal in settings.meals:
        if meal.enabled:
            add("diet", meal.slot.value, f"记录{meal.slot.value}", at_local(day, meal.local_time))
    if settings.exercise.enabled:
        add("exercise", "daily", "记录今日运动", at_local(day, settings.exercise.local_time))
    for plan in tx.scalars(select(PlanRow).where(PlanRow.elder_id == elder_id,
            PlanRow.active.is_(True), PlanRow.start_date <= day)):
        if plan.end_date and day > plan.end_date:
            continue
        snapshot = {"plan_id": plan.id, "version": plan.version, "name": plan.name,
            "dose_display": plan.dose_display, "schedule": plan.schedule,
            "start_date": plan.start_date.isoformat(),
            "end_date": plan.end_date.isoformat() if plan.end_date else None}
        for slot in plan.schedule["slots"]:
            due = at_local(day, slot["local_time"]) if plan.schedule["mode"] == "fixed" else None
            meal = meals.get(slot.get("meal_slot"))
            effective_due = due or (meal.occurred_at + timedelta(minutes=slot["delay_minutes"]) if meal else None)
            if effective_due and effective_due < plan.updated_at:
                continue  # a new plan cannot introduce already-past obligations
            add("medication", f'{plan.id}:{slot["slot_id"]}', plan.name, due,
                plan_id=plan.id, plan_version=plan.version, plan_snapshot=snapshot,
                dose_display=plan.dose_display, waiting_for_meal=due is None)
    for category in set(_PAYLOADS) - generated:
        tx.add(DailyGoalBatch(elder_id=elder_id, local_date=day, category=category, generated_at=now))
    tx.flush()
    refresh_after_meal(tx, elder_id, day)
    return task_rows(tx, elder_id, day)


def task_dto(task, records):
    related = [r for r in records if r.task_id == task.id]
    if task.category == "exercise":
        related = [r for r in records if r.type == "exercise"]
    completion = "pending"
    if related:
        completion = "not_taken" if task.category == "medication" and related[0].payload_json["intake_status"] == "not_taken" else "completed"
    return DailyTask(task_id=task.id, date=task.local_date, category=task.category,
        slot_key=task.slot_key, plan_id=task.plan_id, plan_version=task.plan_version,
        title=task.title, dose_display=task.dose_display, due_at=task.due_at,
        waiting_for_meal=task.waiting_for_meal, completion=completion,
        checkin_ids=[r.id for r in related], cancelled=task.cancelled_at is not None)


def sync_task_notices(tx, elder_id, day):
    records = live_records(tx, elder_id, day)
    for task in task_rows(tx, elder_id, day):
        recorded = task_dto(task, records).completion != "pending"
        for notice in tx.scalars(select(Notification).where(Notification.related_task_id == task.id)):
            if recorded and notice.task_state in {"open", "snoozed"}:
                notice.task_state = "handled"
            elif not recorded and notice.task_state == "handled":
                notice.task_state = "open"
    tx.flush()


class CheckinService:
    def __init__(self, clock: Clock | None = None, *, access: AccessPort | None = None,
                 memory: MemoryPort | None = None, media: MediaPort | None = None):
        self.clock, self.access, self.memory, self.media = clock, access, memory, media

    def tasks(self, tx: Session, actor: Actor, elder_id: str, day: date) -> TaskList:
        authorize(tx, actor, elder_id, access=self.access)
        rows = materialize_tasks(tx, elder_id, day, clock_now(self.clock))
        records = live_records(tx, elder_id, day)
        return TaskList(date=day, items=[task_dto(t, records) for t in rows])

    def today(self, tx: Session, actor: Actor, elder_id: str, day: date) -> TaskList:
        """A0 TaskPort entry; composition can share this health-domain instance."""
        return self.tasks(tx, actor, elder_id, day)

    def import_demo_history(self, tx: Session, actor: Actor, elder_id: str, *, demo_id: str, days: int, seed: DemoHistorySeed | None = None) -> None:
        """A0 HistoryPort, housed in the approved B file; composition may share
        this instance as history/checkins/tasks. Explicit demo fixtures only.
        """
        from app.fixtures.history import HISTORY_DAYS, history_template
        authorize(tx, actor, elder_id, "self", self.access)
        owner = tx.get(User, actor.user_id)
        elder = tx.get(ElderProfile, elder_id)
        if owner.demo_id != demo_id or elder.onboarding_status != "confirmed":
            invalid("History import requires this confirmed demo household")
        if not 1 <= days <= HISTORY_DAYS:
            invalid("Unsupported history length")
        marker = f"demo:{demo_id}:{elder_id}:history"
        if tx.scalar(select(TaskRow.id).where(TaskRow.source_key == marker)):
            return
        plans = list(tx.scalars(select(PlanRow).where(PlanRow.elder_id == elder_id).order_by(PlanRow.id)))
        plans_by_id = {plan.id: plan for plan in plans}
        if seed and any(plan_id not in plans_by_id for plan_id in seed.plan_ids.values()):
            invalid("History plan does not belong to this elder")
        now = clock_now(self.clock)
        marker_saved = False
        for template in history_template(seed.template_key if seed else "diabetes_daily")[-days:]:
            day = local_date(now) + timedelta(days=template["day_offset"])
            saved = {(r.category, r.slot_key): r for r in task_rows(tx, elder_id, day)}
            def add_task(category, key, title, due_at, **kwargs):
                nonlocal marker_saved
                task = saved.get((category, key))
                if task is None:
                    source = marker if not marker_saved else f"{marker}:{day}:{category}:{key}"
                    task = TaskRow(elder_id=elder_id, local_date=day, category=category,
                        slot_key=key, title=title, due_at=due_at, source_key=source, **kwargs)
                    tx.add(task)
                    tx.flush()
                    saved[category, key] = task
                    marker_saved = True
                return task
            for slot, hhmm in [("breakfast", "08:30"), ("lunch", "12:30"), ("dinner", "18:30")]:
                add_task("diet", slot, f"演示历史餐食 {slot}", at_local(day, hhmm))
            add_task("exercise", "daily", "演示历史运动", at_local(day, "17:00"))

            def add_record(category, payload, task, occurred_at, suffix):
                source = f"{marker}:{day}:record:{category}:{suffix}"
                if tx.scalar(select(CheckinRow.id).where(CheckinRow.source_key == source)):
                    return
                if category in {"diet", "medication"}:
                    condition = (CheckinRow.slot_key == payload["meal_slot"]) if category == "diet" else (CheckinRow.task_id == task.id)
                    if tx.scalar(select(CheckinRow.id).where(CheckinRow.elder_id == elder_id,
                            CheckinRow.type == category, CheckinRow.local_date == day,
                            CheckinRow.cancelled_at.is_(None), condition)):
                        return  # preserve any user record rather than replacing it
                tx.add(CheckinRow(elder_id=elder_id, type=category, local_date=day,
                    occurred_at=occurred_at, task_id=task.id, payload_json=payload,
                    slot_key=payload["meal_slot"] if category == "diet" else None,
                    version=1, revisions_json=[], source="demo_seed", source_key=source,
                    created_at=now, updated_at=now))
                tx.flush()
            for payload in template["diet"]:
                slot = payload["meal_slot"]
                add_record("diet", DietPayload.model_validate(payload).model_dump(mode="json"),
                    saved["diet", slot], at_local(day, "12:00" if slot == "lunch" else "18:00"), slot)
            for index, payload in enumerate(template["exercise"]):
                add_record("exercise", ExercisePayload.model_validate(payload).model_dump(mode="json"),
                    saved["exercise", "daily"], at_local(day, "17:00"), str(index))
            for item in template["medication"]:
                if seed:
                    plan = plans_by_id.get(seed.plan_ids.get(item["plan_key"]))
                    if (plan is None or not plan.active or plan.start_date > day
                            or (plan.end_date is not None and plan.end_date < day)):
                        continue
                else:
                    if len(plans) != 1 or item["plan_index"] >= len(plans):
                        continue  # legacy callers only justify their singleton plan
                    plan = plans[item["plan_index"]]
                slot = next((s for s in plan.schedule["slots"] if s["slot_id"] == item["slot_id"]), None)
                if slot is None:
                    continue
                if plan.schedule["mode"] == "fixed":
                    due = at_local(day, slot["local_time"])
                else:
                    meal = next((r for r in live_records(tx, elder_id, day)
                                 if r.type == "diet" and r.slot_key == slot["meal_slot"]), None)
                    if meal is None:
                        continue  # a meal-relative time requires an actual synthetic meal
                    due = meal.occurred_at + timedelta(minutes=slot["delay_minutes"])
                task = add_task("medication", f'{plan.id}:{slot["slot_id"]}', f"演示历史 {plan.name}",
                    due, plan_id=plan.id, plan_version=plan.version,
                    plan_snapshot={"plan_id": plan.id, "version": plan.version,
                        "name": plan.name, "dose_display": plan.dose_display, "schedule": plan.schedule,
                        "start_date": plan.start_date.isoformat(),
                        "end_date": plan.end_date.isoformat() if plan.end_date else None},
                    dose_display=plan.dose_display)
                payload = MedicationPayload(plan_id=plan.id, slot_id=slot["slot_id"],
                    intake_status=item["intake_status"], notes="演示历史记录").model_dump(mode="json")
                add_record("medication", payload, task, task.due_at, task.slot_key)
            for category in _PAYLOADS:
                if tx.get(DailyGoalBatch, (elder_id, day, category)) is None:
                    tx.add(DailyGoalBatch(elder_id=elder_id, local_date=day, category=category, generated_at=now))
        tx.flush()

    def list(self, tx, actor, elder_id, day, category=None, limit=20, cursor=None):
        authorize(tx, actor, elder_id, access=self.access)
        rows = [r for r in live_records(tx, elder_id, day) if category is None or r.type == category]
        if cursor:
            indexes = [i for i, r in enumerate(rows) if r.id == cursor]
            if not indexes:
                invalid("Cursor does not belong to this query")
            rows = rows[indexes[0] + 1:]
        return Page[Checkin](items=[checkin_dto(r) for r in rows[:limit]],
            next_cursor=rows[limit - 1].id if len(rows) > limit else None)

    def _source_changed(self, tx, actor, row):
        if self.memory is None:
            unimplemented()
        self.memory.on_source_changed(tx, actor, row.elder_id,
            SourceRef(type="checkin", id=row.id, version=row.version))

    def create_or_update(self, tx: Session, actor: Actor, elder_id: str,
                         payload: CheckinWrite | CheckinUpdate, checkin_id: str | None = None, *,
                         source: Literal["user", "agent_confirmed"] = "user") -> Checkin:
        authorize(tx, actor, elder_id, "self", self.access)
        if source not in {"user", "agent_confirmed"}:
            invalid("Only trusted user or agent_confirmed provenance is accepted")
        row = tx.get(CheckinRow, checkin_id) if checkin_id else None
        if checkin_id and (row is None or row.elder_id != elder_id):
            raise AppError(404, "NOT_FOUND", "Record unavailable")
        if isinstance(payload, CheckinUpdate):
            if row is None:
                invalid("An update requires a checkin_id")
            if row.cancelled_at or row.version != payload.expected_version:
                conflict("Record changed or cancelled")
            if not isinstance(payload.payload, _PAYLOADS[row.type]):
                invalid("Payload does not match the original record type")
            value = _WRITE.validate_python({"type": row.type,
                "occurred_at": payload.occurred_at or row.occurred_at,
                "payload": payload.payload, "task_id": row.task_id if row.type == "medication" else None})
        else:
            if checkin_id:
                invalid("Use CheckinUpdate to correct a record")
            value = payload
        if value.occurred_at > clock_now(self.clock):
            invalid("A checkin cannot occur in the future")
        day = local_date(value.occurred_at)
        old_day = row.local_date if row else day
        task = tx.get(TaskRow, value.task_id) if value.task_id else None
        if value.task_id and (task is None or task.elder_id != elder_id or task.category != value.type
                or task.local_date != day or task.cancelled_at is not None):
            invalid("Task, elder, date and record type must match")
        if value.type == "medication":
            plan = tx.get(PlanRow, value.payload.plan_id)
            if (plan is None or plan.elder_id != elder_id or task.plan_id != plan.id
                    or task.slot_key != f"{plan.id}:{value.payload.slot_id}" or not task.plan_snapshot
                    or value.payload.slot_id not in {s["slot_id"] for s in task.plan_snapshot["schedule"]["slots"]}):
                invalid("Medication plan and slot must match the saved task")
            duplicate = tx.scalar(select(CheckinRow).where(CheckinRow.task_id == task.id,
                CheckinRow.type == "medication", CheckinRow.cancelled_at.is_(None)))
            if duplicate and duplicate is not row:
                conflict("Medication task already has a record; use REC03")
        if value.type == "diet":
            if task and task.slot_key != value.payload.meal_slot:
                invalid("Meal slot does not match task")
            duplicate = tx.scalar(select(CheckinRow).where(CheckinRow.elder_id == elder_id,
                CheckinRow.local_date == day, CheckinRow.type == "diet",
                CheckinRow.slot_key == value.payload.meal_slot, CheckinRow.cancelled_at.is_(None)))
            if duplicate and row and duplicate is not row:
                conflict("Another record already occupies this meal")
            row = row or duplicate
            for asset in value.payload.image_asset_ids:
                if self.media is None:
                    unimplemented()
                self.media.get_asset(tx, actor, asset)
        materialize_tasks(tx, elder_id, day, clock_now(self.clock))
        if task is None and value.type in {"diet", "exercise"}:
            key = value.payload.meal_slot if value.type == "diet" else "daily"
            task = next((t for t in task_rows(tx, elder_id, day)
                if t.category == value.type and t.slot_key == key), None)
        if row:
            old_day = row.local_date
            row.revisions_json = [*row.revisions_json, checkin_dto(row).model_dump(mode="json")]
            row.version += 1
        else:
            row = CheckinRow(elder_id=elder_id, type=value.type, version=1,
                created_at=clock_now(self.clock), revisions_json=[])
            tx.add(row)
        row.local_date, row.occurred_at = day, value.occurred_at
        row.payload_json = value.payload.model_dump(mode="json")
        row.source = source
        row.slot_key = value.payload.meal_slot.value if value.type == "diet" else None
        row.task_id, row.updated_at = task.id if task else None, clock_now(self.clock)
        tx.flush()
        if row.version > 1:
            self._source_changed(tx, actor, row)
        for changed_day in {old_day, day}:
            refresh_after_meal(tx, elder_id, changed_day)
            sync_task_notices(tx, elder_id, changed_day)
        return checkin_dto(row)

    def cancel(self, tx, actor, elder_id, checkin_id, expected_version):
        authorize(tx, actor, elder_id, "self", self.access)
        row = tx.get(CheckinRow, checkin_id)
        if row is None or row.elder_id != elder_id:
            raise AppError(404, "NOT_FOUND", "Record unavailable")
        if row.version != expected_version or row.cancelled_at:
            conflict("Record changed or cancelled")
        row.revisions_json = [*row.revisions_json, checkin_dto(row).model_dump(mode="json")]
        row.version += 1
        row.cancelled_at = row.updated_at = clock_now(self.clock)
        self._source_changed(tx, actor, row)
        tx.flush()
        refresh_after_meal(tx, elder_id, row.local_date)
        sync_task_notices(tx, elder_id, row.local_date)
        return CancelledCheckin(checkin_id=row.id, cancelled=True, version=row.version)
