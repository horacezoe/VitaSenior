"""Actual A factory and environment settings; HTTP substitutes, never paid calls."""
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.providers.mock_chat import MockUnderstanding
from app.providers.real_understanding import RealUnderstanding
from app.seed import framework_seed


@pytest.fixture
def configured(monkeypatch, tmp_path):
    for key, value in {'CHAT_PROVIDER': 'real', 'CHAT_API_KEY': 'explicit-startup-substitute-key',
                       'CHAT_BASE_URL': 'https://provider.test/v1', 'CHAT_MODEL': 'startup-test-model',
                       'ASR_PROVIDER': 'mock', 'TTS_PROVIDER': 'mock', 'SCANNER_ENABLED': 'false',
                       'DATA_DIR': str(tmp_path/'configured')}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv('DATABASE_URL', raising=False)
    return monkeypatch


def login(client, account):
    body = {key: account[key] for key in ['phone', 'role']}
    challenge = client.post('/api/v1/auth/code', json=body).json()['data']['challenge_id']
    result = client.post('/api/v1/auth/login', json={**body, 'challenge_id': challenge, 'code': '123456'})
    assert result.status_code == 200, result.text
    return {'Authorization': 'Bearer '+result.json()['data']['access_token']}


def test_env_builds_real_adapter_and_runtime_matches_actual_instance(configured):
    app = create_app()  # No Settings/provider/bundle injection.
    assert isinstance(app.state.agent_chat, RealUnderstanding)
    assert app.state.agent_chat.name == 'real' and not app.state.agent_chat.is_mock
    assert app.state.agent_chat.model == 'startup-test-model'
    with TestClient(app) as client:
        seed = framework_seed(app.state.sessions, app.state.clock)
        headers = login(client, seed['elder'])
        runtime = client.get('/api/v1/runtime', headers=headers)
        assert runtime.status_code == 200
        assert runtime.json()['data']['providers'] == {'chat': 'real', 'asr': 'mock', 'tts': 'mock'}
        # Substitute only the HTTP transport after the actual factory constructed
        # the instance; never replace the provider or normal application assembly.
        def response(request):
            return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps({
                'intent': 'diet', 'meal_slot': 'lunch', 'foods': ['青菜'], 'food_groups': ['vegetable'], 'reply': '请确认'})}}]})
        app.state.agent_chat._transport = httpx.MockTransport(response)
        result = client.post('/api/v1/agent/turns', headers={**headers, 'Idempotency-Key': 'configured-turn'},
            json={'elder_id': seed['elder']['elder_id'], 'client_turn_id': 'configured-turn', 'text': '今天午餐吃了青菜'})
        assert result.status_code == 201, result.text
        assert result.json()['data']['providers']['chat'] == 'real'
        assert result.json()['data']['actions'][0]['status'] == 'confirmed'
        assert not result.json()['data']['actions'][0]['requires_confirmation']


@pytest.mark.parametrize('missing', ['CHAT_API_KEY', 'CHAT_BASE_URL', 'CHAT_MODEL'])
def test_explicit_real_mode_missing_parameter_refuses_normal_startup(configured, missing):
    configured.setenv(missing, '')
    with pytest.raises(ValueError, match='CHAT_PROVIDER=real requires'):
        create_app()


def test_explicit_mock_restart_without_key_preserves_existing_sessions(configured):
    first = create_app()
    with TestClient(first) as client:
        seed = framework_seed(first.state.sessions, first.state.clock)
        headers = login(client, seed['elder'])
    configured.setenv('CHAT_PROVIDER', 'mock')
    for name in ['CHAT_API_KEY', 'CHAT_BASE_URL', 'CHAT_MODEL']:
        configured.delenv(name, raising=False)
    restarted = create_app()  # Same DATA_DIR, explicit fallback, no real credentials.
    assert isinstance(restarted.state.agent_chat, MockUnderstanding)
    with TestClient(restarted) as client:
        runtime = client.get('/api/v1/runtime', headers=headers)
        assert runtime.status_code == 200, runtime.text
        assert runtime.json()['data']['providers'] == {'chat': 'mock', 'asr': 'mock', 'tts': 'mock'}
        assert client.get(f"/api/v1/elders/{seed['elder']['elder_id']}/profile", headers=headers).status_code == 200
