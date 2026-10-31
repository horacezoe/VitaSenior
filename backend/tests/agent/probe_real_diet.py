"""Explicit paid C probe, never collected by pytest.

LIVE_UNDERSTANDING=1 CHAT_API_KEY=... CHAT_BASE_URL=... CHAT_MODEL=...
python tests/agent/probe_real_diet.py --image /path/to/a/demo-meal.jpg

Uses a temporary DB, real default A/B/C business ports and explicit RealUnderstanding
injection. A's production factory/startup/runtime are a separate integration gate.
Default: two model requests (text and image); --mode selects one partial probe.
Never prints keys/tokens/media URLs.
"""
import argparse
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND))

from fastapi.testclient import TestClient
from app.core.config import Settings
from app.core.clock import local_date
from app.main import create_app
from app.providers.real_understanding import RealUnderstanding, MAX_IMAGE_BYTES
from app.seed import framework_seed


def run():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', type=Path, help='A non-private demo meal photograph; required for image/both mode')
    parser.add_argument('--mode', choices=['both', 'text', 'image'], default='both', help='Partial probes do not count as both FAST-02 inputs')
    parser.add_argument('--env-file', type=Path, help='Explicitly read local CHAT_* settings; application does not auto-load this file')
    parser.add_argument('--live', action='store_true', help='Explicitly enable the selected one or two real model requests')
    args = parser.parse_args()
    if args.env_file:
        allowed = {'CHAT_API_KEY', 'CHAT_BASE_URL', 'CHAT_MODEL', 'LIVE_UNDERSTANDING'}
        for number, line in enumerate(args.env_file.read_text(encoding='utf-8-sig').splitlines(), 1):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            key, separator, value = line.partition('=')
            key, value = key.strip(), value.strip()
            if not separator or not re.fullmatch(r'[A-Z][A-Z0-9_]*', key):
                parser.error(f'Invalid env-file syntax at line {number}')
            if key in allowed:
                if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
                    value = value[1:-1]
                os.environ[key] = value
    if not args.live and os.getenv('LIVE_UNDERSTANDING') != '1':
        parser.error('Real requests are disabled; explicitly use --live or LIVE_UNDERSTANDING=1')
    missing = [name for name in ['CHAT_API_KEY', 'CHAT_BASE_URL', 'CHAT_MODEL'] if not os.getenv(name)]
    if missing:
        parser.error('Missing configuration: ' + ', '.join(missing))
    raw, mime = None, None
    if args.mode != 'text':
        if args.image is None:
            parser.error('--image is required for image/both mode')
        if args.image.stat().st_size > MAX_IMAGE_BYTES:
            parser.error('The demo meal photograph must be at most 5 MiB')
        raw = args.image.read_bytes()
        mime = ('image/png' if raw.startswith(b'\x89PNG\r\n\x1a\n') else
                'image/jpeg' if raw.startswith(b'\xff\xd8\xff') else
                'image/webp' if raw[:4] == b'RIFF' and raw[8:12] == b'WEBP' else None)
        if mime is None:
            parser.error('Use a PNG, JPEG or WebP demo photograph')
    provider = RealUnderstanding(api_key=os.environ['CHAT_API_KEY'], base_url=os.environ['CHAT_BASE_URL'],
                                 model=os.environ['CHAT_MODEL'])
    temporary_parent = BACKEND / '.pytest_cache' / 'c-f2-live'
    temporary_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='run-', dir=temporary_parent) as directory:
        # Explicit independent C probe. Do not pretend a missing A factory is live.
        app = create_app(Settings(data_dir=Path(directory), database_url=None, scanner_enabled=False,
                                  chat_provider='mock', asr_provider='mock', tts_provider='mock'))
        app.state.agent_chat = provider
        with TestClient(app, raise_server_exceptions=False) as client:
            seed = framework_seed(app.state.sessions, app.state.clock)
            def checked(method, path, expected=200, **kwargs):
                response = client.request(method, path, **kwargs)
                if response.status_code != expected:
                    try:
                        code = response.json().get('error', {}).get('code', 'UNKNOWN')
                    except ValueError:
                        code = 'NON_JSON_RESPONSE'
                    upstream = response.json().get('error', {}).get('details', {}).get('upstream_status') if code != 'NON_JSON_RESPONSE' else None
                    raise RuntimeError(f'{method} {path.split("?")[0]}: {response.status_code} {code}; upstream_status={upstream}')
                return response.json()['data']
            headers = {}
            for role in ['elder', 'bound_child']:
                account = {key: seed[role][key] for key in ['phone', 'role']}
                challenge = checked('POST', '/api/v1/auth/code', json=account)
                login = checked('POST', '/api/v1/auth/login', json={**account,
                    'challenge_id': challenge['challenge_id'], 'code': '123456'})
                headers[role] = {'Authorization': 'Bearer '+login['access_token']}
            elder = seed['elder']['elder_id']
            requests = []
            if args.mode != 'image':
                requests.append(('text', '今天早餐吃了鸡蛋和全麦面包，请准备记录', []))
            if args.mode != 'text':
                asset = checked('POST', '/api/v1/media', 201,
                    headers={**headers['elder'], 'Idempotency-Key': 'live-upload'},
                    data={'elder_id': elder, 'purpose': 'meal'}, files={'file': ('demo-meal', raw, mime)})
                requests.append(('image', '这是今天午餐的餐食照片，请识别并准备记录', [asset['asset_id']]))
            for index, (mode, text, images) in enumerate(requests):
                start = time.monotonic()
                body = {'elder_id': elder, 'client_turn_id': 'live-'+mode, 'text': text, 'image_asset_ids': images}
                turn_headers = {**headers['elder'], 'Idempotency-Key': 'live-'+mode}
                turn = checked('POST', '/api/v1/agent/turns', 201, headers=turn_headers, json=body)
                if len(turn['actions']) != 1 or turn['actions'][0]['type'] != 'record_diet':
                    raise RuntimeError(mode+': actual model did not yield a clear pending diet action')
                if turn['actions'][0]['status'] != 'pending' or turn['providers']['chat'] != 'real':
                    raise RuntimeError(mode+': inaccurate provider or premature confirmation')
                before = checked('GET', f'/api/v1/elders/{elder}/checkins?date={local_date(app.state.clock.now())}',
                                 headers=headers['elder'])
                assert len(before['items']) == index, 'A pending action wrote a health fact'
                replay = checked('POST', '/api/v1/agent/turns', 201, headers=turn_headers, json=body)
                assert replay == turn
                path = '/api/v1/agent/actions/'+turn['actions'][0]['action_id']+'/decision'
                decision_headers = {**headers['elder'], 'Idempotency-Key': 'confirm-'+mode}
                result = checked('POST', path, headers=decision_headers, json={'decision': 'confirm'})
                assert checked('POST', path, headers=decision_headers, json={'decision': 'confirm'}) == result
                record = result['result']
                assert record['source'] == 'agent_confirmed'
                report = checked('GET', f"/api/v1/elders/{elder}/reports/daily?date={record['local_date']}",
                                 headers=headers['bound_child'])
                dashboard = checked('GET', f'/api/v1/elders/{elder}/dashboard', headers=headers['bound_child'])
                assert any(r['checkin_id'] == record['checkin_id'] for r in report['records']['diet'])
                assert len(report['records']['diet']) == len(before['items']) + 1
                assert any(r['checkin_id'] == record['checkin_id'] for r in dashboard['today_records']['diet'])
                print(json.dumps({'mode': mode, 'model': provider.model, 'provider': turn['providers']['chat'],
                    'elapsed_ms': int((time.monotonic()-start)*1000), 'confirmed_once': True,
                    'record_source': record['source'], 'same_record_on_child_dashboard': True}, ensure_ascii=False))
    marker = 'C_LIVE_DIET_PROBE_OK' if args.mode == 'both' else 'C_LIVE_DIET_'+args.mode.upper()+'_OK'
    print(marker+': explicit real provider, temporary DB; A factory gate separate')


if __name__ == '__main__':
    run()
