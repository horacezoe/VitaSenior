"""Real understanding adapter + HTTP substitutes + real A/B/C business ports.

The only injection is the provider adapter with MockTransport. It is explicit
test assembly while A owns F2 factory/config, not a production fallback.
"""
import json
from dataclasses import dataclass

import httpx
import pytest
from sqlalchemy import select, func

from app.contracts.context import Actor
from app.core.errors import AppError
from app.core.uow import UnitOfWork
from app.models.agent import AgentTurn, AgentAction, MemoryDocument
from app.models.health import Checkin
from app.models.identity import IdempotencyRecord, MediaAsset
from app.providers.mock_audio import FIXTURES, Speech
from app.providers.real_understanding import RealUnderstanding
from app.schemas.enums import Role
from app.schemas.identity import ProfilePatch
from test_http import api, hdr
from test_real_understanding import candidate, response, PNG


@dataclass
class Captured:
    calls: list
    handler: object = None


@pytest.fixture
def real_api(api):
    captured = Captured([])
    def transport(request):
        captured.calls.append(request)
        return captured.handler(request) if captured.handler else response()
    api[0].state.agent_chat = RealUnderstanding(api_key='substitute-only-key',
        base_url='https://provider.test/v1', model='test-vision-model', transport=httpx.MockTransport(transport))
    yield api, captured


def turn(api, key='diet-turn', **changes):
    body = {'elder_id': api[3]['elder']['elder_id'], 'client_turn_id': key,
            'text': '今天午餐吃了青菜和豆腐', **changes}
    return api[1].post('/api/v1/agent/turns', json=body, headers=hdr(api, key))


def count(api, model):
    with api[0].state.sessions() as tx:
        return tx.scalar(select(func.count()).select_from(model))


def upload(api, owner='elder', raw=PNG):
    result = api[1].post('/api/v1/media', headers=hdr(api, 'upload-'+owner, owner),
        data={'purpose': 'meal', 'elder_id': api[3][owner]['elder_id']},
        files={'file': ('meal.png', raw, 'image/png')})
    assert result.status_code == 201, result.text
    return result.json()['data']['asset_id']


@pytest.mark.parametrize('with_image', [False, True])
def test_new_diet_turn_pending_confirm_replay_and_real_child_dashboard(real_api, with_image):
    api, captured = real_api
    app, client, _, seed, _ = api
    images = [upload(api)] if with_image else []
    prepared = turn(api, image_asset_ids=images)
    assert prepared.status_code == 201, prepared.text
    value = prepared.json()['data']
    assert value['providers'] == {'chat': 'real', 'asr': 'not_used', 'tts': 'not_used'}
    assert value['degraded'] == ['tts_unavailable'] and '【模拟】' not in value['reply']['text']
    assert value['actions'][0]['type'] == 'record_diet' and value['actions'][0]['status'] == 'pending'
    assert count(api, Checkin) == 0 and count(api, MemoryDocument) == 0
    replay = turn(api, image_asset_ids=images)
    assert replay.status_code == 201 and replay.json()['data'] == value and len(captured.calls) == 1
    action = value['actions'][0]['action_id']
    decision = f'/api/v1/agent/actions/{action}/decision'
    confirmed = client.post(decision, json={'decision': 'confirm'}, headers=hdr(api, 'confirm-diet'))
    assert confirmed.status_code == 200, confirmed.text
    record = confirmed.json()['data']['result']
    assert record['source'] == 'agent_confirmed' and record['payload']['image_asset_ids'] == images
    again = client.post(decision, json={'decision': 'confirm'}, headers=hdr(api, 'confirm-diet-again'))
    assert again.json()['data'] == confirmed.json()['data'] and count(api, Checkin) == 1
    elder = seed['elder']['elder_id']
    dashboard = client.get(f'/api/v1/elders/{elder}/dashboard', headers=hdr(api, account='bound_child'))
    report = client.get(f"/api/v1/elders/{elder}/reports/daily?date={record['local_date']}", headers=hdr(api, account='bound_child'))
    assert dashboard.status_code == report.status_code == 200
    assert dashboard.json()['data']['today_records']['diet'][0]['checkin_id'] == record['checkin_id']
    assert report.json()['data']['records']['diet'][0]['checkin_id'] == record['checkin_id']
    sent = json.loads(captured.calls[0].content)
    assert seed['elder']['user_id'] not in json.dumps(sent) and seed['elder']['elder_id'] not in json.dumps(sent)
    assert api[4]['elder']['Authorization'] not in json.dumps(sent)


