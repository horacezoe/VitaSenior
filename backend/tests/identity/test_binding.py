"""BIND01-04: leading zeros, 5-minute validity, re-issue, one-time consumption."""
from types import SimpleNamespace
from sqlalchemy import select
from app.models.identity import BindingCode as BindingCodeRow
from conftest import auth_header, hdr
import app.services.binding_service as binding_module

def force_code(monkeypatch, code: int):
    """Prove leading zeros survive the whole flow with a deterministic code."""
    monkeypatch.setattr(binding_module, 'secrets', SimpleNamespace(randbelow=lambda n: code))

def test_leading_zero_code_round_trip(demo, monkeypatch):
    force_code(monkeypatch, 12)
    issued = demo.client.post(f'/api/v1/elders/{demo.elder_id}/binding-codes', headers=hdr(demo.elder, 'code-1'))
    assert issued.status_code == 201, issued.text
    data = issued.json()['data']
    assert data['code'] == '0012' and len(data['code']) == 4
    assert '0012' in data['display_text']
    preview = demo.client.post('/api/v1/family-bindings/preview', headers=demo.child, json={'code': '0012'})
    assert preview.status_code == 200, preview.text
    assert preview.json()['data']['already_bound'] is False
    assert preview.json()['data']['elder_display_name'] == '演示老人'
    consumed = demo.client.post('/api/v1/family-bindings', headers=hdr(demo.child, 'bind-1'),
                               json={'code': '0012', 'relationship': '女儿'})
    assert consumed.status_code == 201, consumed.text
    assert consumed.json()['data']['elder_id'] == demo.elder_id
    assert consumed.json()['data']['status'] == 'active'
    # Preview never consumes; the second consume of the same code is refused.
    second = demo.client.post('/api/v1/family-bindings/preview', headers=demo.child, json={'code': '0012'})
    assert second.status_code == 409 and second.json()['error']['code'] == 'BIND_CODE_CONSUMED'
    again = demo.client.post('/api/v1/family-bindings', headers=hdr(demo.child, 'bind-other'),
                             json={'code': '0012', 'relationship': '女儿'})
    assert again.status_code == 409

def test_reissue_revokes_the_previous_code(demo, monkeypatch):
    force_code(monkeypatch, 12)
    assert demo.client.post(f'/api/v1/elders/{demo.elder_id}/binding-codes', headers=hdr(demo.elder, 'code-a')).status_code == 201
    force_code(monkeypatch, 34)
    assert demo.client.post(f'/api/v1/elders/{demo.elder_id}/binding-codes', headers=hdr(demo.elder, 'code-b')).status_code == 201
    old = demo.client.post('/api/v1/family-bindings/preview', headers=demo.child, json={'code': '0012'})
    assert old.status_code == 409 and old.json()['error']['code'] == 'BIND_CODE_INVALID'
    new = demo.client.post('/api/v1/family-bindings/preview', headers=demo.child, json={'code': '0034'})
    assert new.status_code == 200

def test_code_expires_after_five_minutes(demo, monkeypatch, env):
    app, client, clock, seed = env
    force_code(monkeypatch, 7)
    issued = demo.client.post(f'/api/v1/elders/{demo.elder_id}/binding-codes', headers=hdr(demo.elder, 'code-ttl'))
    assert issued.json()['data']['code'] == '0007'
    clock.advance(seconds=301)
    preview = demo.client.post('/api/v1/family-bindings/preview', headers=demo.child, json={'code': '0007'})
    assert preview.status_code == 409 and preview.json()['error']['code'] == 'BIND_CODE_EXPIRED'
    consume = demo.client.post('/api/v1/family-bindings', headers=hdr(demo.child, 'ttl-bind'),
                               json={'code': '0007', 'relationship': '子女'})
    assert consume.status_code == 409 and consume.json()['error']['code'] == 'BIND_CODE_EXPIRED'

def test_unknown_code_and_role_guards(demo):
    unknown = demo.client.post('/api/v1/family-bindings/preview', headers=demo.child, json={'code': '9999'})
    assert unknown.status_code == 409 and unknown.json()['error']['code'] == 'BIND_CODE_INVALID'
    elder_cannot_preview = demo.client.post('/api/v1/family-bindings/preview', headers=demo.elder, json={'code': '9999'})
    assert elder_cannot_preview.status_code == 403
    child_cannot_issue = demo.client.post(f'/api/v1/elders/{demo.elder_id}/binding-codes', headers=hdr(demo.child, 'child-issue'))
    assert child_cannot_issue.status_code == 403

def test_already_bound_child_is_treated_as_consumed(demo, monkeypatch):
    force_code(monkeypatch, 21)
    demo.client.post(f'/api/v1/elders/{demo.elder_id}/binding-codes', headers=hdr(demo.elder, 'c1'))
    first = demo.client.post('/api/v1/family-bindings', headers=hdr(demo.child, 'b1'), json={'code': '0021', 'relationship': '儿子'})
    assert first.status_code == 201
    force_code(monkeypatch, 22)
    demo.client.post(f'/api/v1/elders/{demo.elder_id}/binding-codes', headers=hdr(demo.elder, 'c2'))
    second = demo.client.post('/api/v1/family-bindings', headers=hdr(demo.child, 'b2'), json={'code': '0022', 'relationship': '儿子'})
    assert second.status_code == 409 and second.json()['error']['code'] == 'BIND_CODE_CONSUMED'
    preview = demo.client.post('/api/v1/family-bindings/preview', headers=demo.child, json={'code': '0022'})
    assert preview.json()['data']['already_bound'] is True

def test_bound_child_sees_the_elder_and_binding(demo, monkeypatch, env):
    app, client, clock, seed = env
    assert demo.client.get('/api/v1/me/elders', headers=demo.child).json()['data']['items'] == []
    force_code(monkeypatch, 33)
    demo.client.post(f'/api/v1/elders/{demo.elder_id}/binding-codes', headers=hdr(demo.elder, 'c-33'))
    demo.client.post('/api/v1/family-bindings', headers=hdr(demo.child, 'b-33'), json={'code': '0033', 'relationship': '孙女'})
    items = demo.client.get('/api/v1/me/elders', headers=demo.child).json()['data']['items']
    assert len(items) == 1
    summary = items[0]
    assert summary['elder_id'] == demo.elder_id
    assert summary['relationship'] == '孙女' and summary['binding_id']
    assert summary['display_name'] == '演示老人'
    # A child cannot list elders as an elder-role account.
    assert demo.client.get('/api/v1/me/elders', headers=demo.elder).status_code == 403
