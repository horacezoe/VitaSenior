from __future__ import annotations

from typing import Literal

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.context import Actor
from app.contracts.ports import AccessPort, MediaPort, MemoryPort
from app.core.clock import Clock, SystemClock, local_date
from app.core.errors import AppError, unimplemented
from app.models.health import MedicationPlan as PlanRow, DailyTask, Checkin, Notification
from app.models.identity import ElderProfile
from app.schemas.common import SourceRef
from app.schemas.health import MedicationPlanWrite, MedicationPlan, PlanList, PlanPatch, SettingsPatch, ReminderSettings
from app.services.health_service import authorize, at_local, conflict, invalid, materialize_tasks, settings_for


def plan_dto(row):
    return MedicationPlan(plan_id=row.id, elder_id=row.elder_id, name=row.name,
        dose_display=row.dose_display, schedule=row.schedule, start_date=row.start_date,
        end_date=row.end_date, medicine_asset_id=row.medicine_asset_id, notes=row.notes,
        active=row.active, version=row.version, updated_at=row.updated_at)


class MedicationService:
    def __init__(self, clock: Clock | None = None, *, access: AccessPort | None = None,
                 media: MediaPort | None = None, memory: MemoryPort | None = None):
        self.clock, self.access, self.media, self.memory = clock or SystemClock(), access, media, memory

    def list(self, tx, actor, elder_id, active=None):
        authorize(tx, actor, elder_id, access=self.access)
        query = select(PlanRow).where(PlanRow.elder_id == elder_id).order_by(PlanRow.id)
        if active is not None:
            query = query.where(PlanRow.active == active)
        return PlanList(items=[plan_dto(r) for r in tx.scalars(query)])

    def import_draft(self, tx: Session, actor: Actor, elder_id: str,
                     plans: list[MedicationPlanWrite]) -> list[MedicationPlan]:
        authorize(tx, actor, elder_id, "proposal", self.access)
        return [self.apply_change(tx, actor, elder_id, "create", None, p, None) for p in plans]

    def apply_change(self, tx: Session, actor: Actor, elder_id: str,
                     operation: Literal["create", "update", "deactivate"], target_id: str | None,
                     patch: MedicationPlanWrite | PlanPatch | None, expected_version: int | None) -> MedicationPlan:
        authorize(tx, actor, elder_id, "proposal", self.access)
        now = self.clock.now()
        if operation == "create":
            if target_id is not None or expected_version is not None or not isinstance(patch, MedicationPlanWrite):
                invalid("Create requires a complete plan and no target/version")
            row, candidate = PlanRow(elder_id=elder_id, version=1, active=True), patch
        else:
            row = tx.get(PlanRow, target_id) if target_id else None
            if row is None or row.elder_id != elder_id:
                raise AppError(404, "NOT_FOUND", "Plan unavailable")
            if expected_version != row.version or not row.active:
                conflict("Plan version changed or plan is inactive")
            if operation == "update" and isinstance(patch, PlanPatch):
                data = plan_dto(row).model_dump(include=set(MedicationPlanWrite.model_fields))
                data.update(patch.model_dump(exclude_unset=True))
                try:
                    candidate = MedicationPlanWrite.model_validate(data)
                except ValidationError as exc:
                    raise AppError(422, "VALIDATION_ERROR", "Merged plan is invalid") from exc
            elif operation == "deactivate" and patch is None:
                candidate = None
            else:
                invalid("Operation and patch type do not match")
        if candidate and candidate.medicine_asset_id:
            if self.media is None:
                unimplemented()
            self.media.get_asset(tx, actor, candidate.medicine_asset_id)
        materialize_tasks(tx, elder_id, local_date(now), now)
        changes = []
        if operation != "create":
            for task in tx.scalars(select(DailyTask).where(DailyTask.plan_id == row.id)):
                recorded = tx.scalar(select(Checkin.id).where(Checkin.task_id == task.id))
                delivered = tx.scalar(select(Notification.id).where(
                    Notification.related_task_id == task.id, Notification.delivery_state != "pending"))
                future = task.local_date > local_date(now) or (task.local_date == local_date(now)
                    and (task.waiting_for_meal or (task.due_at and task.due_at > now)))
                if not future or recorded or delivered:
                    continue
                slot = next((s for s in candidate.schedule.slots if task.slot_key == f"{row.id}:{s.slot_id}"), None) if candidate else None
                applicable = candidate and candidate.start_date <= task.local_date and (candidate.end_date is None or candidate.end_date >= task.local_date)
                if slot is None or not applicable:
                    unimplemented()  # needs A's task retirement model; see B.md
                changes.append((task, slot))
            row.version += 1
        if candidate:
            for name, value in candidate.model_dump().items():
                setattr(row, name, candidate.schedule.model_dump(mode="json") if name == "schedule" else value)
        else:
            row.active = False
        row.updated_at = now
        tx.add(row)
        tx.flush()
        for task, slot in changes:
            task.plan_version, task.title, task.dose_display = row.version, row.name, row.dose_display
            task.plan_snapshot = {**task.plan_snapshot, "version": row.version, "name": row.name,
                "dose_display": row.dose_display, "schedule": row.schedule,
                "start_date": row.start_date.isoformat(),
                "end_date": row.end_date.isoformat() if row.end_date else None}
            task.waiting_for_meal = row.schedule["mode"] == "after_meal"
            task.due_at = None if task.waiting_for_meal else at_local(task.local_date, slot.local_time)
        materialize_tasks(tx, elder_id, local_date(now), now)
        tx.flush()
        return plan_dto(row)

    def settings(self, tx, actor, elder_id):
        authorize(tx, actor, elder_id, access=self.access)
        return settings_for(tx, elder_id)

    def update_settings(self, tx, actor, elder_id, expected_version, patch: SettingsPatch):
        authorize(tx, actor, elder_id, "proposal", self.access)
        row = tx.get(ElderProfile, elder_id)
        if row.version != expected_version:
            conflict("Profile/settings version changed")
        materialize_tasks(tx, elder_id, local_date(self.clock.now()), self.clock.now())
        current = settings_for(tx, elder_id).model_dump(exclude={"version"})
        current.update(patch.model_dump(exclude_unset=True, mode="json"))
        result = ReminderSettings.model_validate({**current, "version": row.version + 1})
        row.reminder_settings_json = result.model_dump(mode="json", exclude={"version"})
        row.version += 1
        row.updated_at = self.clock.now()
        if self.memory is None:
            unimplemented()
        self.memory.on_source_changed(tx, actor, elder_id, SourceRef(type="profile", id=elder_id, version=row.version))
        tx.flush()
        return result