def test_client_turn_id_conflict_does_not_call_model_or_write_business(real_api):
    api, captured = real_api
    assert turn(api).status_code == 201
    result = turn(api, text='今天午餐改成鱼')
    assert result.status_code == 409 and result.json()['error']['code'] == 'IDEMPOTENCY_CONFLICT'
    assert len(captured.calls) == 1 and count(api, Checkin) == 0 and count(api, AgentAction) == 1


@pytest.mark.parametrize('failure', ['timeout', 'auth', 'invalid', 'tool'])
def test_model_failure_rolls_back_turn_actions_and_success_cache(real_api, failure):
    api, captured = real_api
    def handler(request):
        if failure == 'timeout':
            raise httpx.ReadTimeout('Explicit provider substitute timeout')
        if failure == 'auth':
            return httpx.Response(401, text='private-upstream-message')
        if failure == 'tool':
            return response(message={'tool_calls': [{'function': {'name': 'write_checkin'}}]})
        return response(candidate(elder_id='foreign-elder'))
    captured.handler = handler
    result = turn(api)
    assert result.status_code == (504 if failure == 'timeout' else 502), result.text
    assert 'private-upstream-message' not in result.text
    for model in [AgentTurn, AgentAction, Checkin, IdempotencyRecord]:
        assert count(api, model) == 0
    captured.handler = None
    retry = turn(api)
    assert retry.status_code == 201 and len(captured.calls) == 2 and count(api, Checkin) == 0


def test_foreign_image_is_denied_before_any_provider_request(real_api):
    api, captured = real_api
    asset = upload(api, 'stranger_elder')
    result = turn(api, image_asset_ids=[asset])
    assert result.status_code in {403, 404}, result.text
    assert captured.calls == [] and count(api, AgentTurn) == count(api, Checkin) == 0


@pytest.mark.parametrize('change', ['independent-writer', 'profile', 'memory', 'session', 'media'])
def test_model_phase_has_no_lock_and_final_uow_rechecks_real_resources(real_api, change):
    api, captured = real_api
    app, _, clock, seed, _ = api
    image = upload(api) if change == 'media' else None
    def handler(request):
        if change == 'session':
            clock.advance(seconds=49*3600)
        else:
            with UnitOfWork(app.state.sessions) as unit:
                if change == 'profile':
                    app.state.services.profile.update(unit.session, Actor(seed['elder']['user_id'], Role.elder),
                        seed['elder']['elder_id'], 1, ProfilePatch(medical_notes='并发本人修订'))
                elif change == 'media':
                    unit.session.delete(unit.session.get(MediaAsset, image))
                else:
                    target = seed['stranger_elder']['elder_id'] if change == 'independent-writer' else seed['elder']['elder_id']
                    unit.session.add(MemoryDocument(elder_id=target, version=2, entries_json=[],
                                                   revisions_json=[], updated_at=clock.now()))
                unit.commit()
        return response()
    captured.handler = handler
    result = turn(api, image_asset_ids=[image] if image else [])
    expected = {'independent-writer': 201, 'profile': 409, 'memory': 409, 'session': 401, 'media': 404}[change]
    assert result.status_code == expected, result.text
    assert count(api, Checkin) == 0
    assert count(api, AgentAction) == (1 if change == 'independent-writer' else 0)
    assert count(api, AgentTurn) == (1 if change == 'independent-writer' else 0)


def test_real_mode_non_diet_guidance_does_not_materialize_medication_or_call_mock(real_api):
    api, captured = real_api
    from app.models.health import DailyTask
    result = turn(api, text='我吃药了')
    assert result.status_code == 201, result.text
    value = result.json()['data']
    assert not value['actions'] and value['providers']['chat'] == 'not_used'
    assert captured.calls == [] and count(api, Checkin) == count(api, DailyTask) == 0


