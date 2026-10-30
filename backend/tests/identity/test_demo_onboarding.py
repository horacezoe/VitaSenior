"""DEMO01 / ONB01 / ONB02: independent pair, draft isolation, confirmed profile."""
from sqlalchemy import func, select
from app.models.identity import ElderProfile, FamilyBinding, User
from conftest import auth_header, hdr

def test_demo01_creates_independent_unbound_pair(env):
    app, client, clock, seed = env
    first = client.post('/api/v1/demo/experiences', json={'scenario': 'diabetes_daily'}, headers={'Idempotency-Key': 'k1'})
    second = client.post('/api/v1/demo/experiences', json={'scenario': 'diabetes_daily'}, headers={'Idempotency-Key': 'k2'})
    assert first.status_code == second.status_code == 201
    a, b = first.json()['data'], second.json()['data']
    assert a['demo_id'] != b['demo_id'] and a['elder_id'] != b['elder_id']
    assert a['elder_account'] != b['elder_account']
    assert a['is_mock'] is True and a['history_days'] == 14
    assert a['elder_account']['role'] == 'elder' and a['child_account']['role'] == 'child'
    for account in (a['elder_account'], a['child_account']):
        assert len(account['phone']) == 11 and account['phone'].isdigit()
    with app.state.sessions() as tx:
        assert tx.scalar(select(func.count()).select_from(User).where(User.demo_id == a['demo_id'])) == 2
        assert tx.scalar(select(func.count()).select_from(FamilyBinding).where(FamilyBinding.elder_id == a['elder_id'])) == 0
        assert tx.get(ElderProfile, a['elder_id']).onboarding_status == 'draft'

def test_demo01_replays_same_key_without_new_rows(env):
    app, client, clock, seed = env
    body = {'scenario': 'diabetes_daily'}
    first = client.post('/api/v1/demo/experiences', json=body, headers={'Idempotency-Key': 'same'})
    again = client.post('/api/v1/demo/experiences', json=body, headers={'Idempotency-Key': 'same'})
    assert first.status_code == again.status_code == 201
    assert first.json()['data'] == again.json()['data']
    assert first.json()['meta']['request_id'] != again.json()['meta']['request_id']
    with app.state.sessions() as tx:
        assert tx.scalar(select(func.count()).select_from(User)) == 6  # 4 seeded + one demo pair

def test_demo01_allocated_phones_use_the_normal_login(env, demo):
    app, client, clock, seed = env
    me = demo.client.get('/api/v1/me', headers=demo.elder).json()['data']
    assert me['elder_id'] == demo.elder_id and me['user']['role'] == 'elder'
    assert me['bound_elders'] == []
    child_me = demo.client.get('/api/v1/me', headers=demo.child).json()['data']
    assert child_me['elder_id'] is None and child_me['bound_elders'] == []

def test_demo01_is_rate_limited(env):
    app, client, clock, seed = env
    for index in range(10):
        assert client.post('/api/v1/demo/experiences', json={}, headers={'Idempotency-Key': f'k{index}'}).status_code == 201
    blocked = client.post('/api/v1/demo/experiences', json={}, headers={'Idempotency-Key': 'k-over'})
    assert blocked.status_code == 429
    assert blocked.json()['error']['code'] == 'RATE_LIMITED'
    assert int(blocked.headers['Retry-After']) >= 1

def test_onb01_match_never_touches_the_confirmed_profile(demo):
    before = demo.client.get(f'/api/v1/elders/{demo.elder_id}/profile', headers=demo.elder).json()['data']
    matched = demo.client.post(f'/api/v1/elders/{demo.elder_id}/onboarding/match',
                               json={'sample_identity_key': 'community_sample_001'}, headers=hdr(demo.elder, 'match-1'))
    assert matched.status_code == 200, matched.text
    data = matched.json()['data']
    assert data['match_status'] == 'matched'
    assert data['profile_draft']['display_name'] == '陈阿姨'
    assert data['medication_plan_drafts'] and data['is_mock'] is True and data['draft_id']
    after = demo.client.get(f'/api/v1/elders/{demo.elder_id}/profile', headers=demo.elder).json()['data']
    assert after['version'] == before['version'] and after['display_name'] == before['display_name']
    assert after['onboarding_status'] == 'draft'
    replay = demo.client.post(f'/api/v1/elders/{demo.elder_id}/onboarding/match',
                              json={'sample_identity_key': 'community_sample_001'}, headers=hdr(demo.elder, 'match-1'))
    assert replay.json()['data']['draft_id'] == data['draft_id']
    fresh = demo.client.post(f'/api/v1/elders/{demo.elder_id}/onboarding/match',
                             json={'sample_identity_key': 'unknown_key'}, headers=hdr(demo.elder, 'match-2'))
    assert fresh.json()['data']['match_status'] == 'not_found'
    assert fresh.json()['data']['medication_plan_drafts'] == []

