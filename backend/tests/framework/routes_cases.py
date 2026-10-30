"""Shared authorized-request cases for the 45 P0 operations.

Used by the long-term capability test (test_all_routes.py) and the frozen F0
stage test (test_stage_f0.py). Bodies are schema-valid and authorized; the
fixtures they reference are created by the `resources` fixture in conftest.py.
"""

CASES = [
    ('DEMO01', 'post', '/demo/experiences', {}, 'elder'),
    ('ONB01', 'post', '/elders/{elder}/onboarding/match', {'sample_identity_key': 'sample'}, 'elder'),
    ('ONB02', 'post', '/elders/{elder}/onboarding/confirm', {'draft_id': 'draft', 'profile': {'display_name': '老人'}, 'medication_plans': [], 'expected_version': 1}, 'elder'),
    ('PROF01', 'get', '/elders/{elder}/profile', None, 'elder'),
    ('PROF02', 'put', '/elders/{elder}/profile', {'expected_version': 1, 'patch': {'medical_notes': 'note'}}, 'elder'),
    ('BIND01', 'post', '/elders/{elder}/binding-codes', None, 'elder'),
    ('BIND02', 'post', '/family-bindings/preview', {'code': '0012'}, 'bound_child'),
    ('BIND03', 'post', '/family-bindings', {'code': '0012', 'relationship': '子女'}, 'bound_child'),
    ('BIND04', 'get', '/me/elders', None, 'bound_child'),
    ('MEDIA01', 'post', '/media', 'multipart', 'elder'),
    ('MEDIA02', 'get', '/media/asset', None, 'elder'),
    ('MEDIA03', 'get', '/media/asset/content', None, 'elder'),
    ('CHANGE01', 'post', '/elders/{elder}/change-proposals', {'target_type': 'profile', 'target_id': '{elder}', 'operation': 'update', 'base_version': 1, 'patch': {'medical_notes': 'note'}}, 'bound_child'),
    ('CHANGE02', 'get', '/elders/{elder}/change-proposals', None, 'bound_child'),
    ('CHANGE03', 'get', '/change-proposals/proposal', None, 'elder'),
    # accept exercises the whole apply path (target write + C memory invalidation),
    # so an undeclared CHANGE04 must still answer 501; reject only closes the notice.
    ('CHANGE04', 'post', '/change-proposals/proposal/decision', {'decision': 'accept'}, 'elder'),
    ('PLAN01', 'get', '/elders/{elder}/medication-plans', None, 'bound_child'),
    ('PLAN02', 'post', '/elders/{elder}/medication-plans', {'name': 'demo', 'dose_display': 'provided', 'schedule': {'mode': 'fixed', 'slots': [{'slot_id': 'morning', 'local_time': '08:00'}]}, 'start_date': '2026-10-30'}, 'elder'),
    ('PLAN03', 'put', '/medication-plans/plan', {'expected_version': 1, 'patch': {'notes': 'note'}}, 'elder'),
    ('SET01', 'get', '/elders/{elder}/reminder-settings', None, 'bound_child'),
    ('SET02', 'put', '/elders/{elder}/reminder-settings', {'expected_version': 1, 'patch': {'voice_enabled': True}}, 'elder'),
    ('TASK01', 'get', '/elders/{elder}/tasks?date=2026-10-30', None, 'elder'),
    ('REC01', 'get', '/elders/{elder}/checkins?date=2026-10-30', None, 'elder'),
    ('REC02', 'post', '/elders/{elder}/checkins', {'type': 'exercise', 'occurred_at': '2026-10-30T04:00:00Z', 'payload': {'activity': '散步', 'duration_minutes': 20}}, 'elder'),
    ('REC03', 'put', '/checkins/checkin', {'expected_version': 1, 'payload': {'activity': '散步', 'duration_minutes': 30}}, 'elder'),
    ('REC04', 'delete', '/checkins/checkin?expected_version=1', None, 'elder'),
    ('DASH01', 'get', '/elders/{elder}/dashboard', None, 'bound_child'),
    ('CAL01', 'get', '/elders/{elder}/calendar?month=2026-10', None, 'bound_child'),
    ('REPORT01', 'get', '/elders/{elder}/reports/daily?date=2026-10-30', None, 'bound_child'),
    ('NOTI01', 'post', '/elders/{elder}/presence', {'client_id': 'page', 'visible': True}, 'elder'),
    ('NOTI02', 'get', '/elders/{elder}/notifications', None, 'bound_child'),
    ('NOTI03', 'post', '/notifications/notice/events', {'event_id': 'evt', 'event_type': 'displayed'}, 'elder'),
    ('NOTI04', 'post', '/elders/{elder}/family-reminders', {'category': 'general', 'text': '关怀'}, 'bound_child'),
    ('AI01', 'post', '/ai/asr', {'elder_id': '{elder}', 'audio_asset_id': 'asset'}, 'elder'),
    ('AI02', 'post', '/ai/tts', {'elder_id': '{elder}', 'text': '您好'}, 'elder'),
    ('AGENT01', 'post', '/agent/turns', {'elder_id': '{elder}', 'client_turn_id': 'client1', 'text': '您好'}, 'elder'),
    ('AGENT02', 'post', '/agent/actions/action/decision', {'decision': 'confirm'}, 'elder'),
    ('MEM01', 'get', '/elders/{elder}/memory', None, 'bound_child'),
    ('MEM02', 'put', '/elders/{elder}/memory/entries/entry', {'expected_version': 1, 'text': '更正'}, 'elder'),
    ('MEM03', 'delete', '/elders/{elder}/memory/entries/entry?expected_version=1', None, 'elder'),
]

# The five operations F0 shipped as real implementations.
F0_CAPABILITIES = frozenset({"SYS01", "SYS02", "AUTH01", "AUTH02", "AUTH04"})

def call(client, tokens, elder_id, operation, method, path, body, account):
    import json
    kwargs = {'headers': tokens[account]}
    if body == 'multipart':
        kwargs.update(files={'file': ('test.wav', b'RIFF-test', 'audio/wav')}, data={'purpose': 'agent_audio', 'elder_id': elder_id})
    elif body is not None:
        kwargs['json'] = json.loads(json.dumps(body).replace('{elder}', elder_id))
    return client.request(method, '/api/v1' + path.format(elder=elder_id), **kwargs)
