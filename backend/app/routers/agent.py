from typing import Annotated
from fastapi import APIRouter, Header, Query
from app.schemas.common import Envelope
from app.routers.dependencies import Auth, Context, access, check_access, check_resource, read_unit
from app.schemas.agent import ASRResult, ASRWrite, ActionDecision, ActionResult, AgentTurn, AgentTurnWrite, MemoryDocument, MemoryUpdate, TTSResult, TTSWrite
from app.application.agent_flows import unavailable

router = APIRouter()

# AI routes authenticate without holding a transaction: a provider call (ASR,
# LLM, TTS) must never sit inside BEGIN IMMEDIATE. The permission check runs in a
# short read UoW here; when the flow writes, it opens its own write UoW and must
# re-check access/idempotency before the write (see contracts/ports docstring).
@router.post("/ai/asr", operation_id="AI01", response_model=Envelope[ASRResult], status_code=200)
def ai01(auth: Auth, body: ASRWrite):
    with read_unit(auth.request) as uow:
        check_access(auth.request, uow.session, auth.actor, body.elder_id, "self")
    unavailable(auth.request.app.state.services)

@router.post("/ai/tts", operation_id="AI02", response_model=Envelope[TTSResult], status_code=200)
def ai02(auth: Auth, body: TTSWrite):
    with read_unit(auth.request) as uow:
        check_access(auth.request, uow.session, auth.actor, body.elder_id, "self")
    unavailable(auth.request.app.state.services)

@router.post("/agent/turns", operation_id="AGENT01", response_model=Envelope[AgentTurn], status_code=201)
def agent01(auth: Auth, body: AgentTurnWrite, idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=200)]):
    with read_unit(auth.request) as uow:
        check_access(auth.request, uow.session, auth.actor, body.elder_id, "self")
    unavailable(auth.request.app.state.services)

@router.post("/agent/actions/{action_id}/decision", operation_id="AGENT02", response_model=Envelope[ActionResult], status_code=200)
def agent02(auth: Auth, action_id: str, body: ActionDecision, idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=200)]):
    with read_unit(auth.request) as uow:
        check_resource(auth.request, uow.session, auth.actor, "action", action_id, "self")
    unavailable(auth.request.app.state.services)

@router.get("/elders/{elder_id}/memory", operation_id="MEM01", response_model=Envelope[MemoryDocument], status_code=200)
def mem01(ctx: Context, elder_id: str):
    access(ctx, elder_id)
    unavailable(ctx.request.app.state.services)

@router.put("/elders/{elder_id}/memory/entries/{entry_id}", operation_id="MEM02", response_model=Envelope[MemoryDocument], status_code=200)
def mem02(ctx: Context, elder_id: str, entry_id: str, body: MemoryUpdate, idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=200)]):
    access(ctx, elder_id, "self")
    unavailable(ctx.request.app.state.services)

@router.delete("/elders/{elder_id}/memory/entries/{entry_id}", operation_id="MEM03", response_model=Envelope[MemoryDocument], status_code=200)
def mem03(ctx: Context, elder_id: str, entry_id: str, idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=200)], expected_version: Annotated[int, Query(ge=1)]):
    access(ctx, elder_id, "self")
    unavailable(ctx.request.app.state.services)
