from app.contracts.bundle import ServiceBundle
from app.contracts.context import Actor
from collections.abc import Callable
from sqlalchemy.orm import Session
from app.core.errors import unimplemented
from app.core.idempotency import StoredResult
from app.core.uow import UnitOfWork
from app.core.auth import authenticate
from app.core.errors import AppError
from app.schemas.health import Checkin, NotificationEnqueue
from app.schemas.common import DTO
from pathlib import Path
import json
import hashlib
from app.routers.dependencies import check_access, check_resource, RESOURCE_MODELS
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse


def perform(auth, *, service_name: str, operation: Callable[[ServiceBundle, Session, Actor, str], DTO], elder_id=None, resource=None,
            scope="read", body=None, key=None, status=200, snapshot=False):
    """Short transaction coordinating frozen ports and shared idempotency.

    Read endpoints that materialize goals deliberately use BEGIN IMMEDIATE so
    concurrent TASK/report requests cannot race the daily unique constraint.
    Unwired bundles fail explicitly instead of mixing service/application clocks.
    """
    request = auth.request
    services = request.app.state.services
    target = getattr(services, service_name)
    write = key is not None or snapshot or request.method not in {"GET", "HEAD"}
    with UnitOfWork(request.app.state.sessions, write=write) as uow:
        tx = uow.session
        scheme, _, token = request.headers.get("authorization", "").partition(" ")
        actor = authenticate(tx, token if scheme.lower() == "bearer" else None, request.app.state.clock)
        if resource:
            kind, resource_id = resource
            check_resource(request, tx, actor, kind, resource_id, scope)
            elder_id = tx.get(RESOURCE_MODELS[kind], resource_id).elder_id
        else:
            check_access(request, tx, actor, elder_id, scope)
        operation_id = request.scope["route"].operation_id
        if operation_id not in request.app.state.capabilities_declared:
            unimplemented()
        if getattr(target, "clock", None) is not request.app.state.clock:
            unimplemented()

        def execute():
            result = operation(services, tx, actor, elder_id)
            actual_status = 200 if status == 201 and isinstance(result, Checkin) and result.version > 1 else status
            return StoredResult(actual_status, result.model_dump(mode="json", exclude_unset=True))

        if key is not None:
            result = request.app.state.idempotency.execute(tx, actor_id=actor.user_id,
                method=request.method, path=request.url.path, key=key, body=body, operation=execute)
        else:
            result = execute()
        uow.commit()
    response = request.app.state.respond(request, result.data)
    if status == 201 and service_name == "checkins" and result.status_code == 200:
        response["meta"].replaced = True
    return JSONResponse(status_code=result.status_code, content=jsonable_encoder(response))

def family_reminder(auth, elder_id, body, key):
    """Prepare fixed speech / controlled user recording bytes outside the write
    lock. The one idempotent write rechecks ownership and registers the message
    for this household, so an unbound private upload can safely be shared.
    """
    request, state = auth.request, auth.request.app.state
    root = Path(__file__).resolve().parents[2] / "fixtures" / "health"
    templates = json.loads((root / "templates.json").read_text(encoding="utf-8"))
    if body.template_id and body.template_id not in templates:
        raise AppError(422, "VALIDATION_ERROR", "Unknown reminder template")
    text = body.text or (templates[body.template_id]["text"] if body.template_id else "请收听家人的录音。")
    media = None
    with UnitOfWork(state.sessions, write=False) as unit:
        check_access(request, unit.session, auth.actor, elder_id, "child")
        if body.audio_asset_id:
            state.services.media.assert_owned_voice(unit.session, auth.actor, body.audio_asset_id)
            media = state.services.media.open_content(unit.session, auth.actor, body.audio_asset_id)
    audio, mime = None, "audio/wav"
    if media:
        if media.size_bytes > 15 * 1024 * 1024:
            raise AppError(413, "MEDIA_TOO_LARGE", "Voice message exceeds 15 MiB")
        try:
            with media.path.open("rb") as stream:
                audio = stream.read(15 * 1024 * 1024 + 1)
        except FileNotFoundError as exc:
            raise AppError(404, "NOT_FOUND", "Voice content unavailable") from exc
        if len(audio) > 15 * 1024 * 1024:
            raise AppError(413, "MEDIA_TOO_LARGE", "Voice message exceeds 15 MiB")
        mime = media.mime_type
    else:
        for sample in json.loads((root / "audio_manifest.json").read_text(encoding="utf-8-sig")):
            if sample["text"] == text:
                audio = (root / sample["file"]).read_bytes()
                if hashlib.sha256(audio).hexdigest() != sample["sha256"]:
                    raise AppError(502, "PROVIDER_ERROR", "Demo speech integrity check failed")
                break

    def operation(services, tx, actor, elder):
        if body.audio_asset_id:
            services.media.assert_owned_voice(tx, actor, body.audio_asset_id)
        # Registration is bounded local persistence through A's port. Speech
        # generation and recording reads have finished before this write tx.
        asset = services.media.store_upload(tx, actor, elder_id=elder, purpose="voice_message",
            filename="reminder.wav", content_type=mime, content=audio) if audio else None
        payload = NotificationEnqueue(**body.model_dump(exclude={"audio_asset_id", "text"}),
            elder_id=elder, kind="family_voice", title="家人的关怀提醒", text=text,
            audio_asset_id=asset.asset_id if asset else None, due_at=state.clock.now())
        return services.notifications.enqueue(tx, actor, f"family:{elder}:{actor.user_id}:{key}", payload)
    return perform(auth, service_name="notifications", elder_id=elder_id, scope="child",
        body=body.model_dump(mode="json"), key=key, status=201, operation=operation)
