"""Health-domain placeholder for today's task list (B implements).

Kept separate from MedicationService: tasks cover diet/exercise/medication and
are not owned by the medication aggregate.
"""
from datetime import date
from sqlalchemy.orm import Session
from app.contracts.context import Actor
from app.core.errors import unimplemented
from app.schemas.health import TaskList

class TaskService:
    def today(self, tx: Session, actor: Actor, elder_id: str, day: date) -> TaskList:
        unimplemented()
