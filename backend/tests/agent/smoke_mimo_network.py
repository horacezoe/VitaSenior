"""Explicit real MiMo HTTP smoke using normal app.main:app and A's factory.

python tests/agent/smoke_mimo_network.py --env-file .env --live --image <demo.jpg>
Starts a hidden Uvicorn process on a random localhost port with a NEW temp DB.
No provider/service injection. Two paid model requests; retries replay saved data.
Checks Runtime, real text/photo, confirmation, dashboard/report, restart and
explicit no-key mock fallback. Does not print credentials/tokens/media tickets.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

BACKEND = Path(__file__).resolve().parents[2]
STOP_PATH = '/_c_f2_network_stop'


class Server:
    def __init__(self, env):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            self.port = sock.getsockname()[1]
        self.base = f'http://127.0.0.1:{self.port}'
        self.env = {**env, 'PUBLIC_BASE_URL': self.base}
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self.process = None

    def request(self, path, *, token=None, key=None, body=None, raw=None, content_type=None,
                method=None, expected=200, timeout=50):
        url = path if path.startswith('http') else self.base+path
        parsed = urlsplit(url)
        if parsed.hostname != '127.0.0.1' or parsed.port != self.port:
            raise RuntimeError('Refusing an unexpected HTTP destination')
        headers = {}
        if token:
            headers['Authorization'] = 'Bearer '+token
        if key:
            headers['Idempotency-Key'] = key
        if body is not None:
            raw = json.dumps(body).encode()
            content_type = 'application/json'
        if content_type:
            headers['Content-Type'] = content_type
        request = urllib.request.Request(url, data=raw, headers=headers, method=method)
        try:
            with self.opener.open(request, timeout=timeout) as response:
                status, content = response.status, response.read()
        except urllib.error.HTTPError as exc:
            status, content = exc.code, exc.read()
        result = json.loads(content) if content[:1] in {b'{', b'['} else content
        if status != expected:
            error = result.get('error', {}) if isinstance(result, dict) else {}
            raise RuntimeError(f'{path.split("?")[0]}: {status}, {error.get("code", "NON_JSON")}, '
                               f'upstream={error.get("details", {}).get("upstream_status")}')
        return result.get('data', result) if isinstance(result, dict) else result

    def __enter__(self):
        # Import the normal production entry. Only a harness shutdown route is
        # added; it is excluded from OpenAPI and never written to app sources.
        code = f'''import uvicorn
from app.main import app
server=uvicorn.Server(uvicorn.Config(app,host="127.0.0.1",port={self.port},workers=1,log_level="warning"))
def stop():
    server.should_exit=True
    return {{"stopping":True}}
app.add_api_route("{STOP_PATH}",stop,methods=["POST"],include_in_schema=False)
server.run()
'''
        self.process = subprocess.Popen([sys.executable, '-c', code], cwd=BACKEND, env=self.env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        try:
            for _ in range(100):
                if self.process.poll() is not None:
                    raise RuntimeError('Normal configured Uvicorn exited during startup')
                try:
                    assert self.request('/api/v1/health', timeout=.5)['status'] == 'ok'
                    return self
                except OSError:
                    time.sleep(.1)
            raise RuntimeError('Normal configured Uvicorn startup timed out')
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *_):
        if self.process is not None and self.process.poll() is None:
            try:
                self.request(STOP_PATH, body={}, timeout=3)
                self.process.wait(timeout=15)
            except (OSError, RuntimeError, subprocess.TimeoutExpired):
                if os.name == 'nt':
                    subprocess.run(['taskkill', '/PID', str(self.process.pid), '/T', '/F'],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), timeout=10)
                else:
                    self.process.terminate()
                self.process.wait(timeout=10)


def config_from(path):
    values = {}
    allowed = {'CHAT_API_KEY', 'CHAT_BASE_URL', 'CHAT_MODEL', 'LIVE_UNDERSTANDING'}
    if path:
        for number, line in enumerate(path.read_text(encoding='utf-8-sig').splitlines(), 1):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            key, separator, value = line.partition('=')
            key, value = key.strip(), value.strip()
            if not separator or not re.fullmatch(r'[A-Z][A-Z0-9_]*', key):
                raise ValueError(f'Invalid env file syntax at line {number}')
            if key in allowed:
                if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
                    value = value[1:-1]
                values[key] = value
    return {name: values.get(name, os.getenv(name, '')) for name in allowed}


def upload(server, token, elder, raw, mime):
    boundary = 'c-f2-'+secrets.token_hex(8)
    chunks = []
    for field, value in [('elder_id', elder), ('purpose', 'meal')]:
        chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"\r\n\r\n{value}\r\n'.encode())
    chunks.extend([f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="demo-meal.jpg"\r\nContent-Type: {mime}\r\n\r\n'.encode(),
                   raw, f'\r\n--{boundary}--\r\n'.encode()])
    return server.request('/api/v1/media', token=token, key='network-photo-upload', raw=b''.join(chunks),
                          content_type='multipart/form-data; boundary='+boundary, expected=201)


def run():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', type=Path)
    parser.add_argument('--image', type=Path, required=True)
    parser.add_argument('--live', action='store_true')
    args = parser.parse_args()
    config = config_from(args.env_file)
    if not args.live and config.get('LIVE_UNDERSTANDING') != '1':
        parser.error('Use --live to explicitly allow two real model requests')
    missing = [name for name in ['CHAT_API_KEY', 'CHAT_BASE_URL', 'CHAT_MODEL'] if not config[name]]
    if missing:
        parser.error('Missing '+', '.join(missing))
    if args.image.stat().st_size > 5*1024*1024:
        parser.error('Demo image exceeds 5 MiB')
    raw = args.image.read_bytes()
    mime = ('image/jpeg' if raw.startswith(b'\xff\xd8\xff') else 'image/png' if raw.startswith(b'\x89PNG\r\n\x1a\n') else
            'image/webp' if raw[:4] == b'RIFF' and raw[8:12] == b'WEBP' else None)
    if not mime:
        parser.error('Use a real PNG, JPEG or WebP demo image')
    parent = BACKEND/'.pytest_cache'/'c-f2-network'
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='run-', dir=parent) as directory:
        env = {**os.environ, **{name: config[name] for name in ['CHAT_API_KEY', 'CHAT_BASE_URL', 'CHAT_MODEL']},
               'CHAT_PROVIDER': 'real', 'ASR_PROVIDER': 'mock', 'TTS_PROVIDER': 'mock', 'DATA_DIR': directory,
               'SCANNER_ENABLED': 'false', 'WEB_PUSH_ENABLED': 'false', 'APP_ENV': 'demo',
               'APP_TIMEZONE': 'Asia/Hong_Kong', 'MEDIA_TICKET_SECRET': secrets.token_urlsafe(32), 'PYTHONIOENCODING': 'utf-8'}
        env.pop('DATABASE_URL', None)  # Always isolate from any running database.
        invalid = {**env, 'CHAT_API_KEY': ''}
        rejected = subprocess.run([sys.executable, '-c', 'import app.main'], cwd=BACKEND, env=invalid,
            capture_output=True, timeout=15, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if rejected.returncode == 0 or b'CHAT_PROVIDER=real requires' not in rejected.stderr:
            raise RuntimeError('Missing-key normal startup did not fail explicitly')
        print('MISSING_KEY_STARTUP_REJECTED')
        records, turns = [], []
        day = datetime.now(timezone.utc).astimezone(ZoneInfo('Asia/Hong_Kong')).date().isoformat()
        with Server(env) as server:
            demo = server.request('/api/v1/demo/experiences', key='real-network-demo', body={}, expected=201)
            def login(account):
                challenge = server.request('/api/v1/auth/code', body=account)
                return server.request('/api/v1/auth/login', body={**account,
                    'challenge_id': challenge['challenge_id'], 'code': '123456'})['access_token']
            owner, child = login(demo['elder_account']), login(demo['child_account'])
            elder = demo['elder_id']
            runtime = server.request('/api/v1/runtime', token=owner)
            assert runtime['providers'] == {'chat': 'real', 'asr': 'mock', 'tts': 'mock'}
            server.request(f'/api/v1/elders/{elder}/profile', token=child, expected=403)
            profile = server.request(f'/api/v1/elders/{elder}/profile', token=owner)
            draft = server.request(f'/api/v1/elders/{elder}/onboarding/match', token=owner, key='network-draft',
                                   body={'sample_identity_key': 'c-f2-network-manual'})
            server.request(f'/api/v1/elders/{elder}/onboarding/confirm', token=owner, key='network-profile', body={
                'draft_id': draft['draft_id'], 'expected_version': profile['version'],
                'profile': {'display_name': 'C真实网络演示老人'}, 'medication_plans': []})
            binding = server.request(f'/api/v1/elders/{elder}/binding-codes', token=owner,
                                     key='network-binding-code', body={}, expected=201)
            server.request('/api/v1/family-bindings', token=child, key='network-binding', expected=201,
                           body={'code': binding['code'], 'relationship': '子女'})
            image = upload(server, owner, elder, raw, mime)
            for index, (mode, text, images) in enumerate([
                    ('text', '今天早餐吃了鸡蛋和全麦面包，请准备记录', []),
                    ('image', '这是今天午餐的餐食照片，请识别并准备记录', [image['asset_id']])]):
                body = {'elder_id': elder, 'client_turn_id': 'network-'+mode, 'text': text, 'image_asset_ids': images}
                start = time.monotonic()
                pending = server.request('/api/v1/agent/turns', token=owner, key='turn-'+mode, body=body, expected=201)
                assert pending['providers']['chat'] == 'real' and pending['degraded'] == ['tts_unavailable']
                assert len(pending['actions']) == 1 and pending['actions'][0]['type'] == 'record_diet'
                assert pending['actions'][0]['status'] == 'pending' and '【模拟】' not in pending['reply']['text']
                before = server.request(f'/api/v1/elders/{elder}/checkins?date={day}', token=owner)
                assert len(before['items']) == index, 'Pending action created a health record'
                assert server.request('/api/v1/agent/turns', token=owner, key='turn-'+mode, body=body, expected=201) == pending
                decision_path = '/api/v1/agent/actions/'+pending['actions'][0]['action_id']+'/decision'
                result = server.request(decision_path, token=owner, key='confirm-'+mode, body={'decision': 'confirm'})
                assert server.request(decision_path, token=owner, key='confirm-again-'+mode, body={'decision': 'confirm'}) == result
                record = result['result']
                assert record['source'] == 'agent_confirmed' and record['version'] == 1
                dashboard = server.request(f'/api/v1/elders/{elder}/dashboard', token=child)
                report = server.request(f"/api/v1/elders/{elder}/reports/daily?date={record['local_date']}", token=child)
                assert any(r['checkin_id'] == record['checkin_id'] for r in dashboard['today_records']['diet'])
                assert any(r['checkin_id'] == record['checkin_id'] for r in report['records']['diet'])
                assert len(report['records']['diet']) == index+1
                records.append(record['checkin_id'])
                turns.append((mode, body, pending))
                print(json.dumps({'mode': mode, 'model': config['CHAT_MODEL'], 'provider': 'real',
                    'elapsed_ms': int((time.monotonic()-start)*1000), 'foods': record['payload']['foods'],
                    'source': record['source'], 'confirmed_once': True, 'child_same_record': True}, ensure_ascii=False))
        with Server(env) as restarted:
            assert restarted.request('/api/v1/runtime', token=owner)['providers']['chat'] == 'real'
            for mode, body, pending in turns:
                assert restarted.request('/api/v1/agent/turns', token=owner, key='turn-'+mode, body=body, expected=201) == pending
            persisted = restarted.request(f'/api/v1/elders/{elder}/checkins?date={day}', token=child)['items']
            assert {r['checkin_id'] for r in persisted} == set(records) and len(persisted) == 2
            print('REAL_RESTART_PERSISTENCE_OK: same sessions, two records, saved turn replay')
        mock_env = {**env, 'CHAT_PROVIDER': 'mock'}
        for name in ['CHAT_API_KEY', 'CHAT_BASE_URL', 'CHAT_MODEL']:
            mock_env.pop(name, None)
        with Server(mock_env) as fallback:
            assert fallback.request('/api/v1/runtime', token=owner)['providers'] == {'chat': 'mock', 'asr': 'mock', 'tts': 'mock'}
            pending = fallback.request('/api/v1/agent/turns', token=owner, key='mock-fallback', expected=201,
                body={'elder_id': elder, 'client_turn_id': 'mock-fallback', 'text': '演示午餐', 'mock_fixture_id': 'meal_lunch'})
            assert pending['providers']['chat'] == 'mock' and pending['actions'][0]['status'] == 'pending'
            persisted = fallback.request(f'/api/v1/elders/{elder}/checkins?date={day}', token=child)['items']
            assert {r['checkin_id'] for r in persisted} == set(records) and len(persisted) == 2
            print('EXPLICIT_NO_KEY_MOCK_FALLBACK_OK')
    print('C_MIMO_NETWORK_OK: normal configured factory, actual text/image, restart and explicit mock fallback; temporary DB only')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
    sys.stderr.reconfigure(encoding='utf-8')
    run()
