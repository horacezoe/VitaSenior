from typing import Literal
from sqlalchemy.orm import Session
from app.contracts.context import Actor
from app.core.errors import unimplemented
from app.schemas.health import MedicationPlanWrite, MedicationPlan, PlanPatch

class MedicationService:
    """B owns medication plans. A0/A2 only froze the signatures it needs.

    get_plan is required so A can snapshot the target before a proposal without
    touching B's tables; apply_change keeps plan version and future tasks in sync.
    """

    def get_plan(self, tx: Session, actor: Actor, plan_id: str) -> MedicationPlan:
        unimplemented()

    def import_draft(self, tx: Session, actor: Actor, elder_id: str, plans: list[MedicationPlanWrite]) -> list[MedicationPlan]:
        unimplemented()

    def apply_change(self, tx: Session, actor: Actor, elder_id: str, operation: Literal["create", "update", "deactivate"], target_id: str | None, patch: MedicationPlanWrite | PlanPatch | None, expected_version: int | None) -> MedicationPlan:
        unimplemented()