def test_plain_next_turn_confirmation_reuses_saved_action_without_model_call(real_api):
    api, captured = real_api
    pending = turn(api).json()['data']['actions'][0]['action_id']
    confirmed = turn(api, key='next-confirm', text='确认', context={'pending_action_id': pending})
    assert confirmed.status_code == 201, confirmed.text
    value = confirmed.json()['data']
    assert value['actions'][0]['status'] == 'confirmed' and value['providers']['chat'] == 'not_used'
    assert '【模拟】' not in value['reply']['text'] and count(api, Checkin) == 1 and len(captured.calls) == 1


def test_speech_result_and_agent_provenance_use_actual_instance(real_api):
    api, _ = real_api
    app, client, _, seed, _ = api
    class RealSpeechSubstitute:
        name = 'real'
        is_mock = False
        def synthesize(self, text, voice_id=None):
            return Speech((FIXTURES/'greeting.wav').read_bytes(), 'audio/wav', 600, text, is_mock=False)
    app.state.agent_tts = RealSpeechSubstitute()
    tts = client.post('/api/v1/ai/tts', headers=hdr(api), json={'elder_id': seed['elder']['elder_id'], 'text': '您好'})
    assert tts.status_code == 200, tts.text
    assert tts.json()['data']['provider'] == 'real' and tts.json()['data']['is_mock'] is False
    value = turn(api).json()['data']
    assert value['providers']['tts'] == 'real' and value['reply']['audio_asset_id']


def test_failed_tts_keeps_real_text_pending_action_and_explicit_degradation(real_api):
    api, _ = real_api
    class Failed:
        name = 'real'
        is_mock = False
        def synthesize(self, text, voice_id=None):
            raise AppError(504, 'PROVIDER_TIMEOUT', 'Explicit TTS substitute timeout')
    api[0].state.agent_tts = Failed()
    result = turn(api)
    assert result.status_code == 201, result.text
    value = result.json()['data']
    assert value['providers']['chat'] == 'real' and value['providers']['tts'] == 'not_used'
    assert value['degraded'] == ['tts_unavailable'] and value['actions'][0]['status'] == 'pending'
    assert count(api, Checkin) == 0 and count(api, MediaAsset) == 0


@pytest.mark.parametrize('elapsed', [30.0, 46.0])
def test_agent_budget_skips_unaffordable_tts_or_rolls_back_late_plan(real_api, monkeypatch, elapsed):
    from types import SimpleNamespace
    from app.application import agent_flows
    api, captured = real_api
    monotonic = [100.0]
    monkeypatch.setattr(agent_flows, 'time', SimpleNamespace(monotonic=lambda: monotonic[0]))
    def handler(request):
        monotonic[0] += elapsed
        return response()
    class ShouldNotRun:
        name = 'real'
        is_mock = False
        def synthesize(self, text, voice_id=None):
            raise AssertionError('No 20-second budget remains for real TTS')
    captured.handler = handler
    api[0].state.agent_tts = ShouldNotRun()
    result = turn(api)
    assert result.status_code == (201 if elapsed == 30 else 504), result.text
    assert count(api, AgentAction) == (1 if elapsed == 30 else 0) and count(api, Checkin) == 0
    if elapsed == 30:
        assert result.json()['data']['degraded'] == ['tts_unavailable']


def test_ai02_rejects_wrong_speech_provenance_before_registering_media(real_api):
    api, _ = real_api
    class IncorrectSpeech:
        name = 'real'
        def synthesize(self, text, voice_id=None):
            return Speech((FIXTURES/'greeting.wav').read_bytes(), 'audio/wav', 600, text, is_mock=True)
    api[0].state.agent_tts = IncorrectSpeech()
    result = api[1].post('/api/v1/ai/tts', headers=hdr(api),
        json={'elder_id': api[3]['elder']['elder_id'], 'text': '您好'})
    assert result.status_code == 502 and count(api, MediaAsset) == 0
