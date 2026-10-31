"""C orchestration: providers never run while a Session is held."""
from dataclasses import replace
import time
from pydantic import TypeAdapter, ValidationError
from app.core.auth import authenticate
from app.core.clock import local_date
from app.core.errors import AppError, unimplemented
from app.core.idempotency import StoredResult
from app.providers.planning import ImageInput, request_digest
from app.providers.real_understanding import MAX_IMAGE_BYTES, MAX_TOTAL_IMAGE_BYTES
from app.routers.dependencies import check_access, check_resource, read_unit, write_unit
from app.schemas.agent import Action, AgentTurn, ASRResult, TTSResult


def unavailable(services):
    unimplemented()


def _ready(state):
    if not all(hasattr(state, name) for name in ('agent', 'agent_chat', 'agent_asr', 'agent_tts')):
        raise AppError(501, 'MODULE_NOT_IMPLEMENTED', 'C2 awaits A-owned composition wiring; see C handoff')


def _reauthorize(auth, tx, elder_id=None):
    header = auth.request.headers.get('authorization', '')
    scheme, _, token = header.partition(' ')
    actor = authenticate(tx, token if scheme.lower() == 'bearer' else None, auth.request.app.state.clock)
    if actor != auth.actor:
        raise AppError(401, 'UNAUTHENTICATED', 'Session actor changed')
    if elder_id is not None:
        check_access(auth.request, tx, actor, elder_id, 'self')


def _context_access(auth, tx, body):
    _reauthorize(auth, tx, body.elder_id)
    if body.context.notification_id:
        check_resource(auth.request, tx, auth.actor, 'notification', body.context.notification_id, 'self')


def _store(state, tx, actor, request, key, body, status, operation):
    return state.idempotency.execute(
        tx, actor_id=actor.user_id, method=request.method, path=request.url.path,
        key=key, body=body,
        operation=lambda: StoredResult(status, operation().model_dump(mode='json', exclude_unset=True)),
    ).data


def _content_bytes(content):
    # Exact handle from MediaPort, never an inferred local path.
    if content.size_bytes > 15 * 1024 * 1024:
        raise AppError(413, 'MEDIA_TOO_LARGE', 'Audio exceeds 15 MiB')
    try:
        with content.path.open('rb') as stream:
            raw = stream.read(15 * 1024 * 1024 + 1)
    except FileNotFoundError as exc:
        raise AppError(404, 'NOT_FOUND', 'Audio content unavailable') from exc
    if len(raw) > 15 * 1024 * 1024:
        raise AppError(413, 'MEDIA_TOO_LARGE', 'Audio exceeds 15 MiB')
    return raw


def _is_mock(provider):
    return getattr(provider, 'is_mock', getattr(provider, 'name', 'mock') == 'mock')


def _speech_provider(provider, speech):
    name = getattr(provider, 'name', 'mock' if speech.is_mock else 'real')
    if (not isinstance(name, str) or not name.strip() or name in {'not_used', 'not_implemented'}
            or bool(speech.is_mock) != (name == 'mock')):
        raise AppError(502, 'PROVIDER_ERROR', 'Speech provenance differs from the configured provider')
    return name


def _image_bytes(content):
    if content.size_bytes > MAX_IMAGE_BYTES:
        raise AppError(413, 'MEDIA_TOO_LARGE', 'Real understanding allows at most 5 MiB per image')
    try:
        with content.path.open('rb') as stream:
            raw = stream.read(MAX_IMAGE_BYTES + 1)
    except FileNotFoundError as exc:
        raise AppError(404, 'NOT_FOUND', 'Image content unavailable') from exc
    if len(raw) > MAX_IMAGE_BYTES:
        raise AppError(413, 'MEDIA_TOO_LARGE', 'Real understanding allows at most 5 MiB per image')
    return raw


def asr(auth, body):
    state = auth.request.app.state
    with read_unit(auth.request) as unit:
        _reauthorize(auth, unit.session, body.elder_id)
        _ready(state)
        content = state.services.media.open_content(unit.session, auth.actor, body.audio_asset_id)
    result = state.agent_asr.transcribe(_content_bytes(content), content.mime_type, body.mock_fixture_id)
    result = ASRResult.model_validate(result)
    with read_unit(auth.request) as unit:
        _reauthorize(auth, unit.session, body.elder_id)
        _ready(state)
        state.services.media.get_asset(unit.session, auth.actor, body.audio_asset_id)
    return result


