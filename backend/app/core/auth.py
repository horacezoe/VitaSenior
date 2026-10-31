import hashlib
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.clock import Clock
from app.core.errors import AppError
from app.contracts.context import Actor, ElderAccess, WriteScope, SYSTEM_USER_ID
from app.schemas.enums import Role
from app.models.identity import AuthSession, User, ElderProfile, FamilyBinding

def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()

def authenticate(tx: Session, token: str | None, clock: Clock) -> Actor:
    if not token:
        raise AppError(401, "UNAUTHENTICATED", "Bearer token required")
    session = tx.scalar(select(AuthSession).where(AuthSession.token_hash == token_hash(token)))
    if session is None:
        raise AppError(401, "UNAUTHENTICATED", "Invalid token")
    if session.expires_at <= clock.now():
        raise AppError(401, "SESSION_EXPIRED", "Session expired")
    user = tx.get(User, session.user_id)
    return Actor(user.id, Role(user.role))

def require_elder_access(tx: Session, actor: Actor, elder_id: str, write_scope: WriteScope = "read") -> ElderAccess:
    elder = tx.get(ElderProfile, elder_id)
    if actor.user_id == SYSTEM_USER_ID:
        # The due-proposal scanner is the only system principal. It is a reserved id
        # that AUTH never issues, so this cannot be reached from a request header;
        # the applied action is still audited as applied_by="timeout".
        if elder is None:
            raise AppError(403, "ELDER_ACCESS_DENIED", "No access to this elder")
        return ElderAccess(elder.id, elder.owner_user_id, "system")
    owner = elder is not None and elder.owner_user_id == actor.user_id and actor.role == Role.elder
    bound = elder is not None and actor.role == Role.child and tx.scalar(select(FamilyBinding.id).where(FamilyBinding.elder_id == elder_id, FamilyBinding.child_user_id == actor.user_id, FamilyBinding.status == "active")) is not None
    # Same denial for unknown and unauthorized elders: no existence oracle.
    if not (owner or bound):
        raise AppError(403, "ELDER_ACCESS_DENIED", "No access to this elder")
    if write_scope == "proposal" and not owner:
        raise AppError(403, "PROPOSAL_REQUIRED", "A child must submit a change proposal")
    if write_scope == "self" and not owner:
        raise AppError(403, "ELDER_ACCESS_DENIED", "Only the elder may perform this action")
    if write_scope == "child" and not bound:
        raise AppError(403, "ELDER_ACCESS_DENIED", "An active child binding is required")
    return ElderAccess(elder.id, elder.owner_user_id, write_scope)
