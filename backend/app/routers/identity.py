from typing import Annotated, Literal
from fastapi import APIRouter, Query, Header, UploadFile, File, Form, Response
from fastapi.responses import FileResponse
from app.schemas.common import Envelope, Page
from app.schemas.enums import ProposalStatus
from app.routers.dependencies import Context, Public, access, resource_access, role
from app.schemas.identity import BindingCode, BindingPreview, BindingPreviewWrite, BindingResult, BindingWrite, ChangeDecision, ChangeProposal, ChangeProposalWrite, ConfirmWrite, DemoExperience, DemoWrite, ElderList, MatchResult, MatchWrite, MediaAsset, Profile, ProfileUpdate
from app.application import identity_flows as flows

router = APIRouter()

@router.post("/demo/experiences", operation_id="DEMO01", response_model=Envelope[DemoExperience], status_code=201)
def demo01(ctx: Public, body: DemoWrite, idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=200)]):
    data = flows.create_demo(ctx, body, idempotency_key)
    ctx.uow.commit()
    return ctx.request.app.state.respond(ctx.request, data)

@router.post("/elders/{elder_id}/onboarding/match", operation_id="ONB01", response_model=Envelope[MatchResult], status_code=200)
def onb01(ctx: Context, elder_id: str, body: MatchWrite, idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=200)]):
    access(ctx, elder_id, "self")
    data = flows.match_onboarding(ctx, elder_id, body, idempotency_key)
    ctx.uow.commit()
    return ctx.request.app.state.respond(ctx.request, data)

@router.post("/elders/{elder_id}/onboarding/confirm", operation_id="ONB02", response_model=Envelope[Profile], status_code=200)
def onb02(ctx: Context, elder_id: str, body: ConfirmWrite, idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=200)]):
    access(ctx, elder_id, "self")
    data = flows.confirm_onboarding(ctx, elder_id, body, idempotency_key)
    ctx.uow.commit()
    return ctx.request.app.state.respond(ctx.request, data)

@router.get("/elders/{elder_id}/profile", operation_id="PROF01", response_model=Envelope[Profile], status_code=200)
def prof01(ctx: Context, elder_id: str):
    access(ctx, elder_id)
    data = flows.read_profile(ctx, elder_id)
    return ctx.request.app.state.respond(ctx.request, data)

@router.put("/elders/{elder_id}/profile", operation_id="PROF02", response_model=Envelope[Profile], status_code=200)
def prof02(ctx: Context, elder_id: str, body: ProfileUpdate, idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=200)]):
    access(ctx, elder_id, "proposal")
    data = flows.update_profile(ctx, elder_id, body, idempotency_key)
    ctx.uow.commit()
    return ctx.request.app.state.respond(ctx.request, data)

@router.post("/elders/{elder_id}/binding-codes", operation_id="BIND01", response_model=Envelope[BindingCode], status_code=201)
def bind01(ctx: Context, elder_id: str, idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=200)]):
    access(ctx, elder_id, "self")
    data = flows.issue_binding_code(ctx, elder_id, idempotency_key)
    ctx.uow.commit()
    return ctx.request.app.state.respond(ctx.request, data)

@router.post("/family-bindings/preview", operation_id="BIND02", response_model=Envelope[BindingPreview], status_code=200)
def bind02(ctx: Context, body: BindingPreviewWrite):
    role(ctx, "child")
    data = flows.preview_binding(ctx, body)
    return ctx.request.app.state.respond(ctx.request, data)

@router.post("/family-bindings", operation_id="BIND03", response_model=Envelope[BindingResult], status_code=201)
def bind03(ctx: Context, body: BindingWrite, idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=200)]):
    role(ctx, "child")
    data = flows.consume_binding(ctx, body, idempotency_key)
    ctx.uow.commit()
    return ctx.request.app.state.respond(ctx.request, data)

@router.get("/me/elders", operation_id="BIND04", response_model=Envelope[ElderList], status_code=200)
def bind04(ctx: Context):
    role(ctx, "child")
    data = flows.list_bound_elders(ctx)
    return ctx.request.app.state.respond(ctx.request, data)

@router.post("/media", operation_id="MEDIA01", response_model=Envelope[MediaAsset], status_code=201)
def media01(ctx: Context, idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=200)], file: Annotated[UploadFile, File()], purpose: Annotated[Literal["meal", "ingredient", "medicine", "face", "voice_message", "agent_audio", "document"], Form()], elder_id: Annotated[str | None, Form()] = None):
    if elder_id is not None:
        access(ctx, elder_id)
    content = file.file.read()
    data = flows.upload_media(ctx, key=idempotency_key, purpose=purpose, elder_id=elder_id,
                              filename=file.filename, content_type=file.content_type, content=content)
    ctx.uow.commit()
    return ctx.request.app.state.respond(ctx.request, data)

@router.get("/media/{asset_id}", operation_id="MEDIA02", response_model=Envelope[MediaAsset], status_code=200)
def media02(ctx: Context, asset_id: str):
    data = flows.read_media(ctx, asset_id)
    return ctx.request.app.state.respond(ctx.request, data)

# Either a Bearer actor or a short-lived ticket authorises the bytes, so <audio>
# and <img> can load content without an Authorization header. The optional security
# requirement is declared explicitly because the route intentionally has no
# mandatory bearer dependency.
@router.get("/media/{asset_id}/content", operation_id="MEDIA03", response_class=Response,
            openapi_extra={"security": [{"HTTPBearer": []}, {}]},
            responses={200: {"content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}}}})
def media03(ctx: Public, asset_id: str, ticket: str | None = None):
    content = flows.media_content(ctx, asset_id, ticket)
    return FileResponse(content.path, media_type=content.mime_type)

@router.post("/elders/{elder_id}/change-proposals", operation_id="CHANGE01", response_model=Envelope[ChangeProposal], status_code=201)
def change01(ctx: Context, elder_id: str, body: ChangeProposalWrite, idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=200)]):
    access(ctx, elder_id, "child")
    data = flows.create_change(ctx, elder_id, body, idempotency_key)
    ctx.uow.commit()
    return ctx.request.app.state.respond(ctx.request, data)

@router.get("/elders/{elder_id}/change-proposals", operation_id="CHANGE02", response_model=Envelope[Page[ChangeProposal]], status_code=200)
def change02(ctx: Context, elder_id: str, status: ProposalStatus | None = None, limit: Annotated[int, Query(ge=1, le=100)] = 20, cursor: str | None = None):
    access(ctx, elder_id)
    data = flows.list_changes(ctx, elder_id, status, limit, cursor)
    return ctx.request.app.state.respond(ctx.request, data)

@router.get("/change-proposals/{proposal_id}", operation_id="CHANGE03", response_model=Envelope[ChangeProposal], status_code=200)
def change03(ctx: Context, proposal_id: str):
    resource_access(ctx, "proposal", proposal_id)
    data = flows.read_change(ctx, proposal_id)
    return ctx.request.app.state.respond(ctx.request, data)

@router.post("/change-proposals/{proposal_id}/decision", operation_id="CHANGE04", response_model=Envelope[ChangeProposal], status_code=200)
def change04(ctx: Context, proposal_id: str, body: ChangeDecision, idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=200)]):
    resource_access(ctx, "proposal", proposal_id, "self")
    data = flows.decide_change(ctx, proposal_id, body, idempotency_key)
    ctx.uow.commit()
    return ctx.request.app.state.respond(ctx.request, data)
