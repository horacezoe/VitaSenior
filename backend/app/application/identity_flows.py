"""Agent A application flows: the only place that coordinates ports + one commit.

Routers stay thin; services never commit. Idempotent endpoints store their success
payload inside the caller's write tx (see app.core.idempotency). Cross-domain
imports (B medication/history, C memory) run in the SAME tx: a 501 from an
unimplemented port rolls the whole confirmation back instead of faking success.
"""
import hashlib
from app.contracts.bundle import ServiceBundle
from app.contracts.context import Actor
from app.contracts.media import MediaContent
from app.core.auth import authenticate
from app.core.errors import unimplemented
from app.core.idempotency import StoredResult
from app.seed import import_demo_history

DEMO_RATE_LIMIT = 10
DEMO_RATE_WINDOW = 60

def unavailable(services: ServiceBundle) -> None:
    """F2 replaces this entry with named flows coordinating typed ports and UoW."""
    unimplemented()

def _state(ctx):
    return ctx.request.app.state

def _client_ip(ctx) -> str:
    client = ctx.request.client
    return getattr(client, "host", None) or "unknown"

def _bearer_token(ctx) -> str | None:
    header = ctx.request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    return token if scheme.lower() == "bearer" and token else None

def _idempotent(ctx, *, key: str, status_code: int, body: dict, operation, actor_id: str | None = None) -> dict:
    state = _state(ctx)
    actor_id = actor_id or (ctx.actor.user_id if ctx.actor else "public")
    def run():
        return StoredResult(status_code, operation())
    return state.idempotency.execute(ctx.tx, actor_id=actor_id, method=ctx.request.method,
                                     path=ctx.request.url.path, key=key, body=body, operation=run).data

# ---- DEMO01 -----------------------------------------------------------------

def create_demo(ctx, body, key: str) -> dict:
    state = _state(ctx)
    # Public entry point: process-local throttle, then idempotent creation.
    state.ratelimit.check(f"demo:{_client_ip(ctx)}", limit=DEMO_RATE_LIMIT, window_seconds=DEMO_RATE_WINDOW)
    def operation():
        experience = state.identity.create_demo_experience(ctx.tx, body, entry_base=state.settings.public_base_url)
        return experience.model_dump(mode="json")
    return _idempotent(ctx, key=key, status_code=201, body=body.model_dump(mode="json"), operation=operation, actor_id="public")

# ---- ONB01/ONB02 ------------------------------------------------------------

def match_onboarding(ctx, elder_id: str, body, key: str) -> dict:
    state = _state(ctx)
    def operation():
        return state.identity.match_onboarding(ctx.tx, ctx.actor, elder_id, body).model_dump(mode="json")
    return _idempotent(ctx, key=key, status_code=200,
                       body={"elder_id": elder_id, **body.model_dump(mode="json")}, operation=operation)

def confirm_onboarding(ctx, elder_id: str, body, key: str) -> dict:
    state = _state(ctx)
    def operation():
        profile, draft = state.identity.confirm_onboarding(ctx.tx, ctx.actor, elder_id, body)
        if body.medication_plans:
            # B owns medication rows; the plan import commits with the profile.
            state.services.medication.import_draft(ctx.tx, ctx.actor, elder_id, body.medication_plans)
        if draft.get("matched") and draft.get("demo_id"):
            import_demo_history(ctx.tx, state.services, ctx.actor, elder_id, demo_id=draft["demo_id"])
        return profile.model_dump(mode="json")
    return _idempotent(ctx, key=key, status_code=200,
                       body={"elder_id": elder_id, **body.model_dump(mode="json")}, operation=operation)

# ---- PROF01/02 --------------------------------------------------------------

def read_profile(ctx, elder_id: str):
    return _state(ctx).services.profile.read(ctx.tx, ctx.actor, elder_id)

def update_profile(ctx, elder_id: str, body, key: str) -> dict:
    state = _state(ctx)
    def operation():
        return state.services.profile.update(ctx.tx, ctx.actor, elder_id, body.expected_version, body.patch).model_dump(mode="json")
    return _idempotent(ctx, key=key, status_code=200,
                       body={"elder_id": elder_id, **body.model_dump(mode="json")}, operation=operation)

# ---- BIND01-04 --------------------------------------------------------------

def issue_binding_code(ctx, elder_id: str, key: str) -> dict:
    state = _state(ctx)
    def operation():
        return state.services.binding.issue_code(ctx.tx, ctx.actor, elder_id).model_dump(mode="json")
    return _idempotent(ctx, key=key, status_code=201, body={"elder_id": elder_id}, operation=operation)

def preview_binding(ctx, body):
    return _state(ctx).services.binding.preview(ctx.tx, ctx.actor, body.code)

def consume_binding(ctx, body, key: str) -> dict:
    state = _state(ctx)
    def operation():
        return state.services.binding.consume(ctx.tx, ctx.actor, body.code, body.relationship).model_dump(mode="json")
    return _idempotent(ctx, key=key, status_code=201, body=body.model_dump(mode="json"), operation=operation)

def list_bound_elders(ctx):
    return _state(ctx).services.binding.list_elders(ctx.tx, ctx.actor)

# ---- MEDIA01-03 -------------------------------------------------------------

def upload_media(ctx, *, key: str, purpose: str, elder_id: str | None, filename: str | None,
                 content_type: str | None, content: bytes) -> dict:
    state = _state(ctx)
    fingerprint = {"purpose": purpose, "elder_id": elder_id, "filename": filename,
                   "content_type": content_type, "size_bytes": len(content),
                   "sha256": hashlib.sha256(content).hexdigest()}
    def operation():
        asset = state.services.media.store_upload(ctx.tx, ctx.actor, elder_id=elder_id, purpose=purpose,
                                                 filename=filename or "upload", content_type=content_type or "",
                                                 content=content)
        return asset.model_dump(mode="json")
    return _idempotent(ctx, key=key, status_code=201, body=fingerprint, operation=operation)

def read_media(ctx, asset_id: str):
    return _state(ctx).services.media.get_asset(ctx.tx, ctx.actor, asset_id)

def media_content(ctx, asset_id: str, ticket: str | None) -> MediaContent:
    """MEDIA03: a valid ticket alone is enough; otherwise a Bearer actor must prove access."""
    actor: Actor | None = None
    if ticket is None:
        actor = authenticate(ctx.tx, _bearer_token(ctx), _state(ctx).clock)
    return _state(ctx).services.media.open_content(ctx.tx, actor, asset_id, ticket=ticket)
