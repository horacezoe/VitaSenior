import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException
from app.core.config import Settings
from app.core.clock import Clock, SystemClock
from app.core.db import build_engine, create_tables, sessions
from app.core.errors import AppError
from app.core.ids import new_id
from app.core.idempotency import Idempotency
from app.composition import compose, compose_identity, declared_capabilities, providers
from app.contracts.bundle import ServiceBundle
from app.scheduler import Scanner
from app.schemas.common import Envelope, ErrorEnvelope, ErrorDetail, Meta
from app.routers import system, auth, identity, health, agent

log = logging.getLogger("vitasenior")
ERROR_RESPONSES = {s: {"model": ErrorEnvelope} for s in (401,403,404,409,413,415,422,429,500,501,502,504)}
# Keep the public contract stable across Python HTTPStatus phrase changes.
ERROR_RESPONSES[413]["description"] = "Content Too Large"
ERROR_RESPONSES[422]["description"] = "Unprocessable Content"

def create_app(settings: Settings | None = None, *, clock: Clock | None = None, services: ServiceBundle | None = None) -> FastAPI:
    settings, clock = settings or Settings(), clock or SystemClock()
    @asynccontextmanager
    async def lifespan(app):
        engine = build_engine(settings.data_dir, settings.database_url)
        app.state.engine = engine
        app.state.sessions = sessions(engine)
        create_tables(engine)
        try:
            await app.state.scanner.start()
            yield
        finally:
            await app.state.scanner.stop()
            engine.dispose()
    app = FastAPI(title="VitaSenior", version="0.1.0", lifespan=lifespan)
    app.state.settings, app.state.clock = settings, clock
    app.state.services = services or compose(clock, settings)
    # The only place capability/provider declarations are read; routers/system.py
    # just renders them so the three developers never edit one shared list.
    app.state.capabilities_declared = declared_capabilities()
    app.state.providers = providers()
    app.state.identity = compose_identity(clock)
    app.state.idempotency = Idempotency(clock)
    app.state.scanner = Scanner(clock, enabled=settings.scanner_enabled, interval=settings.scanner_interval)
    def meta(request):
        return Meta(request_id=getattr(request.state, "request_id", new_id("req")), server_time=clock.now())
    def respond(request, data):
        return {"data": data, "meta": meta(request)}
    app.state.respond = respond
    def error_response(request, status, code, message, details=None, retryable=False):
        body = ErrorEnvelope(error=ErrorDetail(code=code, message=message, details=details or {}, retryable=retryable), meta=meta(request))
        headers = {"X-Request-ID": body.meta.request_id}
        if status == 429:
            headers["Retry-After"] = "300"
        return JSONResponse(status_code=status, content=body.model_dump(mode="json"), headers=headers)
    @app.middleware("http")
    async def request_id(request, call_next):
        request.state.request_id = new_id("req")
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        log.info("%s %s status=%s request_id=%s", request.method, request.url.path, response.status_code, request.state.request_id)
        return response
    @app.exception_handler(AppError)
    async def app_error(request, exc):
        return error_response(request, exc.status, exc.code, exc.message, exc.details, exc.retryable)
    @app.exception_handler(RequestValidationError)
    async def validation(request, exc):
        # Never serialize user input, tokens or arbitrary exception objects.
        errors = [{"loc": list(e['loc']), "type": e['type'], "message": e['msg']} for e in exc.errors()]
        return error_response(request, 422, "VALIDATION_ERROR", "Request validation failed", {"errors": errors})
    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        return error_response(request, exc.status_code, "NOT_FOUND" if exc.status_code == 404 else "HTTP_ERROR", str(exc.detail))
    @app.exception_handler(Exception)
    async def unexpected(request, exc):
        log.error("Unhandled error request_id=%s", getattr(request.state, 'request_id', ''), exc_info=(type(exc), exc, exc.__traceback__))
        return error_response(request, 500, "INTERNAL_ERROR", "Unexpected server error")
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins), allow_methods=["GET","POST","PUT","DELETE"], allow_headers=["Authorization","Content-Type","Idempotency-Key"], expose_headers=["X-Request-ID"])
    for router in (system.router, auth.router, identity.router, health.router, agent.router):
        app.include_router(router, prefix="/api/v1", responses=ERROR_RESPONSES)
    return app

app = create_app()
