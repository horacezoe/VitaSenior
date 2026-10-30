from datetime import datetime, date
from typing import Literal
from sqlalchemy.orm import Session
from app.contracts.context import Actor, ElderAccess, WriteScope
from app.core.errors import unimplemented
from app.schemas.common import SourceRef
from app.schemas.identity import BindingCode, Profile, ProfilePatch, ChangeProposal
from app.schemas.health import MedicationPlanWrite, MedicationPlan, PlanPatch, CheckinWrite, CheckinUpdate, Checkin, NotificationEnqueue, Notification, DailyReport
from app.schemas.agent import MemoryDocument

class NotificationService:
    def enqueue(self, tx: Session, actor: Actor, source_key: str, payload: NotificationEnqueue) -> Notification:
        unimplemented()
