from dataclasses import dataclass
from typing import Annotated
from fastapi import Depends, Request, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from app.core.uow import UnitOfWork
from app.core.auth import authenticate, require_elder_access
from app.core.errors import AppError
from app.contracts.context import Actor, ElderAccess, WriteScope
from app.models.identity import MediaAsset, ChangeProposal
from app.models.health import Checkin, Notification, MedicationPlan
from app.models.agent import AgentAction

bearer = HTTPBearer(auto_error=False)

RESOURCE_MODELS = {"plan": MedicationPlan, "checkin": Checkin, "notification": Notification, "proposal": ChangeProposal, "action": AgentAction, "media": MediaAsset}

@dataclass
class RequestContext:
    request: Request
    tx: Session
    actor: Actor | None
    uow: UnitOfWork

def public_context(request: Request):
    with UnitOfWork(request.app.state.sessions, write=request.method not in {"GET", "HEAD"}) as uow:
        yield RequestContext(request, uow.session, None, uow)

def context(ctx: Annotated[RequestContext, Depends(public_context)], credentials: Annotated[HTTPAuthorizationCredentials | None, Security(bearer)]):
    ctx.actor = authenticate(ctx.tx, credentials.credentials if credentials else None, ctx.request.app.state.clock)
    return ctx
Public = Annotated[RequestContext, Depends(public_context)]
Context = Annotated[RequestContext, Depends(context)]

@dataclass(frozen=True)
class AuthContext:
    """Bearer-authenticated actor with NO open transaction.

    Provider-bound flows (ASR / LLM / TTS) must not sit inside BEGIN IMMEDIATE:
    depend on this, finish the read work, call the provider with no transaction
    open, then open a fresh write UnitOfWork with write_unit() and re-check the
    actor/permission with check_access() inside it. Nothing here commits."""
    request: Request
    actor: Actor

def authenticated(request: Request, credentials: Annotated[HTTPAuthorizationCredentials | None, Security(bearer)]) -> AuthContext:
    # Short read-only UoW, released before the route body runs any slow work.
    with UnitOfWork(request.app.state.sessions, write=False) as uow:
        actor = authenticate(uow.session, credentials.credentials if credentials else None, request.app.state.clock)
    return AuthContext(request, actor)

Auth = Annotated[AuthContext, Depends(authenticated)]

def read_unit(request: Request) -> UnitOfWork:
    return UnitOfWork(request.app.state.sessions, write=False)

def write_unit(request: Request) -> UnitOfWork:
    return UnitOfWork(request.app.state.sessions, write=True)

def check_access(request: Request, tx: Session, actor: Actor, elder_id: str, scope: WriteScope = "read") -> ElderAccess:
    return request.app.state.services.access.require_elder_access(tx, actor, elder_id, scope)

def check_resource(request: Request, tx: Session, actor: Actor, kind: str, resource_id: str, scope: WriteScope = "read") -> None:
    obj = tx.get(RESOURCE_MODELS[kind], resource_id)
    if not obj:
        raise AppError(404, "NOT_FOUND", "Resource unavailable")
    if kind == "media":
        # Unbound media belongs exclusively to uploader. Shared media needs binding.
        if obj.owner_user_id == actor.user_id:
            return
        if obj.elder_id is None:
            raise AppError(404, "NOT_FOUND", "Resource unavailable")
    try:
        check_access(request, tx, actor, obj.elder_id, scope)
    except AppError as exc:
        if exc.code == "ELDER_ACCESS_DENIED":
            raise AppError(404, "NOT_FOUND", "Resource unavailable") from exc
        raise

def access(ctx: RequestContext, elder_id: str, scope: WriteScope = "read") -> None:
    check_access(ctx.request, ctx.tx, ctx.actor, elder_id, scope)

def resource_access(ctx: RequestContext, kind: str, resource_id: str, scope: WriteScope = "read") -> None:
    check_resource(ctx.request, ctx.tx, ctx.actor, kind, resource_id, scope)

def role(ctx: RequestContext, expected: str) -> None:
    if ctx.actor.role.value != expected:
        raise AppError(403, "ELDER_ACCESS_DENIED", "Role not allowed")
