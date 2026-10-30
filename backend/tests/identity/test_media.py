"""MEDIA01-03: real bytes, quotas/MIME, ownership, and ticket-only playback."""
from urllib.parse import parse_qs, urlparse
from conftest import hdr

PNG = b'\x89PNG\r\n\x1a\n' + b'\x00' * 64

def upload(demo, *, key='m-1', purpose='meal', content=PNG, mime='image/png', filename='meal.png', elder_id='use-demo'):
    data = {'purpose': purpose}
    target = demo.elder_id if elder_id == 'use-demo' else elder_id
    if target is not None:
        data['elder_id'] = target
    return demo.client.post('/api/v1/media', headers=hdr(demo.elder, key),
                            files={'file': (filename, content, mime)}, data=data)

def ticket_of(content_url: str) -> str:
    return parse_qs(urlparse(content_url).query)['ticket'][0]

def test_upload_saves_real_bytes_and_replays(demo, env):
    app, client, clock, seed = env
    created = upload(demo)
    assert created.status_code == 201, created.text
    asset = created.json()['data']
    assert asset['mime_type'] == 'image/png' and asset['size_bytes'] == len(PNG)
    assert asset['purpose'] == 'meal' and asset['duration_ms'] is None
    assert '/api/v1/media/' in asset['content_url'] and 'ticket=' in asset['content_url']
    stored = list((app.state.settings.data_dir / 'media').glob('*.png'))
    assert len(stored) == 1 and stored[0].read_bytes() == PNG
    # Same key + same bytes replays the original asset instead of storing twice.
    again = upload(demo, key='m-1')
    assert again.json()['data']['asset_id'] == asset['asset_id']
    assert len(list((app.state.settings.data_dir / 'media').glob('*.png'))) == 1
    # Same key with different bytes is an idempotency conflict.
    conflict = upload(demo, key='m-1', content=PNG + b'x')
    assert conflict.status_code == 409 and conflict.json()['error']['code'] == 'IDEMPOTENCY_CONFLICT'

def test_ticket_plays_without_bearer_and_bearer_still_works(demo):
    asset = upload(demo).json()['data']
    url = f"/api/v1/media/{asset['asset_id']}/content"
    streamed = demo.client.get(url, params={'ticket': ticket_of(asset['content_url'])})
    assert streamed.status_code == 200
    assert streamed.content == PNG
    assert streamed.headers['content-type'].startswith('image/png')
    with_bearer = demo.client.get(url, headers=demo.elder)
    assert with_bearer.status_code == 200 and with_bearer.content == PNG

def test_bad_expired_or_missing_tickets_are_refused(demo, env):
    app, client, clock, seed = env
    asset = upload(demo).json()['data']
    url = f"/api/v1/media/{asset['asset_id']}/content"
    ticket = ticket_of(asset['content_url'])
    assert demo.client.get(url).status_code == 401
    tampered = ticket[:-1] + ('0' if ticket[-1] != '0' else '1')
    assert demo.client.get(url, params={'ticket': tampered}).status_code == 404
    clock.advance(seconds=301)
    assert demo.client.get(url, params={'ticket': ticket}).status_code == 404

def test_media_is_not_visible_to_an_unbound_child(demo, env):
    app, client, clock, seed = env
    from conftest import auth_header
    unbound = auth_header(client, seed['unbound_child']['phone'], 'child')
    asset = upload(demo).json()['data']
    assert client.get(f"/api/v1/media/{asset['asset_id']}", headers=unbound).status_code == 404
    assert client.get(f"/api/v1/media/{asset['asset_id']}/content", headers=unbound).status_code == 404

def test_quotas_and_mime_are_enforced(demo):
    too_large = upload(demo, key='big', content=b'\x00' * (10 * 1024 * 1024 + 1))
    assert too_large.status_code == 413 and too_large.json()['error']['code'] == 'MEDIA_TOO_LARGE'
    wrong_type = upload(demo, key='pdf', filename='x.pdf', mime='application/pdf', content=b'%PDF-1.4')
    assert wrong_type.status_code == 415 and wrong_type.json()['error']['code'] == 'MEDIA_UNSUPPORTED'
    empty = upload(demo, key='empty', content=b'')
    assert empty.status_code == 422

def test_audio_upload_and_resigned_asset_url(demo):
    audio = upload(demo, key='voice', purpose='voice_message', mime='audio/mpeg', filename='voice.mp3', content=b'ID3' + b'\x00' * 32)
    assert audio.status_code == 201, audio.text
    asset = audio.json()['data']
    assert asset['mime_type'] == 'audio/mpeg' and asset['purpose'] == 'voice_message'
    refreshed = demo.client.get(f"/api/v1/media/{asset['asset_id']}", headers=demo.elder)
    assert refreshed.status_code == 200
    assert refreshed.json()['data']['asset_id'] == asset['asset_id']
    assert refreshed.json()['data']['content_url'] != asset['content_url'] or refreshed.json()['data']['expires_at']
