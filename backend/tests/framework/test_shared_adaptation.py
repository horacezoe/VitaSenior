"""A0 shared-adaptation evidence: capabilities, clock injection, AI tx boundary."""
import pytest
from datetime import datetime, timezone
from app.composition import capabilities, compose, declared_capabilities, providers
from app.core.clock import FakeClock, SystemClock
from app.core.config import Settings
from app.core.errors import AppError
from app.core.uow import UnitOfWork
from app.contracts.context import Actor
from app.schemas.enums import Role
from app.seed import import_demo_history
from app.services import agent_capabilities, health_capabilities, identity_capabilities

def test_capability_declarations_are_per_domain_and_aggregated(env):
    app, client, clock, seed = env
    for module in (identity_capabilities, health_capabilities, agent_capabilities):
        assert isinstance(module.CAPABILITIES, frozenset)
    assert declared_capabilities() == identity_capabilities.CAPABILITIES | health_capabilities.CAPABILITIES | agent_capabilities.CAPABILITIES
    assert providers() == agent_capabilities.PROVIDERS
    mounted = {(op['operationId']) for item in app.openapi()['paths'].values() for m, op in item.items() if m in {'get', 'post', 'put', 'delete'}}
    assert declared_capabilities() <= mounted
    assert set(capabilities(mounted)) == mounted
    assert capabilities(mounted)['SYS01'] is True
    # CHANGE04 is the long-lived "still gated" probe: applying needs C's MemoryPort.
    assert capabilities(mounted)['CHANGE04'] is False

def test_services_receive_the_application_clock_and_settings(tmp_path):
    clock = FakeClock(datetime(2026, 10, 30, 4, 0, tzinfo=timezone.utc))
    settings = Settings(data_dir=tmp_path, scanner_enabled=False)
    bundle = compose(clock, settings)
    assert bundle.profile.clock is clock
    assert bundle.binding.clock is clock
    assert bundle.changes.clock is clock
    assert bundle.media.clock is clock
    assert bundle.media.settings is settings
    # Building without arguments still works for isolated unit tests.
    assert compose().profile.clock is not None

def test_ai_routes_authenticate_without_a_write_transaction(env, tokens, monkeypatch):
    """ASR/LLM/TTS must not run inside BEGIN IMMEDIATE: only the short read UoW."""
    app, client, clock, seed = env
    opened = []
    original = UnitOfWork.__enter__
    def spy(self):
        opened.append(self.write)
        return original(self)
    monkeypatch.setattr(UnitOfWork, '__enter__', spy)
    response = client.post('/api/v1/ai/tts', headers=tokens['elder'], json={'elder_id': seed['elder']['elder_id'], 'text': '你好'})
    assert response.status_code == 501, response.text
    assert opened and not any(opened), opened

def test_ai_routes_still_enforce_identity_and_elder_scope(env, tokens):
    app, client, clock, seed = env
    elder = seed['elder']['elder_id']
    assert client.post('/api/v1/ai/tts', json={'elder_id': elder, 'text': '你好'}).status_code == 401
    denied = client.post('/api/v1/ai/tts', headers=tokens['unbound_child'], json={'elder_id': elder, 'text': '你好'})
    assert denied.status_code == 403 and denied.json()['error']['code'] == 'ELDER_ACCESS_DENIED'

def test_history_import_entry_validates_scenario_and_delegates():
    calls = []
    class FakeHistory:
        def import_demo_history(self, tx, actor, elder_id, *, demo_id, days):
            calls.append((elder_id, demo_id, days))
    services = compose()
    from dataclasses import replace
    services = replace(services, history=FakeHistory())
    actor = Actor('user_demo', Role.elder)
    import_demo_history(None, services, actor, 'elder_demo', demo_id='demo_1')
    assert calls == [('elder_demo', 'demo_1', 14)]
    with pytest.raises(ValueError):
        import_demo_history(None, services, actor, 'elder_demo', demo_id='demo_1', scenario='unknown')

def test_unimplemented_demo_history_is_not_swallowed():
    services = compose()
    with pytest.raises(AppError) as exc:
        import_demo_history(None, services, Actor('user_demo', Role.elder), 'elder_demo', demo_id='demo_1')
    assert exc.value.status == 501
