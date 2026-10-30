from datetime import datetime, date
from typing import Literal
from sqlalchemy.orm import Session
from app.contracts.context import Actor, ElderAccess, WriteScope
from app.core.errors import unimplemented
from app.schemas.common import SourceRef
from app.schemas.identity import BindingCode, Profile, ProfilePatch, ChangeProposal
from app.schemas.health import MedicationPlanWrite, MedicationPlan, PlanPatch, CheckinWrite, CheckinUpdate, Checkin, NotificationEnqueue, Notification, DailyReport
from app.schemas.agent import MemoryDocument

class ChangeService:
    def mark_played(self, tx: Session, actor: Actor, proposal_id: str, now: datetime) -> ChangeProposal:
        unimplemented()
    def apply_due(self, tx: Session, now: datetime) -> list[ChangeProposal]:
        unimplemented()
