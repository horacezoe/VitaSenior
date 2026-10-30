"""Frozen F0 baseline assertions - explicit stage markers, not a live contract.

These describe the repository exactly as tagged `f1-reviewed-v1`: every business
route answered 501, only the five F0 operations were real, and every business port
stub raised 501. They run only when asked for:

    pytest -m f0_stage

Once a business capability is registered the stage is closed and these are skipped
rather than failing: the live contract is enforced by test_all_routes.py plus the
per-domain suites.
"""
import pytest
from routes_cases import CASES, F0_CAPABILITIES, call
from app.composition import compose

pytestmark = pytest.mark.f0_stage

def require_f0_stage(app):
    if app.state.capabilities_declared != F0_CAPABILITIES:
        pytest.skip("F0 stage is closed: business capabilities have been registered")

@pytest.mark.parametrize('operation,method,path,body,account', CASES, ids=[c[0] for c in CASES])
def test_every_business_route_is_still_a_501_placeholder(operation, method, path, body, account, env, tokens, resources):
    app, client, clock, seed = env
    require_f0_stage(app)
    response = call(client, tokens, resources, operation, method, path, body, account)
    assert response.status_code == 501, (operation, response.text)
    assert response.json()['error']['code'] == 'MODULE_NOT_IMPLEMENTED'
    assert 'data' not in response.json()

def test_only_the_five_f0_capabilities_are_true(env, tokens):
    app, client, clock, seed = env
    require_f0_stage(app)
    data = client.get('/api/v1/runtime', headers=tokens['elder']).json()['data']
    assert {k for k, v in data['capabilities'].items() if v} == set(F0_CAPABILITIES)
    assert all(v is False for k, v in data['capabilities'].items() if k not in F0_CAPABILITIES)
    assert data['providers'] == {k: 'not_implemented' for k in ['chat', 'asr', 'tts']}

def test_business_port_stubs_are_honest(env):
    app, client, clock, seed = env
    require_f0_stage(app)
    from app.core.errors import AppError
    bundle = compose()
    with pytest.raises(AppError) as exc:
        bundle.binding.issue_code(None, None, 'elder')
    assert exc.value.status == 501
    with pytest.raises(AppError) as exc:
        bundle.history.import_demo_history(None, None, 'elder', demo_id='demo', days=14)
    assert exc.value.status == 501
