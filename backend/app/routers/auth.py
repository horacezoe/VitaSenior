from fastapi import APIRouter
from app.schemas.common import Envelope
from app.schemas.identity import CodeRequest, CodeResponse, LoginRequest, LoginResponse, Me
from app.routers.dependencies import Public, Context

router = APIRouter()
@router.post("/auth/code", operation_id="AUTH01", response_model=Envelope[CodeResponse])
def issue_code(body: CodeRequest, ctx: Public):
    result = ctx.request.app.state.identity.issue_challenge(ctx.tx, body)
    ctx.uow.commit()
    return ctx.request.app.state.respond(ctx.request, result)

@router.post("/auth/login", operation_id="AUTH02", response_model=Envelope[LoginResponse])
def login(body: LoginRequest, ctx: Public):
    result = ctx.request.app.state.identity.login(ctx.tx, body)
    ctx.uow.commit()
    return ctx.request.app.state.respond(ctx.request, result)

@router.get("/me", operation_id="AUTH04", response_model=Envelope[Me])
def me(ctx: Context):
    result = ctx.request.app.state.identity.me(ctx.tx, ctx.actor)
    return ctx.request.app.state.respond(ctx.request, result)
