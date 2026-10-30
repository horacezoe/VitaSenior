from datetime import datetime
from sqlalchemy.orm import Session
from app.contracts.context import Actor
from app.core.clock import Clock
from app.core.config import Settings
from app.core.errors import unimplemented
from app.schemas.common import Page
from app.schemas.enums import ProposalStatus
from app.schemas.identity import ChangeDecision, ChangeProposal, ChangeProposalWrite

class ChangeService:
    """A owns the child-proposal state machine. A child submit never changes the
    target; only elder accept or the server 60-second timeout applies it."""

    def __init__(self, clock: Clock, settings: Settings):
        self.clock, self.settings = clock, settings

    def create(self, tx: Session, actor: Actor, elder_id: str, body: ChangeProposalWrite, now: datetime) -> ChangeProposal:
        unimplemented()

    def query(self, tx: Session, actor: Actor, elder_id: str, status: ProposalStatus | None, limit: int, cursor: str | None) -> Page[ChangeProposal]:
        unimplemented()

    def read(self, tx: Session, actor: Actor, proposal_id: str) -> ChangeProposal:
        unimplemented()

    def decide(self, tx: Session, actor: Actor, proposal_id: str, decision: ChangeDecision, now: datetime) -> ChangeProposal:
        unimplemented()

    def mark_played(self, tx: Session, actor: Actor, proposal_id: str, now: datetime) -> ChangeProposal:
        unimplemented()

    def apply_due(self, tx: Session, now: datetime) -> list[ChangeProposal]:
        unimplemented()
