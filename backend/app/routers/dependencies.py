from dataclasses import dataclass
from typing import Annotated
from fastapi import Depends, Request, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from app.core.uow import UnitOfWork
from app.core.auth import authenticate, require_elder_access
from app.core.errors import AppError
from app.contracts.context import Actor, WriteScope
from app.models.identity import MediaAsset, ChangeProposal
from app.models.health import Checkin, Notification, MedicationPlan
from app.models.agent import AgentAction

bearer = HTTPBearer(auto_error=False)
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

def access(ctx: RequestContext, elder_id: str, scope: WriteScope = "read") -> None:
    ctx.request.app.state.services.access.require_elder_access(ctx.tx, ctx.actor, elder_id, scope)

def resource_access(ctx: RequestContext, kind: str, resource_id: str, scope: WriteScope = "read") -> None:
    model = {"plan": MedicationPlan, "checkin": Checkin, "notification": Notification, "proposal": ChangeProposal, "action": AgentAction, "media": MediaAsset}[kind]
    obj = ctx.tx.get(model, resource_id)
    if not obj:
        raise AppError(404, "NOT_FOUND", "Resource unavailable")
    if kind == "media":
        # Unbound media belongs exclusively to uploader. Shared media needs binding.
        if obj.owner_user_id == ctx.actor.user_id:
            return
        if obj.elder_id is None:
            raise AppError(404, "NOT_FOUND", "Resource unavailable")
    try:
        access(ctx, obj.elder_id, scope)
    except AppError as exc:
        if exc.code == "ELDER_ACCESS_DENIED":
            raise AppError(404, "NOT_FOUND", "Resource unavailable") from exc
        raise

def role(ctx: RequestContext, expected: str) -> None:
    if ctx.actor.role.value != expected:
        raise AppError(403, "ELDER_ACCESS_DENIED", "Role not allowed")
