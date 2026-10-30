from datetime import datetime, date
from typing import Literal
from sqlalchemy.orm import Session
from app.contracts.context import Actor, ElderAccess, WriteScope
from app.core.errors import unimplemented
from app.schemas.common import SourceRef
from app.schemas.identity import BindingCode, Profile, ProfilePatch, ChangeProposal
from app.schemas.health import MedicationPlanWrite, MedicationPlan, PlanPatch, CheckinWrite, CheckinUpdate, Checkin, NotificationEnqueue, Notification, DailyReport
from app.schemas.agent import MemoryDocument

class MedicationService:
    def import_draft(self, tx: Session, actor: Actor, elder_id: str, plans: list[MedicationPlanWrite]) -> list[MedicationPlan]:
        unimplemented()
    def apply_change(self, tx: Session, actor: Actor, elder_id: str, operation: Literal["create", "update", "deactivate"], target_id: str | None, patch: MedicationPlanWrite | PlanPatch | None, expected_version: int | None) -> MedicationPlan:
        unimplemented()
