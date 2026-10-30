from sqlalchemy.orm import Session
from app.contracts.context import Actor
from app.core.clock import Clock
from app.core.errors import unimplemented
from app.schemas.identity import BindingCode, BindingPreview, BindingResult, ElderList

class BindingService:
    """A owns binding codes. Codes are 4 digits with leading zeros, valid 5 minutes,
    revoked when re-issued, consumed exactly once inside the caller's write tx."""

    def __init__(self, clock: Clock):
        self.clock = clock

    def issue_code(self, tx: Session, actor: Actor, elder_id: str) -> BindingCode:
        unimplemented()

    def preview(self, tx: Session, actor: Actor, code: str) -> BindingPreview:
        unimplemented()

    def consume(self, tx: Session, actor: Actor, code: str, relationship: str) -> BindingResult:
        unimplemented()

    def list_elders(self, tx: Session, actor: Actor) -> ElderList:
        unimplemented()