def test_onb02_confirms_and_imports_plans_once(demo, fakes):
    medication, history = fakes.medication, fakes.history
    matched = demo.client.post(f'/api/v1/elders/{demo.elder_id}/onboarding/match',
                               json={'sample_identity_key': 'community_sample_001'}, headers=hdr(demo.elder, 'match-1')).json()['data']
    body = {'draft_id': matched['draft_id'],
            'profile': {'display_name': '陈阿姨', 'birth_date': '1958-05-12', 'sex': 'female',
                        'conditions': ['糖尿病（演示档案）'], 'allergies': [], 'medical_notes': '确认'},
            'medication_plans': matched['medication_plan_drafts'], 'expected_version': 1}
    confirmed = demo.client.post(f'/api/v1/elders/{demo.elder_id}/onboarding/confirm', json=body, headers=hdr(demo.elder, 'confirm-1'))
    assert confirmed.status_code == 200, confirmed.text
    profile = confirmed.json()['data']
    assert profile['onboarding_status'] == 'confirmed' and profile['version'] == 2
    assert profile['source'] == 'user_confirmed' and profile['display_name'] == '陈阿姨'
    assert [c['plans'] for c in medication.imports] == [['演示药品A']]
    assert history.calls == [{'elder_id': demo.elder_id, 'demo_id': demo.experience['demo_id'], 'days': 14}]
    # The draft is consumed: a second confirm cannot re-import the same plans.
    again = demo.client.post(f'/api/v1/elders/{demo.elder_id}/onboarding/confirm', json=body, headers=hdr(demo.elder, 'confirm-2'))
    assert again.status_code in (404, 409), again.text
    assert len(medication.imports) == 1

def test_onb02_rejects_a_stale_expected_version(demo, fakes):
    matched = demo.client.post(f'/api/v1/elders/{demo.elder_id}/onboarding/match',
                               json={'sample_identity_key': 'community_sample_001'}, headers=hdr(demo.elder, 'match-1')).json()['data']
    body = {'draft_id': matched['draft_id'],
            'profile': {'display_name': '陈阿姨'},
            'medication_plans': [], 'expected_version': 99}
    conflict = demo.client.post(f'/api/v1/elders/{demo.elder_id}/onboarding/confirm', json=body, headers=hdr(demo.elder, 'confirm-bad'))
    assert conflict.status_code == 409
    assert conflict.json()['error']['code'] == 'VERSION_CONFLICT'
    assert conflict.json()['error']['details']['current_version'] == 1

def test_onb02_rolls_back_when_the_medication_port_is_unimplemented(demo):
    """Real B port is still a 501 stub: the profile must NOT be confirmed."""
    matched = demo.client.post(f'/api/v1/elders/{demo.elder_id}/onboarding/match',
                               json={'sample_identity_key': 'community_sample_001'}, headers=hdr(demo.elder, 'match-1')).json()['data']
    assert matched['medication_plan_drafts'], 'fixture must exercise the cross-domain import'
    body = {'draft_id': matched['draft_id'], 'profile': {'display_name': '陈阿姨'},
            'medication_plans': matched['medication_plan_drafts'], 'expected_version': 1}
    failed = demo.client.post(f'/api/v1/elders/{demo.elder_id}/onboarding/confirm', json=body, headers=hdr(demo.elder, 'confirm-x'))
    assert failed.status_code == 501, failed.text
    assert failed.json()['error']['code'] == 'MODULE_NOT_IMPLEMENTED'
    profile = demo.client.get(f'/api/v1/elders/{demo.elder_id}/profile', headers=demo.elder).json()['data']
    assert profile['version'] == 1 and profile['onboarding_status'] == 'draft'
    assert profile['display_name'] == '演示老人'
