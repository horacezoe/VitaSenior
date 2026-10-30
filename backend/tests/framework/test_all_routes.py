"""Long-term route/capability contract.

For every P0 operation with an authorized, schema-valid request:
  * declared implemented -> it must NOT answer 501 (per-domain tests assert bodies);
  * not declared         -> it must answer exactly 501 MODULE_NOT_IMPLEMENTED.
This is not "anything may 200 or 501": the declaration file and the runtime
behaviour must agree in both directions.
"""
import pytest
from routes_cases import CASES, call

@pytest.mark.parametrize('operation,method,path,body,account', CASES, ids=[c[0] for c in CASES])
def test_every_p0_route_matches_its_capability(operation, method, path, body, account, env, tokens, resources):
    app, client, clock, seed = env
    response = call(client, tokens, resources, operation, method, path, body, account)
    declared = app.state.capabilities_declared
    if operation in declared:
        assert response.status_code != 501, (operation, response.text)
        assert response.status_code < 500, (operation, response.text)
    else:
        assert response.status_code == 501, (operation, response.text)
        assert response.json()['error']['code'] == 'MODULE_NOT_IMPLEMENTED'
        assert 'data' not in response.json()

def test_runtime_capabilities_agree_with_every_declaration(env, tokens):
    app, client, clock, seed = env
    runtime = client.get('/api/v1/runtime', headers=tokens['elder']).json()['data']
    capabilities = runtime['capabilities']
    mounted = {op['operationId'] for item in client.get('/openapi.json').json()['paths'].values()
               for method, op in item.items() if method in {'get', 'post', 'put', 'delete'}}
    # Every declared capability must be a real mounted operation: no optimistic entry.
    assert set(app.state.capabilities_declared) <= mounted
    assert {op for op, ok in capabilities.items() if ok} == set(app.state.capabilities_declared)
    assert capabilities['web_push'] is False

@pytest.mark.parametrize('kind,path,method,body', [
    ('checkin', '/checkins/checkin', 'put', {'expected_version': 1, 'payload': {'activity': 'walk', 'duration_minutes': 30}}),
    ('plan', '/medication-plans/plan', 'put', {'expected_version': 1, 'patch': {'notes': 'x'}}),
    ('proposal', '/change-proposals/proposal', 'get', None),
    ('notification', '/notifications/notice/events', 'post', {'event_id': 'evt', 'event_type': 'displayed'}),
    ('action', '/agent/actions/action/decision', 'post', {'decision': 'confirm'}),
    ('media', '/media/asset', 'get', None),
])
def test_resource_guards(kind, path, method, body, env, tokens, resources):
    app, client, clock, seed = env
    kwargs = {'headers': tokens['unbound_child']}
    if body is not None:
        kwargs['json'] = body
    r = client.request(method, '/api/v1' + path, **kwargs)
    assert r.status_code == 404, r.text
