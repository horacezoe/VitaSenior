from datetime import date as Date
from typing import Annotated
from fastapi import APIRouter, Query, Header, UploadFile, File, Form, Response
from app.schemas.common import Envelope, Page
from app.schemas.enums import Category, ProposalStatus, TaskState
from app.routers.dependencies import Context, Public, access, resource_access, role
from app.schemas.agent import ASRResult, ASRWrite, ActionDecision, ActionResult, AgentTurn, AgentTurnWrite, MemoryDocument, MemoryUpdate, TTSResult, TTSWrite
from app.application.agent_flows import unavailable

router = APIRouter()

@router.post("/ai/asr", operation_id="AI01", response_model=Envelope[ASRResult], status_code=200)
def ai01(ctx: Context, body: ASRWrite):
    access(ctx, body.elder_id, "self")
    unavailable(ctx.request.app.state.services)

@router.post("/ai/tts", operation_id="AI02", response_model=Envelope[TTSResult], status_code=200)
def ai02(ctx: Context, body: TTSWrite):
    access(ctx, body.elder_id, "self")
    unavailable(ctx.request.app.state.services)

@router.post("/agent/turns", operation_id="AGENT01", response_model=Envelope[AgentTurn], status_code=201)
def agent01(ctx: Context, body: AgentTurnWrite, idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=200)]):
    access(ctx, body.elder_id, "self")
    unavailable(ctx.request.app.state.services)

@router.post("/agent/actions/{action_id}/decision", operation_id="AGENT02", response_model=Envelope[ActionResult], status_code=200)
def agent02(ctx: Context, action_id: str, body: ActionDecision, idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=200)]):
    resource_access(ctx, "action", action_id, "self")
    unavailable(ctx.request.app.state.services)

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
