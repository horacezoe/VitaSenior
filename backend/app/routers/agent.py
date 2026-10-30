from typing import Annotated
from fastapi import APIRouter, Header, Query
from app.schemas.common import Envelope
from app.routers.dependencies import Auth, Context, access
from app.schemas.agent import ASRResult, ASRWrite, ActionDecision, ActionResult, AgentTurn, AgentTurnWrite, MemoryDocument, MemoryUpdate, TTSResult, TTSWrite
from app.application import agent_flows as flows

router = APIRouter()

@router.post('/ai/asr', operation_id='AI01', response_model=Envelope[ASRResult], status_code=200)
def ai01(auth: Auth, body: ASRWrite):
    return auth.request.app.state.respond(auth.request, flows.asr(auth, body))

@router.post('/ai/tts', operation_id='AI02', response_model=Envelope[TTSResult], status_code=200)
def ai02(auth: Auth, body: TTSWrite):
    return auth.request.app.state.respond(auth.request, flows.tts(auth, body))

@router.post('/agent/turns', operation_id='AGENT01', response_model=Envelope[AgentTurn], status_code=201, response_model_exclude_unset=True)
def agent01(auth: Auth, body: AgentTurnWrite, idempotency_key: Annotated[str, Header(alias='Idempotency-Key', min_length=1, max_length=200)]):
    return auth.request.app.state.respond(auth.request, flows.turn(auth, body, idempotency_key))

@router.post('/agent/actions/{action_id}/decision', operation_id='AGENT02', response_model=Envelope[ActionResult], status_code=200, response_model_exclude_unset=True)
def agent02(auth: Auth, action_id: str, body: ActionDecision, idempotency_key: Annotated[str, Header(alias='Idempotency-Key', min_length=1, max_length=200)]):
    return auth.request.app.state.respond(auth.request, flows.decide(auth, action_id, body, idempotency_key))

@router.get('/elders/{elder_id}/memory', operation_id='MEM01', response_model=Envelope[MemoryDocument], status_code=200)
def mem01(ctx: Context, elder_id: str):
    access(ctx, elder_id)
    return ctx.request.app.state.respond(ctx.request, flows.read_memory(ctx, elder_id))

@router.put('/elders/{elder_id}/memory/entries/{entry_id}', operation_id='MEM02', response_model=Envelope[MemoryDocument], status_code=200)
def mem02(ctx: Context, elder_id: str, entry_id: str, body: MemoryUpdate, idempotency_key: Annotated[str, Header(alias='Idempotency-Key', min_length=1, max_length=200)]):
    access(ctx, elder_id, 'self')
    result = flows.update_memory(ctx, elder_id, entry_id, body, idempotency_key)
    ctx.uow.commit()
    return ctx.request.app.state.respond(ctx.request, result)

@router.delete('/elders/{elder_id}/memory/entries/{entry_id}', operation_id='MEM03', response_model=Envelope[MemoryDocument], status_code=200)
def mem03(ctx: Context, elder_id: str, entry_id: str, idempotency_key: Annotated[str, Header(alias='Idempotency-Key', min_length=1, max_length=200)], expected_version: Annotated[int, Query(ge=1)]):
    access(ctx, elder_id, 'self')
    result = flows.delete_memory(ctx, elder_id, entry_id, expected_version, idempotency_key)
    ctx.uow.commit()
    return ctx.request.app.state.respond(ctx.request, result)
