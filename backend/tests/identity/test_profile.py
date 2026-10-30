"""PROF01/PROF02: real access matrix, versioning, and child write protection."""
from datetime import date
from conftest import auth_header, hdr

def test_profile_read_access_matrix(env):
    app, client, clock, seed = env
    elder_id = seed['elder']['elder_id']
    path = f'/api/v1/elders/{elder_id}/profile'
    elder = auth_header(client, seed['elder']['phone'], 'elder')
    bound = auth_header(client, seed['bound_child']['phone'], 'child')
    unbound = auth_header(client, seed['unbound_child']['phone'], 'child')
    stranger = auth_header(client, seed['stranger_elder']['phone'], 'elder')
    assert client.get(path).status_code == 401
    assert client.get(path, headers=unbound).status_code == 403
    assert client.get(path, headers=stranger).status_code == 403
    for headers in (elder, bound):
        response = client.get(path, headers=headers)
        assert response.status_code == 200, response.text
        data = response.json()['data']
        assert data['elder_id'] == elder_id and data['version'] >= 1
        assert data['timezone'] == 'Asia/Hong_Kong' and data['birth_date'] == '1958-05-12'

def test_profile_update_bumps_version_and_persists(env):
    app, client, clock, seed = env
    elder_id = seed['elder']['elder_id']
    elder = auth_header(client, seed['elder']['phone'], 'elder')
    before = client.get(f'/api/v1/elders/{elder_id}/profile', headers=elder).json()['data']
    updated = client.put(f'/api/v1/elders/{elder_id}/profile', headers=hdr(elder, 'prof-1'),
                         json={'expected_version': before['version'], 'patch': {'medical_notes': '社区复查', 'allergies': ['青霉素']}})
    assert updated.status_code == 200, updated.text
    data = updated.json()['data']
    assert data['version'] == before['version'] + 1
    assert data['medical_notes'] == '社区复查' and data['allergies'] == ['青霉素']
    assert data['display_name'] == before['display_name']
    assert data['updated_at'] >= before['updated_at']
    reread = client.get(f'/api/v1/elders/{elder_id}/profile', headers=elder).json()['data']
    assert reread['version'] == data['version'] and reread['medical_notes'] == '社区复查'

def test_profile_update_rejects_stale_version_and_replays_idempotently(env):
    app, client, clock, seed = env
    elder_id = seed['elder']['elder_id']
    elder = auth_header(client, seed['elder']['phone'], 'elder')
    version = client.get(f'/api/v1/elders/{elder_id}/profile', headers=elder).json()['data']['version']
    body = {'expected_version': version, 'patch': {'medical_notes': '第一次'}}
    first = client.put(f'/api/v1/elders/{elder_id}/profile', headers=hdr(elder, 'same-key'), json=body)
    replay = client.put(f'/api/v1/elders/{elder_id}/profile', headers=hdr(elder, 'same-key'), json=body)
    assert first.status_code == replay.status_code == 200
    assert first.json()['data'] == replay.json()['data']
    stale = client.put(f'/api/v1/elders/{elder_id}/profile', headers=hdr(elder, 'stale'), json=body)
    assert stale.status_code == 409 and stale.json()['error']['code'] == 'VERSION_CONFLICT'
    assert stale.json()['error']['details']['current_version'] == version + 1
    empty = client.put(f'/api/v1/elders/{elder_id}/profile', headers=hdr(elder, 'empty'), json={'expected_version': version + 1, 'patch': {}})
    assert empty.status_code == 422

def test_child_cannot_write_the_profile_directly(env):
    app, client, clock, seed = env
    elder_id = seed['elder']['elder_id']
    bound = auth_header(client, seed['bound_child']['phone'], 'child')
    response = client.put(f'/api/v1/elders/{elder_id}/profile', headers=hdr(bound, 'child-write'),
                          json={'expected_version': 1, 'patch': {'medical_notes': '代改'}})
    assert response.status_code == 403
    assert response.json()['error']['code'] == 'PROPOSAL_REQUIRED'

def test_birth_date_can_be_cleared_but_other_fields_cannot(env):
    app, client, clock, seed = env
    elder_id = seed['elder']['elder_id']
    elder = auth_header(client, seed['elder']['phone'], 'elder')
    cleared = client.put(f'/api/v1/elders/{elder_id}/profile', headers=hdr(elder, 'clear-birth'),
                         json={'expected_version': 1, 'patch': {'birth_date': None}})
    assert cleared.status_code == 200 and cleared.json()['data']['birth_date'] is None
    null_name = client.put(f'/api/v1/elders/{elder_id}/profile', headers=hdr(elder, 'null-name'),
                           json={'expected_version': 2, 'patch': {'display_name': None}})
    assert null_name.status_code == 422
