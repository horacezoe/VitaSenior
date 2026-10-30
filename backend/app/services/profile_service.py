"""A owns the confirmed family profile.

Reads are shared with actively bound children; writes are elder-only and version
checked. A confirmed profile is never rewritten by an unconfirmed onboarding draft.
"""
from sqlalchemy.orm import Session
from app.contracts.context import Actor
from app.core.auth import require_elder_access
from app.core.clock import Clock
from app.core.config import Settings
from app.models.identity import ElderProfile
from app.schemas.identity import Profile, ProfilePatch
from app.services.identity_views import profile_from_row, version_conflict

class ProfileService:
    def __init__(self, clock: Clock, settings: Settings):
        self.clock, self.settings = clock, settings

    def read(self, tx: Session, actor: Actor, elder_id: str) -> Profile:
        require_elder_access(tx, actor, elder_id, "read")
        elder = tx.get(ElderProfile, elder_id)
        return profile_from_row(elder)

    def update(self, tx: Session, actor: Actor, elder_id: str, expected_version: int, patch: ProfilePatch) -> Profile:
        require_elder_access(tx, actor, elder_id, "self")
        elder = tx.get(ElderProfile, elder_id)
        if elder.version != expected_version:
            raise version_conflict(elder.version)
        raw = dict(elder.profile_json or {})
        raw.update(patch.model_dump(exclude_unset=True, mode="json"))
        raw["source"] = "user_confirmed"
        elder.profile_json = raw
        elder.version += 1
        elder.updated_at = self.clock.now()
        tx.flush()
        return profile_from_row(elder)