def tts(auth, body):
    state = auth.request.app.state
    with read_unit(auth.request) as unit:
        _reauthorize(auth, unit.session, body.elder_id)
        _ready(state)
    speech = state.agent_tts.synthesize(body.text, body.voice_id)
    provider_name = _speech_provider(state.agent_tts, speech)
    if speech.text != body.text:
        raise AppError(502, 'PROVIDER_ERROR', 'Speech text differs from the requested text')
    with write_unit(auth.request) as unit:
        _reauthorize(auth, unit.session, body.elder_id)
        asset = state.services.media.register_generated(
            unit.session, auth.actor, body.elder_id, content=speech.content,
            mime_type=speech.mime_type, purpose='agent_audio', duration_ms=speech.duration_ms)
        unit.commit()
    return TTSResult(audio_asset=asset, provider=provider_name, is_mock=speech.is_mock)


def _proposal_id(services, tx, actor, elder_id, notification_id):
    if not notification_id:
        return None
    cursor, seen = None, set()
    for _ in range(100):
        page = services.changes.query(tx, actor, elder_id, None, 100, cursor)
        for proposal in page.items:
            if proposal.notification_id == notification_id:
                return proposal.proposal_id
        cursor = page.next_cursor
        if cursor is None or cursor in seen:
            return None
        seen.add(cursor)
    raise AppError(422, 'VALIDATION_ERROR', 'Too many proposals to resolve this notification')


def _needs_tasks(body, chat=None):
    if chat is not None and not _is_mock(chat):
        return False  # F2 real understanding is diet-only; no medication preparation.
    return body.mock_fixture_id == 'medication_confirm' or (
        body.mock_fixture_id is None and (body.text or '').strip() in {'吃了药', '我吃药了'})


def _snapshot(auth, tx, body, *, include_tasks=True):
    state = auth.request.app.state
    profile = state.services.profile.read(tx, auth.actor, body.elder_id)
    tasks, slots = [], {}
    if include_tasks and _needs_tasks(body, state.agent_chat):
        tasks = state.services.tasks.today(tx, auth.actor, body.elder_id, local_date(state.clock.now())).items
        for task in tasks:
            if task.category != 'medication' or not task.plan_id:
                continue
            plan = state.services.medication.get_plan(tx, auth.actor, task.plan_id)
            if plan.elder_id != body.elder_id or plan.version != task.plan_version:
                raise AppError(409, 'VERSION_CONFLICT', 'Task snapshot no longer matches current plan')
            for slot in plan.schedule.slots:
                # Derive from actual plan slots, never parse slot_key as slot_id.
                if task.slot_key == f'{plan.plan_id}:{slot.slot_id}':
                    slots[task.task_id] = slot.slot_id
    snapshot = state.agent.read_snapshot(tx, auth.actor, body, profile=profile,
                                         tasks=tasks, medication_slots=slots)
    return replace(snapshot, proposal_id=_proposal_id(state.services, tx, auth.actor,
                                                      body.elder_id, body.context.notification_id))


