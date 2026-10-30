from sqlalchemy.orm import Session
from app.contracts.context import Actor
from app.core.clock import Clock
from app.core.config import Settings
from app.core.errors import unimplemented
from app.schemas.identity import Profile, ProfilePatch

class ProfileService:
    """A owns the confirmed profile. Reads are shared with bound children; writes
    are elder-only and version-checked."""

    def __init__(self, clock: Clock, settings: Settings):
        self.clock, self.settings = clock, settings

    def read(self, tx: Session, actor: Actor, elder_id: str) -> Profile:
        unimplemented()

    def update(self, tx: Session, actor: Actor, elder_id: str, expected_version: int, patch: ProfilePatch) -> Profile:
        unimplemented()
