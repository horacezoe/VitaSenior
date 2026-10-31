"""No paid calls: test the actual adapter with explicit HTTP substitutes."""
import asyncio
import base64
import json
import time
from dataclasses import replace
from datetime import datetime, timezone

import httpx
import pytest

from app.core.errors import AppError
from app.providers.planning import ImageInput, Snapshot
from app.providers.real_understanding import RealUnderstanding, MAX_IMAGE_BYTES, MAX_RESPONSE_BYTES
from app.schemas.agent import AgentTurnWrite, MemoryDocument

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a5WQAAAAASUVORK5CYII=')


def candidate(**changes):
    return {'intent': 'diet', 'meal_slot': 'lunch', 'foods': ['青菜', '豆腐'],
            'food_groups': ['vegetable', 'protein'], 'reply': '候选，请确认', **changes}


def response(value=None, *, content=None, finish='stop', message=None):
    return httpx.Response(200, json={'choices': [{'finish_reason': finish, 'message': {
        'content': content if content is not None else json.dumps(value or candidate(), ensure_ascii=False),
        **(message or {})}}]})


def provider(handler, **kwargs):
    return RealUnderstanding(api_key='explicit-http-substitute-key', base_url='https://provider.test/v1',
                             model='explicit-test-vision-model', transport=httpx.MockTransport(handler), **kwargs)


def inputs(**changes):
    now = datetime(2026, 10, 31, 4, tzinfo=timezone.utc)
    body = AgentTurnWrite(elder_id='actual-elder', client_turn_id='real-input', text='今天午餐吃了青菜和豆腐', **changes)
    snap = Snapshot(body.elder_id, now, MemoryDocument(elder_id=body.elder_id, version=1, updated_at=now,
                                                     entries=[], markdown='private-memory-not-for-vendor'))
    return body, snap


def test_text_request_uses_current_input_and_server_builds_complete_daily_action():
    captured = []
    def handler(request):
        captured.append(request)
        return response()
    body, snap = inputs()
    plan = provider(handler).plan(body, snap)
    sent = json.loads(captured[0].content)
    assert captured[0].url == 'https://provider.test/v1/chat/completions'
    assert captured[0].headers['Authorization'] == 'Bearer explicit-http-substitute-key'
    assert sent['stream'] is False and sent['response_format'] == {'type': 'json_object'}
    assert 'thinking' not in sent  # MiMo-specific fields must not leak to other providers.
    assert sent['messages'][1]['content'] == [{'type': 'text', 'text': body.text}]
    assert snap.elder_id not in captured[0].content.decode() and snap.memory.markdown not in captured[0].content.decode()
    assert len(captured) == 1 and plan.chat_provider == 'real' and plan.preference is None
    action, payload = plan.actions[0].action, plan.actions[0].payload
    assert not action.requires_confirmation and action.status == 'confirmed' and action.type == 'record_diet'
    assert action.action_id.startswith('action_') and payload['elder_id'] == snap.elder_id
    assert payload['checkin']['occurred_at'] == snap.now.isoformat().replace('+00:00', 'Z')
    assert action.preview.foods == ['青菜', '豆腐'] and '【模拟】' not in plan.reply


def test_image_request_sends_only_authorized_bytes_without_local_path_or_ticket():
    captured = []
    body, snap = inputs(image_asset_ids=['private-asset'])
    snap = replace(snap, images=(ImageInput('private-asset', 'image/png', PNG),))
    def handler(request):
        captured.append(json.loads(request.content))
        return response()
    plan = provider(handler).plan(body, snap)
    parts = captured[0]['messages'][1]['content']
    assert parts[1]['image_url']['url'] == 'data:image/png;base64,'+base64.b64encode(PNG).decode()
    assert 'private-asset' not in json.dumps(captured[0])
    assert plan.actions[0].action.preview.image_asset_ids == ['private-asset']


@pytest.mark.parametrize('with_image', [False, True])
def test_mimo_non_thinking_text_and_image_complete_daily_actions(with_image):
    captured = []
    def handler(request):
        sent = json.loads(request.content)
        captured.append(sent)
        assert sent['model'] == 'mimo-v2.6-flash'
        assert sent['thinking'] == {'type': 'disabled'}
        assert sent['response_format'] == {'type': 'json_object'}
        return response()
    body, snap = inputs(image_asset_ids=['meal-image'] if with_image else [])
    if with_image:
        snap = replace(snap, images=(ImageInput('meal-image', 'image/png', PNG),))
    chat = RealUnderstanding(api_key='explicit-http-substitute-key',
        base_url='https://api.xiaomimimo.com/v1', model='mimo-v2.6-flash',
        transport=httpx.MockTransport(handler))
    plan = chat.plan(body, snap)
    parts = captured[0]['messages'][1]['content']
    assert [part['type'] for part in parts] == (['text', 'image_url'] if with_image else ['text'])
    assert len(captured) == 1 and plan.chat_provider == 'real'
    assert plan.actions[0].action.status == 'confirmed' and not plan.actions[0].action.requires_confirmation
    assert plan.actions[0].payload['checkin']['payload']['foods'] == ['青菜', '豆腐']


@pytest.mark.parametrize('status,retryable', [(401, False), (403, False), (429, True), (500, True), (503, True)])
def test_upstream_http_failures_are_sanitized_and_not_retried(status, retryable):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(status, text='SECRET invalid API key or private upstream content')
    with pytest.raises(AppError) as exc:
        provider(handler).plan(*inputs())
    assert exc.value.status == 502 and exc.value.code == 'PROVIDER_ERROR'
    assert exc.value.retryable == retryable and exc.value.details == {'upstream_status': status}
    assert 'SECRET' not in exc.value.message and len(calls) == 1