def turn(auth, body, key):
    state = auth.request.app.state
    deadline = time.monotonic() + 45.0
    def remaining():
        value = deadline - time.monotonic()
        if value <= 0:
            raise AppError(504, 'PROVIDER_TIMEOUT', 'Agent total deadline exceeded', retryable=True)
        return value
    content = None
    image_handles = []
    audio_only = bool(body.audio_asset_id and not body.text)
    materializing = _needs_tasks(body, state.agent_chat) and not audio_only
    # TaskPort.today may create today's goals. Persist those stable IDs in a
    # separate SHORT transaction; never retain its write lock for a provider.
    # Targets are not intake facts: no Checkin is written before confirmation.
    with (write_unit(auth.request) if materializing else read_unit(auth.request)) as unit:
        _context_access(auth, unit.session, body)
        _ready(state)
        previous = state.agent.replay(unit.session, auth.actor, body)
        snapshot = None if previous else _snapshot(auth, unit.session, body, include_tasks=not audio_only)
        if previous is None and body.audio_asset_id and not body.text:
            content = state.services.media.open_content(unit.session, auth.actor, body.audio_asset_id)
        if previous is None and not _is_mock(state.agent_chat):
            for asset_id in body.image_asset_ids:
                handle = state.services.media.open_content(unit.session, auth.actor, asset_id)
                if handle.size_bytes > MAX_IMAGE_BYTES:
                    raise AppError(413, 'MEDIA_TOO_LARGE', 'Real understanding allows at most 5 MiB per image')
                image_handles.append((asset_id, handle))
            if sum(handle.size_bytes for _, handle in image_handles) > MAX_TOTAL_IMAGE_BYTES:
                raise AppError(413, 'MEDIA_TOO_LARGE', 'Real understanding allows at most 10 MiB of images in total')
        if materializing:
            unit.commit()
    plan, speech, speech_provider = None, None, None
    if previous is None:
        planning_input, asr_provider = body, 'not_used'
        if content is not None:
            recognized = state.agent_asr.transcribe(_content_bytes(content), content.mime_type, body.mock_fixture_id)
            recognized = ASRResult.model_validate(recognized)
            planning_input = body.model_copy(update={'text': recognized.transcript})
            asr_provider = recognized.provider
            materializing = _needs_tasks(planning_input, state.agent_chat)
            with (write_unit(auth.request) if materializing else read_unit(auth.request)) as unit:
                _context_access(auth, unit.session, body)
                snapshot = _snapshot(auth, unit.session, planning_input)
                if materializing:
                    unit.commit()
        if image_handles:
            snapshot = replace(snapshot, images=tuple(ImageInput(asset_id, handle.mime_type, _image_bytes(handle))
                                                     for asset_id, handle in image_handles))
        if not _is_mock(state.agent_chat) and remaining() < 20.0:
            raise AppError(504, 'PROVIDER_TIMEOUT', 'Insufficient Agent deadline for understanding', retryable=True)
        try:
            plan = state.agent_chat.plan(planning_input, snapshot)
            plan = replace(plan, request_hash=request_digest(body), transcript=planning_input.text or '', asr_provider=asr_provider)
            TypeAdapter(AgentTurn.model_fields['scene'].annotation).validate_python(plan.scene)
            for action in plan.actions:
                TypeAdapter(Action).validate_python(TypeAdapter(Action).dump_python(action.action, mode='json', exclude_unset=True))
            if not _is_mock(state.agent_chat) and (plan.preference or any(a.action.type != 'record_diet' for a in plan.actions)):
                raise ValueError('F2 real understanding may only prepare diet actions')
        except (ValidationError, TypeError, ValueError) as exc:
            raise AppError(502, 'PROVIDER_ERROR', 'Understanding output failed schema validation') from exc
        try:
            # A real provider has a 20s total deadline. Do not start another one
            # if it cannot fit the 45s Agent budget; retain the final text instead.
            if _is_mock(state.agent_tts) or remaining() >= 20.0:
                speech = state.agent_tts.synthesize(plan.reply)
                speech_provider = _speech_provider(state.agent_tts, speech)
        except AppError as exc:
            if exc.status not in {501, 502, 504}:
                raise
            # Explicit text-only degradation, never fake playback media.
        remaining()
    with write_unit(auth.request) as unit:
        _context_access(auth, unit.session, body)
        remaining()
        if snapshot is not None:
            current = state.services.profile.read(unit.session, auth.actor, body.elder_id)
            if snapshot.profile.version != current.version:
                raise AppError(409, 'VERSION_CONFLICT', 'Profile changed during provider call')
        def operation():
            if previous is not None:
                return state.agent.replay(unit.session, auth.actor, body)
            return state.agent.record_turn(unit.session, auth.actor, body, snapshot, plan,
                                           speech=speech, tts_provider=speech_provider)
        data = _store(state, unit.session, auth.actor, auth.request, key, body.model_dump(mode='json'), 201, operation)
        remaining()
        unit.commit()
    return data


def decide(auth, action_id, body, key):
    state = auth.request.app.state
    with write_unit(auth.request) as unit:
        _reauthorize(auth, unit.session)
        check_resource(auth.request, unit.session, auth.actor, 'action', action_id, 'self')
        _ready(state)
        data = _store(state, unit.session, auth.actor, auth.request, key,
                      {'action_id': action_id, **body.model_dump(mode='json', exclude_unset=True)}, 200,
                      lambda: state.agent.decide(unit.session, auth.actor, action_id, body))
        unit.commit()
    return data


def read_memory(ctx, elder_id):
    _ready(ctx.request.app.state)
    return ctx.request.app.state.services.memory.context(ctx.tx, ctx.actor, elder_id)


def update_memory(ctx, elder_id, entry_id, body, key):
    state = ctx.request.app.state
    _ready(state)
    return _store(state, ctx.tx, ctx.actor, ctx.request, key,
                  {'elder_id': elder_id, 'entry_id': entry_id, **body.model_dump(mode='json')}, 200,
                  lambda: state.agent.memory.update_entry(ctx.tx, ctx.actor, elder_id, entry_id, body.expected_version, body.text))


def delete_memory(ctx, elder_id, entry_id, expected_version, key):
    state = ctx.request.app.state
    _ready(state)
    return _store(state, ctx.tx, ctx.actor, ctx.request, key,
                  {'elder_id': elder_id, 'entry_id': entry_id, 'expected_version': expected_version}, 200,
                  lambda: state.agent.memory.delete_entry(ctx.tx, ctx.actor, elder_id, entry_id, expected_version))
