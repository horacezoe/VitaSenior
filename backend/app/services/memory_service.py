from datetime import datetime, date
from typing import Literal
from sqlalchemy.orm import Session
from app.contracts.context import Actor, ElderAccess, WriteScope
from app.core.errors import unimplemented
from app.schemas.common import SourceRef
from app.schemas.identity import BindingCode, Profile, ProfilePatch, ChangeProposal
from app.schemas.health import MedicationPlanWrite, MedicationPlan, PlanPatch, CheckinWrite, CheckinUpdate, Checkin, NotificationEnqueue, Notification, DailyReport
from app.schemas.agent import MemoryDocument

class MemoryService:
    def on_source_changed(self, tx: Session, actor: Actor, elder_id: str, source_ref: SourceRef) -> None:
        unimplemented()
    def context(self, tx: Session, actor: Actor, elder_id: str) -> MemoryDocument:
        unimplemented()