def test_total_deadline_cancels_continuously_streaming_response():
    class Slow(httpx.AsyncByteStream):
        async def __aiter__(self):
            for _ in range(100):
                await asyncio.sleep(.01)
                yield b' '
    async def handler(request):
        return httpx.Response(200, stream=Slow())
    start = time.monotonic()
    with pytest.raises(AppError) as exc:
        provider(handler, timeout_seconds=.04).plan(*inputs())
    assert exc.value.status == 504 and exc.value.code == 'PROVIDER_TIMEOUT'
    assert time.monotonic()-start < 1.0


@pytest.mark.parametrize('error', [httpx.ReadTimeout('substitute timeout'), httpx.ConnectError('substitute connection failure')])
def test_transport_errors_use_existing_error_contract(error):
    def handler(request):
        raise error
    with pytest.raises(AppError) as exc:
        provider(handler).plan(*inputs())
    assert exc.value.status == (504 if isinstance(error, httpx.TimeoutException) else 502)


@pytest.mark.parametrize('result', [
    response(content='not-json'), response(content='```json\n{}\n```'),
    response(candidate(elder_id='other')), response(candidate(action_id='model-action')),
    response(candidate(foods=[' '])), response(candidate(foods=['x'*81])),
    response(candidate(intent='record_medication')),
    response(finish='length'), response(message={'tool_calls': [{'function': {'name': 'write_sql'}}]}),
    response(content='{"intent":"diet","intent":"unsupported"}'),
    httpx.Response(200, json={'choices': []}),
])
def test_invalid_model_json_and_execution_fields_never_become_a_plan(result):
    with pytest.raises(AppError) as exc:
        provider(lambda request: result).plan(*inputs())
    assert exc.value.status == 502 and exc.value.code == 'PROVIDER_ERROR'


def test_oversized_response_is_bounded_before_parsing():
    with pytest.raises(AppError) as exc:
        provider(lambda request: httpx.Response(200, content=b'x'*(MAX_RESPONSE_BYTES+1))).plan(*inputs())
    assert exc.value.status == 502 and 'size limit' in exc.value.message


@pytest.mark.parametrize('intent', ['clarify', 'unsupported'])
def test_unclear_or_unsupported_model_intent_has_no_actions(intent):
    plan = provider(lambda request: response(candidate(intent=intent, foods=[], food_groups=[]))).plan(*inputs())
    assert plan.actions == () and plan.preference is None and plan.chat_provider == 'real'


def test_missing_meal_is_inferred_from_local_time():
    body, snap = inputs()
    plan = provider(lambda request: response()).plan(body.model_copy(update={'text': '我吃了青菜'}), snap)
    assert plan.actions[0].action.preview.meal_slot == 'lunch'
    assert plan.actions[0].action.status == 'confirmed' and '吗' not in plan.reply


def test_explicit_meal_overrides_a_contradictory_model_slot():
    plan = provider(lambda request: response(candidate(meal_slot='dinner'))).plan(*inputs())
    assert plan.actions[0].action.preview.meal_slot == 'lunch'


@pytest.mark.parametrize('text', ['我吃药了', '修改档案', '运动20分钟', '昨天午餐吃了豆腐'])
def test_non_diet_or_historical_intent_does_not_call_model_or_prepare_medication(text):
    body, snap = inputs()
    def unexpected(request):
        raise AssertionError('Unsupported request must not call a model or a mock')
    plan = provider(unexpected).plan(body.model_copy(update={'text': text}), snap)
    assert not plan.actions and plan.preference is None and plan.chat_provider == 'not_used'


def test_real_confirmation_uses_only_validated_pending_context_without_model_call():
    body, snap = inputs()
    body = body.model_copy(update={'text': '确认', 'conversation_id': 'owned-conversation'})
    snap = replace(snap, pending_action_ids=('owned-pending',))
    plan = provider(lambda request: pytest.fail('Confirmation must not infer or re-execute a model intent')).plan(body, snap)
    assert plan.decision_action_id == 'owned-pending' and plan.actions == () and plan.chat_provider == 'not_used'


@pytest.mark.parametrize('case', ['foreign-elder', 'missing-image', 'bad-image', 'large-image', 'mock-fixture'])
def test_invalid_resource_snapshot_or_encoding_never_reaches_provider(case):
    body, snap = inputs()
    if case == 'foreign-elder':
        snap = replace(snap, elder_id='another-elder')
    elif case in {'missing-image', 'bad-image', 'large-image'}:
        body = body.model_copy(update={'image_asset_ids': ['asset']})
        if case != 'missing-image':
            image = b'invalid image' if case == 'bad-image' else b'x'*(MAX_IMAGE_BYTES+1)
            snap = replace(snap, images=(ImageInput('asset', 'image/png', image),))
    else:
        body = body.model_copy(update={'mock_fixture_id': 'meal_lunch'})
    def unexpected(request):
        raise AssertionError('Unvalidated input was sent to provider')
    with pytest.raises(AppError):
        provider(unexpected).plan(body, snap)


@pytest.mark.parametrize('changes', [{'api_key': ''}, {'model': ''}, {'base_url': 'http://provider.test/v1'},
                                   {'base_url': 'https://secret@provider.test/v1'}, {'timeout_seconds': 21}])
def test_missing_or_invalid_real_configuration_fails_explicitly(changes):
    options = {'api_key': 'substitute-key', 'base_url': 'https://provider.test/v1', 'model': 'test-model'}
    options.update(changes)
    with pytest.raises(ValueError):
        RealUnderstanding(**options)
