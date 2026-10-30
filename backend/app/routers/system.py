from fastapi import APIRouter, Request
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from app.schemas.common import Envelope
from app.routers.dependencies import Context

from app.schemas.system import Health, Runtime

router = APIRouter()

def operation_ids(app) -> set[str]:
    return {op["operationId"] for item in app.openapi()["paths"].values() for method, op in item.items() if method in {"get", "post", "put", "delete"}}

@router.get("/health", operation_id="SYS01", response_model=Envelope[Health])
def health(request: Request):
    db = "ok"
    try:
        with request.app.state.engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except SQLAlchemyError:
        db = "unavailable"
    scanner = request.app.state.scanner
    state = "disabled" if not scanner.enabled else scanner.status
    data = Health(status="ok" if db == "ok" and state not in {"failed", "stopped"} else "degraded", database=db, scheduler=state)
    return request.app.state.respond(request, data)

@router.get("/runtime", operation_id="SYS02", response_model=Envelope[Runtime])
def runtime(ctx: Context):
    # Read-only view. Per-domain capability files own the truth; this route never
    # edits it, never invents a capability and never exposes a secret. (Comment,
    # not a docstring: the OpenAPI snapshot must stay byte-identical for A0.)
    declared = ctx.request.app.state.capabilities_declared
    capabilities = {i: i in declared for i in sorted(operation_ids(ctx.request.app))}
    capabilities["web_push"] = False
    data = Runtime(
        mode="demo",
        providers=dict(ctx.request.app.state.providers),
        capabilities=capabilities,
        timezone="Asia/Hong_Kong",
        server_time=ctx.request.app.state.clock.now(),
    )
    return ctx.request.app.state.respond(ctx.request, data)
