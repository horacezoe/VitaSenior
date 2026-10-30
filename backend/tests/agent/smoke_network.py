"""Real default Uvicorn HTTP smoke. Always uses a new temporary database.

Run from backend: python tests/agent/smoke_network.py
No dependency replacement, no vendor calls, no running/user DB, no GUI window.
"""
import base64
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

BACKEND = Path(__file__).resolve().parents[2]


def run():
    with tempfile.TemporaryDirectory(prefix='vitasenior-c-network-') as directory:
        assert Path(directory).resolve().parent == Path(tempfile.gettempdir()).resolve()
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        base = f'http://127.0.0.1:{port}'
        env = {**os.environ, 'DATA_DIR': directory, 'PUBLIC_BASE_URL': base,
               'SCANNER_ENABLED': 'false', 'APP_ENV': 'demo', 'APP_TIMEZONE': 'Asia/Hong_Kong',
               'CHAT_PROVIDER': 'mock', 'ASR_PROVIDER': 'mock', 'TTS_PROVIDER': 'mock',
               'WEB_PUSH_ENABLED': 'false', 'PYTHONIOENCODING': 'utf-8'}
        env.pop('DATABASE_URL', None)
        code = f'''import uvicorn
from app.main import create_app
app=create_app()
server=uvicorn.Server(uvicorn.Config(app,host="127.0.0.1",port={port},workers=1))
def stop():
    server.should_exit=True
    return {{"stopping":True}}
app.add_api_route("/_c_smoke_stop",stop,methods=["POST"],include_in_schema=False)
server.run()
'''
        process = subprocess.Popen([sys.executable, '-c', code], cwd=BACKEND, env=env,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        def request(path, *, body=None, token=None, key=None, method=None, raw=None, content_type=None, expected=200):
            url = path if path.startswith('http') else base + path
            parsed = urlsplit(url)
            assert parsed.hostname == '127.0.0.1' and parsed.port == port
            headers = {}
            if token:
                headers['Authorization'] = 'Bearer ' + token
            if key:
                headers['Idempotency-Key'] = key
            data = raw
            if body is not None:
                data = json.dumps(body).encode()
                headers['Content-Type'] = 'application/json'
            if content_type:
                headers['Content-Type'] = content_type
            req = urllib.request.Request(url, data=data, headers=headers, method=method)
            try:
                with opener.open(req, timeout=10) as response:
                    status, content = response.status, response.read()
            except urllib.error.HTTPError as exc:
                status, content = exc.code, exc.read()
            if status != expected:
                raise AssertionError(f'{path.split("?")[0]} status={status} expected={expected}: {content[:500]!r}')
            return json.loads(content) if content[:1] in {b'{', b'['} else content

        def upload(token, elder_id, content, purpose, name, mime, key):
            boundary = 'vitasenior-c-fixture-boundary'
            chunks = []
            for field, value in [('purpose', purpose), ('elder_id', elder_id)]:
                chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"\r\n\r\n{value}\r\n'.encode())
            chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\nContent-Type: {mime}\r\n\r\n'.encode())
            chunks.extend([content, f'\r\n--{boundary}--\r\n'.encode()])
            return request('/api/v1/media', token=token, key=key, raw=b''.join(chunks),
                           content_type=f'multipart/form-data; boundary={boundary}', expected=201)['data']

        try:
            for _ in range(100):
                try:
                    health = request('/api/v1/health')
                    break
                except OSError:
                    if process.poll() is not None:
                        raise RuntimeError('Uvicorn exited during startup')
                    time.sleep(.1)
            else:
                raise RuntimeError('Uvicorn startup timeout')
            assert health['data']['status'] == 'ok'
            experience = request('/api/v1/demo/experiences', body={}, key='c-network-demo', expected=201)['data']
            def login(account):
                challenge = request('/api/v1/auth/code', body=account)['data']['challenge_id']
                return request('/api/v1/auth/login', body={**account, 'challenge_id': challenge, 'code': '123456'})['data']['access_token']
            owner, child = login(experience['elder_account']), login(experience['child_account'])
            elder = experience['elder_id']
            profile = request(f'/api/v1/elders/{elder}/profile', token=owner)['data']
            draft = request(f'/api/v1/elders/{elder}/onboarding/match', token=owner, key='draft',
                            body={'sample_identity_key': 'c-network-manual'})['data']
            profile = request(f'/api/v1/elders/{elder}/onboarding/confirm', token=owner, key='confirm-profile',
                              body={'draft_id': draft['draft_id'], 'expected_version': profile['version'],
                                    'profile': {'display_name': 'C网络联调老人'}, 'medication_plans': []})['data']
            code = request(f'/api/v1/elders/{elder}/binding-codes', token=owner, key='binding-code', body={}, expected=201)['data']['code']
            request('/api/v1/family-bindings', token=child, key='bind', body={'code': code, 'relationship': '子女'}, expected=201)
            png = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aXFEAAAAASUVORK5CYII=')
            image = upload(owner, elder, png, 'meal', 'pixel.png', 'image/png', 'image')
            def agent(text, client_id, fixture=None, **extra):
                return request('/api/v1/agent/turns', token=owner, key=client_id, expected=201,
                               body={'elder_id': elder, 'client_turn_id': client_id, 'text': text,
                                     'mock_fixture_id': fixture, **extra})['data']
            pending = agent('这是演示午餐', 'lunch', 'meal_lunch', image_asset_ids=[image['asset_id']])
            assert pending['actions'][0]['status'] == 'pending'
            before = agent('今天的日报', 'report-before', 'daily_query')
            assert '饮食记录 0/3' in before['reply']['text']
            action_id = pending['actions'][0]['action_id']
            decision_path = f'/api/v1/agent/actions/{action_id}/decision'
            result = request(decision_path, token=owner, key='take-action', body={'decision': 'confirm'})['data']
            replay = request(decision_path, token=owner, key='repeat-action', body={'decision': 'confirm'})['data']
            assert result == replay and result['status'] == 'confirmed' and result['result']['version'] == 1
            after = agent('今天的日报', 'report-after', 'daily_query')
            assert '饮食记录 1/3' in after['reply']['text']
            agent('我喜欢清淡饮食', 'preference', 'explicit_preference', conversation_id='preference-one')
            recall = agent('我喜欢什么', 'recall', conversation_id='preference-two')
            assert '喜欢清淡饮食' in recall['reply']['text']
            memory = request(f'/api/v1/elders/{elder}/memory', token=child)['data']
            assert len(memory['entries']) == 1
            audio = upload(owner, elder, (BACKEND/'fixtures/agent/exercise_input.wav').read_bytes(),
                           'agent_audio', 'exercise.wav', 'audio/wav', 'input-audio')
            recognized = request('/api/v1/ai/asr', token=owner, body={'elder_id': elder, 'audio_asset_id': audio['asset_id']})['data']
            assert recognized['is_mock'] and recognized['transcript'] == '我散步了20分钟。'
            speech = request('/api/v1/ai/tts', token=owner, body={'elder_id': elder, 'text': '您好'})['data']
            assert request(speech['audio_asset']['content_url']) == (BACKEND/'fixtures/agent/greeting.wav').read_bytes()
            request('/api/v1/ai/tts', token=owner, body={'elder_id': elder, 'text': '无对应真实语音的新内容'}, expected=501)
            request('/api/v1/agent/turns', token=owner, key='timeout', body={
                'elder_id': elder, 'client_turn_id': 'timeout', 'text': '超时演示', 'mock_fixture_id': 'provider_timeout'}, expected=504)
            # An explicit elder decision needs no fabricated playback receipt.
            proposal = request(f'/api/v1/elders/{elder}/change-proposals', token=child, key='proposal', expected=201,
                               body={'target_type': 'profile', 'target_id': elder, 'operation': 'update',
                                     'base_version': profile['version'], 'patch': {'medical_notes': 'C网络联调备注'}})['data']
            assert proposal['auto_apply_at'] is None
            applied = request(f"/api/v1/change-proposals/{proposal['proposal_id']}/decision", token=owner,
                              key='explicit-accept', body={'decision': 'accept'})['data']
            assert applied['status'] == 'applied' and applied['applied_by'] == 'elder_accept'
            updated = request(f'/api/v1/elders/{elder}/profile', token=owner)['data']
            assert updated['version'] == profile['version'] + 1 and updated['medical_notes'] == 'C网络联调备注'
            runtime = request('/api/v1/runtime', token=owner)['data']
            assert runtime['providers'] == {'chat': 'mock', 'asr': 'mock', 'tts': 'mock'}
            assert all(runtime['capabilities'][op] for op in ['AI01', 'AI02', 'AGENT01', 'AGENT02', 'MEM01', 'MEM02', 'MEM03', 'CHANGE04'])
            request('/_c_smoke_stop', body={})
            assert process.wait(timeout=10) == 0
            print('C_NETWORK_SMOKE_OK: default Uvicorn, auth/onboarding/binding, pending/confirm/replay, real report/memory, ASR/TTS/ticket bytes, CHANGE04 explicit accept; temporary DB only')
        finally:
            if process.poll() is None:
                try:
                    request('/_c_smoke_stop', body={})
                    process.wait(timeout=10)
                except Exception:
                    process.terminate()
                    process.wait(timeout=10)


if __name__ == '__main__':
    run()
