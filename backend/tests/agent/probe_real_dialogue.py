"""Opt-in normal TCP/factory MiMo dialogue probe, no provider injection.

Up to eight paid requests with --chat: photo understanding, four TTS calls,
one ASR, and optional chat understanding/TTS. No retries.
New temporary DB only; no keys/tokens/tickets are printed or saved.
"""
import argparse
import os
from pathlib import Path
import secrets
import sys
import tempfile

from smoke_mimo_network import BACKEND, Server, upload


def config_from(path):
    allowed = {f'{prefix}_{suffix}' for prefix in ('CHAT', 'ASR', 'TTS')
               for suffix in ('API_KEY', 'BASE_URL', 'MODEL', 'VOICE')}
    values = {name: os.getenv(name, '') for name in allowed}
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        if line.strip() and not line.lstrip().startswith('#') and '=' in line:
            name, value = line.split('=', 1)
            if name.strip() in allowed:
                values[name.strip()] = value.strip().strip('"').strip("'")
    missing = [f'{prefix}_{suffix}' for prefix in ('CHAT', 'ASR', 'TTS')
               for suffix in ('API_KEY', 'BASE_URL', 'MODEL') if not values[f'{prefix}_{suffix}']]
    if missing:
        raise ValueError('Missing local config: ' + ', '.join(missing))
    return values


def run():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', type=Path, required=True)
    parser.add_argument('--image', type=Path, required=True)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--chat', action='store_true')
    args = parser.parse_args()
    if not args.live:
        parser.error('Explicit --live is required for paid supplier calls')
    config = config_from(args.env_file)
    raw = args.image.read_bytes()
    if not raw.startswith(b'\xff\xd8\xff') or len(raw) > 5 * 1024 * 1024:
        parser.error('Use a public demo JPEG under 5 MiB')
    parent = BACKEND / '.pytest_cache' / 'c-dialogue-live'
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='run-', dir=parent) as directory:
        env = {**os.environ, **config, 'CHAT_PROVIDER': 'real', 'ASR_PROVIDER': 'real', 'TTS_PROVIDER': 'real',
               'DATA_DIR': directory, 'SCANNER_ENABLED': 'false', 'WEB_PUSH_ENABLED': 'false',
               'APP_ENV': 'demo', 'APP_TIMEZONE': 'Asia/Hong_Kong', 'PYTHONIOENCODING': 'utf-8',
               'MEDIA_TICKET_SECRET': secrets.token_urlsafe(32)}
        env.pop('DATABASE_URL', None)
        with Server(env) as server:
            demo = server.request('/api/v1/demo/experiences', body={}, key='demo', expected=201)
            def login(account):
                challenge = server.request('/api/v1/auth/code', body=account)
                return server.request('/api/v1/auth/login', body={**account,
                    'challenge_id': challenge['challenge_id'], 'code': '123456'})['access_token']
            owner, child, elder = login(demo['elder_account']), login(demo['child_account']), demo['elder_id']
            assert server.request('/api/v1/runtime', token=owner)['providers'] == {'chat': 'real', 'asr': 'real', 'tts': 'real'}
            profile = server.request(f'/api/v1/elders/{elder}/profile', token=owner)
            draft = server.request(f'/api/v1/elders/{elder}/onboarding/match', token=owner,
                key='manual-draft', body={'sample_identity_key': 'c-dialogue-manual'})
            server.request(f'/api/v1/elders/{elder}/onboarding/confirm', token=owner, key='manual-profile', body={
                'draft_id': draft['draft_id'], 'expected_version': profile['version'],
                'profile': {'display_name': 'C对话验证老人'}, 'medication_plans': []})
            code = server.request(f'/api/v1/elders/{elder}/binding-codes', token=owner, body={}, key='code', expected=201)
            server.request('/api/v1/family-bindings', token=child, body={'code': code['code'], 'relationship': '子女'}, key='bind', expected=201)
            image = upload(server, owner, elder, raw, 'image/jpeg')['asset_id']
            first_body = {'elder_id': elder, 'client_turn_id': 'photo', 'image_asset_ids': [image], 'context': {'scene': 'meal'}}
            first = server.request('/api/v1/agent/turns', token=owner, key='photo', body=first_body, expected=201)
            assert first['actions'] == [] and first['providers']['chat'] == 'real'
            assert first['reply']['audio_asset_id'] and first['providers']['tts'] == 'real'
            print('REAL_PHOTO_CLARIFICATION_OK')
        with Server(env) as server:
            second = server.request('/api/v1/agent/turns', token=owner, key='meal-slot', expected=201, body={
                'elder_id': elder, 'conversation_id': first['conversation_id'], 'client_turn_id': 'meal-slot',
                'text': '午餐。', 'image_asset_ids': [image]})
            action = second['actions'][0]
            assert action['status'] == 'pending' and action['preview']['image_asset_ids'] == [image]
            assert second['providers']['chat'] == 'not_used' and second['providers']['tts'] == 'real'
            assert second['reply']['audio_asset_id']
            print('REAL_DRAFT_RESTART_AND_MEAL_SLOT_OK')
            speech = server.request('/api/v1/ai/tts', token=owner, body={'elder_id': elder, 'text': '确认。'})
            assert speech['is_mock'] is False and speech['provider'] == 'real'
            audio = server.request(speech['audio_asset']['content_url'])
            assert audio[:4] == b'RIFF' and audio[8:12] == b'WAVE'
            body = {'elder_id': elder, 'conversation_id': first['conversation_id'], 'client_turn_id': 'voice-confirm',
                    'audio_asset_id': speech['audio_asset']['asset_id'], 'image_asset_ids': [image],
                    'context': {'pending_action_id': action['action_id']}}
            done = server.request('/api/v1/agent/turns', token=owner, key='voice-confirm', body=body, expected=201)
            assert done['providers'] == {'chat': 'not_used', 'asr': 'real', 'tts': 'real'}
            assert done['actions'][0]['status'] == 'confirmed' and done['reply']['audio_asset_id']
            assert server.request('/api/v1/agent/turns', token=owner, key='voice-confirm', body=body, expected=201) == done
            # Use the actual saved local date, never guess it from UTC expiry.
            dashboard = server.request(f'/api/v1/elders/{elder}/dashboard', token=child)
            records = dashboard['today_records']['diet']
            assert len(records) == 1 and records[0]['source'] == 'agent_confirmed'
            report = server.request(f'/api/v1/elders/{elder}/reports/daily?date=' + records[0]['local_date'], token=child)
            assert [row['checkin_id'] for row in report['records']['diet']] == [records[0]['checkin_id']]
            print('REAL_ASR_CAMERA_CONFIRM_TTS_AND_CHILD_HISTORY_OK')
            if args.chat:
                chat = server.request('/api/v1/agent/turns', token=owner, key='chat', expected=201, body={
                    'elder_id': elder, 'client_turn_id': 'chat', 'text': '你好，陪我聊聊公园里的花。'})
                assert chat['scene'] == 'health_qa' and not chat['actions']
                assert chat['providers']['chat'] == chat['providers']['tts'] == 'real' and chat['reply']['audio_asset_id']
                print('REAL_COMPANION_CHAT_AND_TTS_OK')
        print('C_REAL_DIALOGUE_OK: normal factory/TCP, three real modalities, temporary DB only; no microphone/listening acceptance claimed')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
    run()
