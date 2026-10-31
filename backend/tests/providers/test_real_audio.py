"""HTTP substitutes by default. Test PCM is not evidence of synthesized speech.

Real requests live only in the explicit standalone probe_real_tts.py script.
"""
import asyncio
import base64
import io
import json
import struct
import wave
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient

from app.contracts.ports import MediaPort
from app.core.config import Settings
from app.core.errors import AppError
from app.core.uow import UnitOfWork
from app.main import create_app
from app.providers.mock_audio import Speech, TTSProvider
from app.providers.real_audio import MiMoTTS, MiMoASR
from app.seed import framework_seed
from app.contracts.context import Actor
from app.schemas.enums import Role
from app.providers.real_tts import MiMoTTS as ConfiguredMiMoTTS, build


TEXT = "您好，这是新生成的中文短回复。请先阅读页面上的完整文字，再播放语音。"
MODEL = MiMoTTS.MODEL
VOICE = "冰糖"
KEY = "test-only-not-a-real-key"


def pcm_wav(*, rate=24_000, channels=1, width=2, frames=2400, silent=False):
    stream = io.BytesIO()
    with wave.open(stream, "wb") as writer:
        writer.setparams((channels, width, rate, 0, "NONE", "not compressed"))
        # Diagnostic test data only, never returned by the production adapter.
        writer.writeframes((b"\x00" if silent else b"\x10") * frames * channels * width)
    return stream.getvalue()


def adapter(handler, **kwargs):
    return MiMoTTS(api_key=KEY, model=MODEL, voice=VOICE,
                   transport=httpx.MockTransport(handler), **kwargs)


def audio_response(raw, *, headers=None):
    return httpx.Response(200, json={"model": MODEL, "choices": [{"index": 0, "finish_reason": "stop",
           "message": {"role": "assistant", "audio": {"data": base64.b64encode(raw).decode("ascii")}}}]},
           headers=headers)


def test_new_chinese_text_is_sent_whole_and_speech_metadata_is_real():
    audio, requests = pcm_wav(), []

    def handler(request):
        requests.append(request)
        assert str(request.url) == MiMoTTS.ENDPOINT
        assert request.method == "POST"
        assert request.headers["api-key"] == KEY
        assert "authorization" not in request.headers
        assert request.headers["accept"] == "application/json"
        payload = json.loads(request.content)
        assert payload == {"model": MODEL, "messages": [{"role": "assistant", "content": texts[len(requests) - 1]}],
                           "audio": {"format": "wav", "voice": VOICE}, "stream": False}
        assert request.extensions["timeout"]["connect"] == 5
        return audio_response(audio)

    provider: TTSProvider = adapter(handler)
    texts = ["  " + TEXT + "\n", "这是另一条刚刚写下的中文回复，不能使用固定样例替代。"]
    for text in texts:
        speech = provider.synthesize(text, VOICE)
        assert isinstance(speech, Speech)
        assert speech.text == text and speech.content == audio
        assert speech.mime_type == "audio/wav" and speech.duration_ms == 100
        assert speech.is_mock is False
    assert provider.name == "mimo" and provider.is_mock is False
    assert len(requests) == 2


@pytest.mark.parametrize("text", ["", " \n\t", "文字\x00内容", "中" * 201])
def test_invalid_or_long_text_never_calls_or_truncates(text):
    calls = []
    provider = adapter(lambda request: calls.append(request))
    with pytest.raises(AppError) as caught:
        provider.synthesize(text)
    assert calls == []
    if len(text) > 200:
        assert caught.value.status == 502 and caught.value.code == "PROVIDER_ERROR"
        assert caught.value.details == {"provider": "mimo", "reason": "text_too_long", "max_chars": 200, "actual_chars": 201}
    else:
        assert caught.value.status == 422 and caught.value.code == "VALIDATION_ERROR"


def test_text_at_demo_limit_is_sent_without_truncation_and_voice_override_is_rejected():
    calls = []

    def handler(request):
        calls.append(json.loads(request.content))
        return audio_response(pcm_wav())

    provider = adapter(handler)
    text = "中" * 200
    assert provider.synthesize(text).text == text
    assert calls[0]["messages"] == [{"role": "assistant", "content": text}]
    with pytest.raises(AppError) as caught:
        provider.synthesize(TEXT, "茉莉")
    assert caught.value.status == 422 and len(calls) == 1


@pytest.mark.parametrize("status,expected,reason,retryable", [
    (400, 502, "request_rejected", False),
    (401, 502, "authentication", False), (403, 502, "authentication", False),
    (429, 502, "rate_limited", True), (500, 502, "upstream_error", True),
    (503, 502, "upstream_error", True), (504, 504, "upstream_timeout", True),
    (408, 504, "upstream_timeout", True), (302, 502, "request_rejected", False),
])
def test_upstream_errors_are_safe_retry_metadata_without_automatic_retry(status, expected, reason, retryable):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, text=KEY + TEXT,
                              headers={"location": "https://untrusted.invalid/steal"})

    with pytest.raises(AppError) as caught:
        adapter(handler).synthesize(TEXT)
    error = caught.value
    assert error.status == expected
    assert error.code == ("PROVIDER_TIMEOUT" if expected == 504 else "PROVIDER_ERROR")
    assert error.retryable is retryable
    assert error.details == {"provider": "mimo", "reason": reason, "upstream_status": status}
    assert KEY not in str(error) + str(error.details) and TEXT not in str(error) + str(error.details)
    assert len(calls) == 1


@pytest.mark.parametrize("exception,status", [
    (httpx.ConnectTimeout, 504), (httpx.ReadTimeout, 504), (httpx.WriteTimeout, 504),
    (httpx.PoolTimeout, 504), (httpx.ConnectError, 502), (httpx.RemoteProtocolError, 502),
])
def test_transport_errors_and_timeouts_are_provider_errors(exception, status):
    calls = []

    def handler(request):
        calls.append(request)
        raise exception(KEY + TEXT, request=request)

    with pytest.raises(AppError) as caught:
        adapter(handler).synthesize(TEXT)
    assert caught.value.status == status and caught.value.retryable
    assert KEY not in str(caught.value) and TEXT not in str(caught.value)
    assert len(calls) == 1


def test_absolute_deadline_cancels_a_slow_response_not_just_each_read():
    class SlowStream(httpx.AsyncByteStream):
        closed = False
        cancelled = False

        async def __aiter__(self):
            try:
                body = audio_response(pcm_wav()).content
                for chunk in [body[:50], body[50:]]:
                    await asyncio.sleep(0.04)
                    yield chunk
            except asyncio.CancelledError:
                self.cancelled = True
                raise

        async def aclose(self):
            self.closed = True

    stream = SlowStream()
    provider = adapter(lambda request: httpx.Response(200, stream=stream, headers={"content-type": "application/json"}),
                       timeout_seconds=0.06, connect_timeout_seconds=0.02)
    with pytest.raises(AppError) as caught:
        provider.synthesize(TEXT)
    assert caught.value.status == 504 and stream.cancelled and stream.closed


def test_absolute_deadline_also_cancels_before_response_headers():
    cancelled = []

    async def handler(request):
        try:
            await asyncio.sleep(1)
        finally:
            cancelled.append(True)

    with pytest.raises(AppError) as caught:
        adapter(handler, timeout_seconds=0.02, connect_timeout_seconds=0.01).synthesize(TEXT)
    assert caught.value.status == 504 and cancelled == [True]


@pytest.mark.parametrize("raw", [
    b"", b"not audio", b'{"error":"failed"}', b"<html>error</html>",
    pcm_wav()[:-2], pcm_wav() + b"garbage", pcm_wav(frames=0), pcm_wav(silent=True),
    pcm_wav(rate=16_000), pcm_wav(width=1), pcm_wav(channels=3),
], ids=["empty", "plain-bytes", "json", "html", "truncated",
        "trailing-junk", "zero-frames", "silent", "wrong-rate", "wrong-width", "three-channels"])
def test_empty_truncated_and_invalid_audio_is_never_returned(raw):
    with pytest.raises(AppError) as caught:
        adapter(lambda request: audio_response(raw)).synthesize(TEXT)
    assert caught.value.status == 502 and caught.value.code == "PROVIDER_ERROR"


@pytest.mark.parametrize("mime", ["application/json", "application/json; charset=utf-8"])
def test_json_audio_is_decoded_and_wav_mime_is_based_on_bytes(mime):
    audio = pcm_wav(channels=2)
    result = adapter(lambda request: audio_response(audio, headers={"content-type": mime})).synthesize(TEXT)
    assert result.content == audio and result.mime_type == "audio/wav" and result.duration_ms == 100


@pytest.mark.parametrize("mime", ["", "text/html", "audio/wav", "application/octet-stream", "text/event-stream"])
def test_non_json_success_response_cannot_be_mistaken_for_mimo_audio(mime):
    with pytest.raises(AppError) as caught:
        adapter(lambda request: audio_response(pcm_wav(), headers={"content-type": mime})).synthesize(TEXT)
    assert caught.value.status == 502 and caught.value.details["reason"] == "invalid_response_type"


@pytest.mark.parametrize("body", [b"", b'{"choices":', b"\xff\xfe", b"<html>failure</html>"])
def test_invalid_json_is_a_safe_provider_failure(body):
    with pytest.raises(AppError) as caught:
        adapter(lambda request: httpx.Response(200, content=body,
                headers={"content-type": "application/json"})).synthesize(TEXT)
    assert caught.value.status == 502 and caught.value.details["reason"] == "invalid_json"


@pytest.mark.parametrize("body", [None, [], "wrong-shape", {}, {"error": {"message": KEY}},
    {"choices": []}, {"choices": {}}, {"choices": [None]}, {"choices": [{}, {}]}])
def test_json_error_or_missing_single_choice_never_returns_speech(body):
    with pytest.raises(AppError) as caught:
        adapter(lambda request: httpx.Response(200, content=json.dumps(body),
                headers={"content-type": "application/json"})).synthesize(TEXT)
    assert caught.value.status == 502 and caught.value.details["reason"] == "invalid_response"
    assert KEY not in str(caught.value) + str(caught.value.details)


@pytest.mark.parametrize("reason", ["length", "content_filter", "repetition_truncation", "tool_calls", None, "unknown"])
def test_valid_wav_with_unfinished_or_truncated_generation_is_rejected(reason):
    body = audio_response(pcm_wav()).json()
    body["choices"][0]["finish_reason"] = reason
    with pytest.raises(AppError) as caught:
        adapter(lambda request: httpx.Response(200, json=body)).synthesize(TEXT)
    assert caught.value.details["reason"] == "incomplete_generation"


@pytest.mark.parametrize("message", [None, [], {"role": "user"}, {"role": "assistant"},
                                      {"role": "assistant", "audio": "not-an-object"}])
def test_missing_or_invalid_audio_message_fails(message):
    body = audio_response(pcm_wav()).json()
    body["choices"][0]["message"] = message
    with pytest.raises(AppError) as caught:
        adapter(lambda request: httpx.Response(200, json=body)).synthesize(TEXT)
    assert caught.value.status == 502


@pytest.mark.parametrize("encoded", [None, 123, "", "not valid base64!", "中文", "YQ", "data:audio/wav;base64,YQ=="])
def test_missing_or_invalid_base64_fails(encoded):
    body = audio_response(pcm_wav()).json()
    body["choices"][0]["message"]["audio"]["data"] = encoded
    with pytest.raises(AppError) as caught:
        adapter(lambda request: httpx.Response(200, json=body)).synthesize(TEXT)
    assert caught.value.status == 502


@pytest.mark.parametrize("change", ["model", "format", "transcript"])
def test_wrong_model_format_or_advertised_transcript_is_rejected(change):
    body = audio_response(pcm_wav()).json()
    if change == "model":
        body["model"] = "mimo-v2.6-flash"
    else:
        body["choices"][0]["message"]["audio"][change] = "mp3" if change == "format" else "不同的文字"
    with pytest.raises(AppError) as caught:
        adapter(lambda request: httpx.Response(200, json=body)).synthesize(TEXT)
    assert caught.value.status == 502


@pytest.mark.parametrize("transcript", [TEXT, None])
def test_optional_audio_format_and_exact_or_null_transcript_are_accepted(transcript):
    body = audio_response(pcm_wav()).json()
    body["choices"][0]["message"]["audio"].update(format="wav", transcript=transcript)
    assert adapter(lambda request: httpx.Response(200, json=body)).synthesize(TEXT).text == TEXT


@pytest.mark.parametrize("change", ["riff_size", "data_size", "byte_rate", "block_align", "partial_frame", "long"])
def test_structurally_inconsistent_wav_and_excess_duration_fail(change):
    raw = bytearray(pcm_wav(frames=24_000 * 120 + 1) if change == "long" else pcm_wav())
    if change == "riff_size":
        struct.pack_into("<I", raw, 4, 1)
    elif change == "data_size":
        struct.pack_into("<I", raw, 40, len(raw))
    elif change == "byte_rate":
        struct.pack_into("<I", raw, 28, 1)
    elif change == "block_align":
        struct.pack_into("<H", raw, 32, 1)
    elif change == "partial_frame":
        struct.pack_into("<I", raw, 40, len(raw) - 45)
    with pytest.raises(AppError) as caught:
        adapter(lambda request: audio_response(bytes(raw))).synthesize(TEXT)
    assert caught.value.status == 502 and caught.value.details["reason"] == "invalid_audio"


@pytest.mark.parametrize("length", ["-1", "invalid", "0", str(MiMoTTS.MAX_RESPONSE_BYTES + 1), "100"])
def test_incorrect_content_length_is_rejected(length):
    with pytest.raises(AppError) as caught:
        adapter(lambda request: audio_response(pcm_wav(), headers={"content-length": length})).synthesize(TEXT)
    assert caught.value.status == 502


def test_unannounced_oversize_body_is_stopped_and_stream_closed():
    class LargeStream(httpx.AsyncByteStream):
        closed = False
        chunks_sent = 0

        async def __aiter__(self):
            for _ in range(24):
                self.chunks_sent += 1
                yield b"x" * 1024 * 1024

        async def aclose(self):
            self.closed = True

    stream = LargeStream()
    with pytest.raises(AppError) as caught:
        adapter(lambda request: httpx.Response(200, stream=stream, headers={"content-type": "application/json"})).synthesize(TEXT)
    assert caught.value.details["reason"] == "invalid_response_size"
    assert stream.closed and stream.chunks_sent == 21


def test_encoded_body_is_rejected_before_decompression():
    with pytest.raises(AppError) as caught:
        adapter(lambda request: httpx.Response(200, stream=httpx.ByteStream(b"bad gzip"),
                headers={"content-type": "application/json", "content-encoding": "gzip"})).synthesize(TEXT)
    assert caught.value.status == 502 and caught.value.details["reason"] == "invalid_audio_encoding"


@pytest.mark.parametrize("overrides", [
    {"api_key": ""}, {"api_key": " \n"}, {"api_key": "key\nheader"}, {"api_key": "密钥"},
    {"model": ""}, {"model": "unknown"}, {"model": "mimo-v2-tts"}, {"model": "mimo-v2.5-tts-voiceclone"},
    {"voice": ""}, {"voice": "unknown"},
    {"timeout_seconds": 0}, {"timeout_seconds": 21}, {"timeout_seconds": float("inf")},
    {"connect_timeout_seconds": 6}, {"connect_timeout_seconds": float("nan")},
])
def test_missing_or_unsupported_configuration_fails_without_network(overrides):
    config = {"api_key": KEY, "model": MODEL, "voice": VOICE, **overrides}
    with pytest.raises(ValueError):
        MiMoTTS(**config)


def assert_media_round_trip(speech, tmp_path, *, provider_handler=None):
    """Use production assembly's MediaPort and ticket HTTP route, no AI wiring."""
    settings = Settings(data_dir=tmp_path / "data", database_url=None, scanner_enabled=False,
                        public_base_url="http://testserver")
    app = create_app(settings)
    with TestClient(app) as client:
        seed = framework_seed(app.state.sessions, app.state.clock)
        actor = Actor(seed["elder"]["user_id"], Role("elder"))
        media: MediaPort = app.state.services.media
        if provider_handler is not None:
            # If synthesis retained BEGIN IMMEDIATE, this independent writer
            # would block/fail. There is no substitute media implementation.
            def writable_handler(request):
                with UnitOfWork(app.state.sessions) as unit:
                    unit.session.connection().exec_driver_sql("SELECT 1")
                    unit.commit()
                return provider_handler(request)
            speech = adapter(writable_handler).synthesize(TEXT)
        with UnitOfWork(app.state.sessions) as unit:
            asset = media.register_generated(unit.session, actor, seed["elder"]["elder_id"],
                    content=speech.content, mime_type=speech.mime_type,
                    purpose="agent_audio", duration_ms=speech.duration_ms)
            unit.commit()
        fetched = client.get(asset.content_url)
        assert fetched.status_code == 200 and fetched.content == speech.content
        assert fetched.headers["content-type"] == "audio/wav"
        assert asset.size_bytes == len(speech.content) and asset.duration_ms == speech.duration_ms
        ticket = parse_qs(urlsplit(asset.content_url).query)["ticket"][0]
        with UnitOfWork(app.state.sessions, write=False) as unit:
            handle = media.open_content(unit.session, None, asset.asset_id, ticket=ticket)
            outsider = Actor(seed["stranger_elder"]["user_id"], Role("elder"))
            with pytest.raises(AppError) as caught:
                media.get_asset(unit.session, outsider, asset.asset_id)
            assert caught.value.status == 404
        assert handle.path.read_bytes() == speech.content
        assert client.get(urlsplit(asset.content_url).path).status_code == 401
        assert client.get(asset.content_url + "tampered").status_code == 404
    return speech


def test_speech_registers_through_existing_media_port_and_ticket_returns_all_bytes(tmp_path):
    audio = pcm_wav()
    speech = assert_media_round_trip(None, tmp_path, provider_handler=lambda request:
             audio_response(audio))
    assert speech.content == audio and speech.is_mock is False


def test_frozen_build_handshake_has_real_name_default_voice_and_timeout():
    provider = build(Settings(tts_provider="real", tts_api_key=KEY,
                     tts_base_url="https://api.xiaomimimo.com/v1/", tts_model=MODEL,
                     tts_timeout_seconds=0.5))
    assert isinstance(provider, ConfiguredMiMoTTS)
    assert provider.name == "real" and provider.is_mock is False
    assert provider.voice == "mimo_default" and provider.timeout_seconds == 0.5
    assert provider.connect_timeout_seconds == 0.5


@pytest.mark.parametrize("url", ["http://api.xiaomimimo.com/v1", "https://untrusted.invalid/v1",
                                "https://api.xiaomimimo.com/v1?key=secret"])
def test_build_rejects_wrong_endpoint_without_sending_credentials(url):
    with pytest.raises(ValueError, match="official HTTPS API root"):
        build(Settings(tts_provider="real", tts_api_key=KEY, tts_model=MODEL, tts_base_url=url))


@pytest.fixture
def configured_audio(monkeypatch, tmp_path):
    for name, value in {"DATA_DIR": str(tmp_path / "configured"), "SCANNER_ENABLED": "false",
                        "CHAT_PROVIDER": "mock", "ASR_PROVIDER": "mock", "TTS_PROVIDER": "real",
                        "TTS_API_KEY": KEY, "TTS_BASE_URL": "https://api.xiaomimimo.com/v1",
                        "TTS_MODEL": MODEL, "TTS_VOICE": VOICE,
                        "PUBLIC_BASE_URL": "http://testserver"}.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    app = create_app()  # Actual Settings, main and A factory, no provider injection.
    assert isinstance(app.state.agent_tts, ConfiguredMiMoTTS)
    with TestClient(app, raise_server_exceptions=False) as client:
        seed = framework_seed(app.state.sessions, app.state.clock)
        tokens = {}
        for name in ["elder", "unbound_child"]:
            account = {key: seed[name][key] for key in ["phone", "role"]}
            challenge = client.post("/api/v1/auth/code", json=account).json()["data"]["challenge_id"]
            result = client.post("/api/v1/auth/login", json={**account, "challenge_id": challenge, "code": "123456"})
            assert result.status_code == 200
            tokens[name] = {"Authorization": "Bearer " + result.json()["data"]["access_token"]}
        yield app, client, seed, tokens, monkeypatch


def test_actual_factory_runtime_ai02_and_media_bytes(configured_audio):
    app, client, seed, tokens, _ = configured_audio
    calls, audio = [], pcm_wav()

    def handler(request):
        calls.append(request)
        with UnitOfWork(app.state.sessions) as unit:
            unit.session.connection().exec_driver_sql("SELECT 1")
            unit.commit()  # The real AI02 flow did not retain a database write lock.
        return audio_response(audio)

    app.state.agent_tts._transport = httpx.MockTransport(handler)
    runtime = client.get("/api/v1/runtime", headers=tokens["elder"])
    assert runtime.json()["data"]["providers"] == {"chat": "mock", "asr": "mock", "tts": "real"}
    dashboard = client.get(f'/api/v1/elders/{seed["elder"]["elder_id"]}/dashboard', headers=tokens["elder"])
    assert dashboard.json()["data"]["provider_mode"] == "mock"
    result = client.post("/api/v1/ai/tts", headers=tokens["elder"],
                         json={"elder_id": seed["elder"]["elder_id"], "text": TEXT})
    assert result.status_code == 200, result.text
    body = result.json()["data"]
    assert body["provider"] == "real" and body["is_mock"] is False
    asset = body["audio_asset"]
    assert asset["duration_ms"] == 100 and asset["mime_type"] == "audio/wav"
    fetched = client.get(asset["content_url"])
    assert fetched.status_code == 200 and fetched.content == audio
    assert fetched.headers["content-type"] == "audio/wav" and len(calls) == 1


@pytest.mark.parametrize("account,status", [(None, 401), ("unbound_child", 403)])
def test_ai02_access_is_checked_before_paid_transport(configured_audio, account, status):
    app, client, seed, tokens, _ = configured_audio
    calls = []
    app.state.agent_tts._transport = httpx.MockTransport(lambda request: calls.append(request))
    result = client.post("/api/v1/ai/tts", headers=tokens[account] if account else {},
                         json={"elder_id": seed["elder"]["elder_id"], "text": TEXT})
    assert result.status_code == status and calls == []


@pytest.fixture
def family_audio(configured_audio):
    app, client, seed, tokens, _ = configured_audio
    account = {key: seed["bound_child"][key] for key in ("phone", "role")}
    challenge = client.post("/api/v1/auth/code", json=account).json()["data"]["challenge_id"]
    login = client.post("/api/v1/auth/login", json={**account, "challenge_id": challenge, "code": "123456"})
    assert login.status_code == 200, login.text
    tokens["bound_child"] = {"Authorization": "Bearer " + login.json()["data"]["access_token"]}
    return app, client, seed["elder"]["elder_id"], tokens


def test_new_family_text_has_real_audio_playback_and_free_idempotent_replay(family_audio):
    app, client, elder, tokens = family_audio
    text, calls, audio = "妈妈，周日下午三点我们来看您，这是刚写的新关怀消息。", [], pcm_wav()

    def handler(request):
        calls.append(request)
        assert json.loads(request.content)["messages"][0]["content"] == text
        with UnitOfWork(app.state.sessions) as unit:
            unit.commit()  # The billable call holds no write lock.
        return audio_response(audio)

    app.state.agent_tts._transport = httpx.MockTransport(handler)
    url = f"/api/v1/elders/{elder}/family-reminders"
    headers = {**tokens["bound_child"], "Idempotency-Key": "new-family-text"}
    body = {"category": "general", "text": text}
    response = client.post(url, headers=headers, json=body)
    assert response.status_code == 201, response.text
    notice = response.json()["data"]
    assert notice["text"] == text and notice["audio_asset_id"] and "暂不可用" not in notice["title"]
    asset = client.get(f'/api/v1/media/{notice["audio_asset_id"]}', headers=tokens["elder"]).json()["data"]
    fetched = client.get(asset["content_url"])
    assert fetched.content == audio and fetched.headers["content-type"] == "audio/wav"
    assert client.post(url, headers=headers, json=body).json()["data"] == notice
    assert client.post(url, headers=headers, json={**body, "text": "换了一条文字"}).status_code == 409
    assert len(calls) == 1
    visible = client.post(f"/api/v1/elders/{elder}/presence", headers=tokens["elder"],
        json={"client_id": "family-player", "visible": True})
    assert visible.status_code == 200
    for kind in ("displayed", "answered", "playback_completed"):
        event = client.post(f'/api/v1/notifications/{notice["notification_id"]}/events',
            headers={**tokens["elder"], "Idempotency-Key": kind}, json={"event_id": kind, "event_type": kind})
        assert event.status_code == 200, event.text
    assert event.json()["data"]["notification"]["delivery_state"] == "played"


@pytest.mark.parametrize("mode", ["timeout", "invalid_audio", "long_text"])
def test_family_speech_failure_sends_full_text_with_explicit_fallback(family_audio, mode):
    app, client, elder, tokens = family_audio
    text = "中" * 201 if mode == "long_text" else "这段关怀消息在语音失败时仍应完整保存。"
    calls = []

    def handler(request):
        calls.append(request)
        if mode == "timeout":
            raise httpx.ReadTimeout("substitute timeout", request=request)
        return audio_response(b"invalid-wav")

    app.state.agent_tts._transport = httpx.MockTransport(handler)
    headers = {**tokens["bound_child"], "Idempotency-Key": "family-fallback"}
    url, body = f"/api/v1/elders/{elder}/family-reminders", {"category": "general", "text": text}
    result = client.post(url, headers=headers, json=body)
    assert result.status_code == 201, result.text
    value = result.json()["data"]
    assert value["text"] == text and value["audio_asset_id"] is None
    assert "语音暂不可用" in value["title"]
    assert client.post(url, headers=headers, json=body).json()["data"] == value
    assert len(calls) == (0 if mode == "long_text" else 1)


@pytest.mark.parametrize("account,status", [(None, 401), ("elder", 403), ("unbound_child", 403)])
def test_family_access_denial_does_not_call_real_tts(family_audio, account, status):
    app, client, elder, tokens = family_audio
    calls = []
    app.state.agent_tts._transport = httpx.MockTransport(lambda request: calls.append(request))
    headers = {**(tokens[account] if account else {}), "Idempotency-Key": "denied-family"}
    result = client.post(f"/api/v1/elders/{elder}/family-reminders", headers=headers,
        json={"category": "general", "text": "这条消息不能由无权账号发送。"})
    assert result.status_code == status and not calls


@pytest.mark.parametrize("source", ["template", "recording"])
def test_real_mode_preserves_family_preset_and_uploaded_recording(family_audio, source):
    app, client, elder, tokens = family_audio
    calls = []
    app.state.agent_tts._transport = httpx.MockTransport(lambda request: (calls.append(request), audio_response(pcm_wav()))[1])
    headers = {**tokens["bound_child"], "Idempotency-Key": "family-source"}
    body = {"category": "general", "template_id": "general"}
    if source == "recording":
        upload = client.post("/api/v1/media", headers={**headers, "Idempotency-Key": "child-voice"},
            data={"purpose": "voice_message"}, files={"file": ("child.wav", pcm_wav(), "audio/wav")})
        assert upload.status_code == 201, upload.text
        body = {"category": "general", "text": "优先播放孩子自己的录音。",
                "audio_asset_id": upload.json()["data"]["asset_id"]}
    result = client.post(f"/api/v1/elders/{elder}/family-reminders", headers=headers, json=body)
    assert result.status_code == 201, result.text
    assert result.json()["data"]["audio_asset_id"]
    assert len(calls) == (1 if source == "template" else 0)


def test_a_proposal_wiring_uses_real_tts_and_waits_for_full_playback(family_audio):
    app, client, elder, tokens = family_audio
    calls = []

    def handler(request):
        text = json.loads(request.content)["messages"][0]["content"]
        calls.append(text)
        assert "下周二上午九点复查" in text and "【模拟】" not in text
        with UnitOfWork(app.state.sessions) as unit:
            unit.commit()
        return audio_response(pcm_wav())

    app.state.agent_tts._transport = httpx.MockTransport(handler)
    result = client.post(f"/api/v1/elders/{elder}/change-proposals",
        headers={**tokens["bound_child"], "Idempotency-Key": "real-proposal"},
        json={"target_type": "profile", "target_id": elder, "operation": "update", "base_version": 1,
              "patch": {"medical_notes": "下周二上午九点复查"}})
    assert result.status_code == 201, result.text
    value = result.json()["data"]
    assert value["status"] == "pending_notice" and value["auto_apply_at"] is None
    notices = client.get(f"/api/v1/elders/{elder}/notifications", headers=tokens["elder"]).json()["data"]["items"]
    notice = next(n for n in notices if n["proposal_id"] == value["proposal_id"])
    assert notice["text"] == calls[0] and notice["audio_asset_id"]


@pytest.mark.parametrize("mode", ["success", "timeout", "long_text"])
def test_agent_speech_real_provenance_and_text_degradation(configured_audio, mode):
    from dataclasses import replace
    from sqlalchemy import func, select
    from app.models.health import Checkin
    from app.models.identity import MediaAsset

    app, client, seed, tokens, monkeypatch = configured_audio
    calls = []

    def handler(request):
        calls.append(request)
        if mode == "timeout":
            raise httpx.ReadTimeout("substitute timeout", request=request)
        return audio_response(pcm_wav())

    app.state.agent_tts._transport = httpx.MockTransport(handler)
    if mode == "long_text":
        original = app.state.agent_chat.plan
        monkeypatch.setattr(app.state.agent_chat, "plan", lambda *args: replace(original(*args), reply="中" * 201))
    result = client.post("/api/v1/agent/turns", headers={**tokens["elder"], "Idempotency-Key": "audio-turn"},
                         json={"elder_id": seed["elder"]["elder_id"], "client_turn_id": "audio-turn",
                               "text": "这是我的演示午餐", "mock_fixture_id": "meal_lunch"})
    assert result.status_code == 201, result.text
    body = result.json()["data"]
    assert body["actions"][0]["status"] == "pending" and body["reply"]["text"]
    with app.state.sessions() as tx:
        assert tx.scalar(select(func.count()).select_from(Checkin)) == 0
        assert tx.scalar(select(func.count()).select_from(MediaAsset)) == (1 if mode == "success" else 0)
    if mode == "success":
        assert body["providers"]["tts"] == "real" and body["reply"]["audio_asset_id"]
        assert body["degraded"] == [] and len(calls) == 1
    else:
        assert body["reply"]["audio_asset_id"] is None and "tts_unavailable" in body["degraded"]
        if mode == "long_text":
            assert body["reply"]["text"] == "中" * 201 and calls == []
        else:
            assert len(calls) == 1


@pytest.mark.parametrize("payload,status", [({"text": "中" * 201}, 502),
                                           ({"text": TEXT, "voice_id": "unknown"}, 422)])
def test_ai02_invalid_voice_or_overlength_cannot_create_media(configured_audio, payload, status):
    app, client, seed, tokens, _ = configured_audio
    calls = []
    app.state.agent_tts._transport = httpx.MockTransport(lambda request: calls.append(request))
    result = client.post("/api/v1/ai/tts", headers=tokens["elder"],
                         json={"elder_id": seed["elder"]["elder_id"], **payload})
    assert result.status_code == status and calls == []


def test_mock_restart_after_real_tts_needs_no_key_and_retains_session(configured_audio):
    from app.providers.mock_audio import MockTTS
    _, _, _, tokens, monkeypatch = configured_audio
    monkeypatch.setenv("TTS_PROVIDER", "mock")
    for name in ["TTS_API_KEY", "TTS_BASE_URL", "TTS_MODEL", "TTS_VOICE"]:
        monkeypatch.delenv(name, raising=False)
    app = create_app()
    assert isinstance(app.state.agent_tts, MockTTS)
    with TestClient(app) as client:
        response = client.get("/api/v1/runtime", headers=tokens["elder"])
        assert response.status_code == 200 and response.json()["data"]["providers"]["tts"] == "mock"


def load_probe(filename="probe_real_tts.py"):
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("audio_probe_for_test", Path(__file__).with_name(filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_standalone_probe_refuses_unapproved_request_before_reading_env(monkeypatch):
    monkeypatch.delenv("LIVE_TTS", raising=False)
    with pytest.raises(SystemExit) as caught:
        load_probe().run(["--env-file", "this-file-must-not-be-read.env"])
    assert caught.value.code == 2


def test_standalone_probe_normal_factory_one_substitute_request_and_isolated_db(monkeypatch, tmp_path):
    import os
    from unittest.mock import patch

    probe = load_probe()
    probe.BACKEND = tmp_path / "backend"
    foreign = tmp_path / "must-not-use-data"
    local_env = tmp_path / ".env"
    local_env.write_text(f"TTS_API_KEY={KEY}\nTTS_BASE_URL=https://api.xiaomimimo.com/v1\n"
                         f"TTS_MODEL={MODEL}\nTTS_VOICE={VOICE}\nDATA_DIR={foreign}\n"
                         f"DATABASE_URL=sqlite:///{foreign}/must-not-open.sqlite3\n", encoding="utf-8")
    original = ConfiguredMiMoTTS.__init__
    calls = []

    def handler(request):
        calls.append(request)
        return audio_response(pcm_wav())

    def substituted_init(self, **kwargs):
        original(self, **kwargs, transport=httpx.MockTransport(handler))

    monkeypatch.setattr(ConfiguredMiMoTTS, "__init__", substituted_init)
    with patch.dict(os.environ):
        probe.run(["--env-file", str(local_env), "--live", "--text", TEXT])
    assert len(calls) == 1 and not foreign.exists()
    manifests = list(probe.BACKEND.glob("data/f2-audio-b/evidence/*/evidence.json"))
    assert len(manifests) == 1
    evidence = json.loads(manifests[0].read_text(encoding="utf-8"))
    assert evidence["provider"] == "real" and evidence["listened"] is False
    assert evidence["text"] == TEXT and evidence["mime_type"] == "audio/wav"
    assert KEY not in manifests[0].read_text(encoding="utf-8")


def asr_adapter(handler, **kwargs):
    return MiMoASR(api_key=KEY, base_url=MiMoASR.BASE_URL, model=MiMoASR.MODEL,
                   transport=httpx.MockTransport(handler), **kwargs)


def asr_response(text):
    return httpx.Response(200, json={"model": MiMoASR.MODEL, "choices": [{"finish_reason": "stop",
                          "message": {"role": "assistant", "content": text}}]})


def test_real_factory_wav_asr_camera_confirmation_and_final_speech(tmp_path):
    """Actual adapters and ports; HTTP bytes are substitutes, not microphone evidence."""
    from sqlalchemy import func, select
    from app.models.health import Checkin

    settings = Settings(data_dir=tmp_path / "three-real", database_url=None, scanner_enabled=False,
        public_base_url="http://testserver", chat_provider="real", chat_api_key=KEY,
        chat_base_url=MiMoASR.BASE_URL, chat_model="mimo-v2.6-flash",
        asr_provider="real", asr_api_key=KEY, asr_base_url=MiMoASR.BASE_URL, asr_model=MiMoASR.MODEL,
        tts_provider="real", tts_api_key=KEY, tts_base_url=MiMoASR.BASE_URL, tts_model=MODEL,
        tts_voice=VOICE)
    app = create_app(settings)
    recording, output = pcm_wav(rate=48_000, frames=4800), pcm_wav()
    calls, spoken = [], []

    def handler(request):
        payload = json.loads(request.content)
        model = payload["model"]
        calls.append(model)
        # ASR, understanding and TTS must all allow an independent writer.
        with UnitOfWork(app.state.sessions) as unit:
            unit.session.connection().exec_driver_sql("SELECT 1")
            unit.commit()
        if model == MiMoASR.MODEL:
            item = payload["messages"][0]["content"][0]["input_audio"]
            assert item["format"] == "wav"
            assert base64.b64decode(item["data"].split(",", 1)[1], validate=True) == recording
            return asr_response("确认。")
        if model == MODEL:
            spoken.append(payload["messages"][0]["content"])
            return audio_response(output)
        assert model == settings.chat_model
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {
            "content": json.dumps({"intent": "diet", "meal_slot": "lunch", "foods": ["青菜", "豆腐"],
                "food_groups": ["vegetable", "protein"], "reply": "请确认这次午餐。"}, ensure_ascii=False)}}]})

    for provider in (app.state.agent_chat, app.state.agent_asr, app.state.agent_tts):
        assert provider.name == "real" and not provider.is_mock
        provider._transport = httpx.MockTransport(handler)
    with TestClient(app) as client:
        seed = framework_seed(app.state.sessions, app.state.clock)
        tokens = {}
        for name in ("elder", "bound_child"):
            account = {key: seed[name][key] for key in ("phone", "role")}
            challenge = client.post("/api/v1/auth/code", json=account).json()["data"]["challenge_id"]
            login = client.post("/api/v1/auth/login", json={**account, "challenge_id": challenge, "code": "123456"})
            assert login.status_code == 200, login.text
            tokens[name] = {"Authorization": "Bearer " + login.json()["data"]["access_token"]}
        elder = seed["elder"]["elder_id"]

        def post(path, key, **kwargs):
            return client.post("/api/v1" + path,
                headers={**tokens["elder"], "Idempotency-Key": key}, **kwargs)

        runtime = client.get("/api/v1/runtime", headers=tokens["elder"]).json()["data"]
        assert runtime["providers"] == {"chat": "real", "asr": "real", "tts": "real"}
        prepared = post("/agent/turns", "prepare", json={"elder_id": elder, "client_turn_id": "prepare",
            "text": "今天午餐吃了青菜和豆腐，先让我核对再保存。"})
        assert prepared.status_code == 201, prepared.text
        pending = prepared.json()["data"]
        assert pending["actions"][0]["status"] == "pending"
        with app.state.sessions() as tx:
            assert tx.scalar(select(func.count()).select_from(Checkin)) == 0

        png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a5WQAAAAASUVORK5CYII=")
        image = post("/media", "frame", data={"purpose": "meal", "elder_id": elder},
            files={"file": ("frame.png", png, "image/png")})
        audio = post("/media", "recording", data={"purpose": "agent_audio", "elder_id": elder},
            files={"file": ("utterance.wav", recording, "audio/wav")})
        assert image.status_code == audio.status_code == 201
        body = {"elder_id": elder, "client_turn_id": "spoken-confirm",
            "conversation_id": pending["conversation_id"],
            "audio_asset_id": audio.json()["data"]["asset_id"],
            "image_asset_ids": [image.json()["data"]["asset_id"]],
            "context": {"pending_action_id": pending["actions"][0]["action_id"]}}
        confirmed = post("/agent/turns", "spoken-confirm", json=body)
        assert confirmed.status_code == 201, confirmed.text
        value = confirmed.json()["data"]
        assert value["transcript"] == "确认。" and value["providers"]["asr"] == "real"
        assert value["actions"][0]["status"] == "confirmed"
        assert calls.count(settings.chat_model) == calls.count(MiMoASR.MODEL) == 1
        before_replay = list(calls)
        replay = post("/agent/turns", "spoken-confirm", json=body)
        assert replay.status_code == 201 and replay.json()["data"] == value
        assert calls == before_replay  # No repeated paid calls or duplicate health facts.
        with app.state.sessions() as tx:
            assert tx.scalar(select(func.count()).select_from(Checkin)) == 1
            record = tx.scalar(select(Checkin))
            assert record.source == "agent_confirmed"
            record_id, day = record.id, record.local_date.isoformat()
        report = client.get(f"/api/v1/elders/{elder}/reports/daily?date={day}", headers=tokens["bound_child"])
        assert report.status_code == 200, report.text
        assert report.json()["data"]["records"]["diet"][0]["checkin_id"] == record_id
        dashboard = client.get(f"/api/v1/elders/{elder}/dashboard?date={day}", headers=tokens["bound_child"])
        assert dashboard.status_code == 200 and dashboard.json()["data"]["provider_mode"] == "real"

        # Execution may change reply.text. Supplement only the final text through AI02.
        final = post("/ai/tts", "final-speech", json={"elder_id": elder, "text": value["reply"]["text"]})
        assert final.status_code == 200, final.text
        speech = final.json()["data"]
        assert speech["provider"] == "real" and speech["is_mock"] is False
        assert spoken[-1] == value["reply"]["text"]
        fetched = client.get(speech["audio_asset"]["content_url"])
        assert fetched.status_code == 200 and fetched.content == output
        assert fetched.headers["content-type"] == "audio/wav"


def test_asr_new_recordings_use_supplier_output_not_fixed_transcript():
    audio = pcm_wav(rate=16000)
    changed = audio[:-2] + b"\x12\x34"
    requests = []
    outputs = ["今天午餐吃了青菜。", "这是一段新的录音内容。"]

    def handler(request):
        data = json.loads(request.content)
        index = len(requests)
        requests.append(request)
        assert str(request.url) == MiMoASR.BASE_URL + "/chat/completions"
        assert request.headers["api-key"] == KEY
        assert data["model"] == "mimo-v2.5-asr" and data["stream"] is False
        assert data["asr_options"] == {"language": "zh"}
        assert data["messages"][0]["role"] == "user"
        parts = data["messages"][0]["content"]
        assert len(parts) == 1 and parts[0]["type"] == "input_audio"
        assert parts[0]["input_audio"]["format"] == "wav"
        prefix, encoded = parts[0]["input_audio"]["data"].split(",", 1)
        assert prefix == "data:audio/wav;base64"
        assert base64.b64decode(encoded, validate=True) == [audio, changed][index]
        return asr_response(outputs[index])

    provider = asr_adapter(handler)
    for index, recording in enumerate([audio, changed]):
        result = provider.transcribe(recording, "audio/wav")
        assert result.transcript == outputs[index]
        assert result.provider == "real" and result.is_mock is False and result.language == "zh-CN"
    assert len(requests) == 2


@pytest.mark.parametrize("audio,mime,status", [
    (b"", "audio/wav", 422), (b"not-wave", "audio/wav", 415),
    (b"\x1a\x45\xdf\xa3webm", "audio/webm;codecs=opus", 415),
    (pcm_wav(), "audio/webm", 415), (pcm_wav()[:-2], "audio/wav", 415),
    (pcm_wav() + b"junk", "audio/wav", 415), (pcm_wav(width=1), "audio/wav", 415),
    (pcm_wav(frames=0), "audio/wav", 415),
], ids=["empty", "invalid", "native-webm", "mislabeled", "truncated", "trailing", "wrong-encoding", "no-frames"])
def test_asr_rejects_unsupported_or_incomplete_audio_before_network(audio, mime, status):
    requests = []
    with pytest.raises(AppError) as caught:
        asr_adapter(lambda request: requests.append(request)).transcribe(audio, mime)
    assert caught.value.status == status and requests == []


def test_asr_mock_fixture_and_size_duration_limits_never_call_supplier():
    requests = []
    provider = asr_adapter(lambda request: requests.append(request))
    with pytest.raises(AppError) as caught:
        provider.transcribe(pcm_wav(), "audio/wav", "known-mock-fixture")
    assert caught.value.status == 422
    with pytest.raises(AppError) as caught:
        provider.transcribe(b"x" * (MiMoASR.MAX_AUDIO_BYTES + 1), "audio/wav")
    assert caught.value.status == 413
    with pytest.raises(AppError) as caught:
        provider.transcribe(pcm_wav(rate=16000, frames=16000 * 61), "audio/wav")
    assert caught.value.status == 413 and requests == []


@pytest.mark.parametrize("status,expected,retryable", [
    (400, 502, False), (401, 502, False), (403, 502, False), (429, 502, True),
    (500, 502, True), (503, 502, True), (504, 504, True), (302, 502, False),
])
def test_asr_upstream_errors_no_leak_no_retry(status, expected, retryable):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, text=KEY, headers={"location": "https://untrusted.invalid"})

    with pytest.raises(AppError) as caught:
        asr_adapter(handler).transcribe(pcm_wav(), "audio/wav")
    assert caught.value.status == expected and caught.value.retryable is retryable
    assert caught.value.details["upstream_status"] == status
    assert KEY not in str(caught.value) + str(caught.value.details) and len(calls) == 1


@pytest.mark.parametrize("error,status", [(httpx.ReadTimeout, 504), (httpx.ConnectTimeout, 504),
                                         (httpx.ConnectError, 502), (httpx.RemoteProtocolError, 502)])
def test_asr_transport_failures_are_explicit(error, status):
    def handler(request):
        raise error(KEY, request=request)
    with pytest.raises(AppError) as caught:
        asr_adapter(handler).transcribe(pcm_wav(), "audio/wav")
    assert caught.value.status == status and KEY not in str(caught.value)


def test_asr_total_deadline_cancels_supplier_wait():
    cancelled = []
    async def handler(request):
        try:
            await asyncio.sleep(1)
        finally:
            cancelled.append(True)
    with pytest.raises(AppError) as caught:
        asr_adapter(handler, timeout_seconds=0.02, connect_timeout_seconds=0.01).transcribe(pcm_wav(), "audio/wav")
    assert caught.value.status == 504 and cancelled == [True]


@pytest.mark.parametrize("text,status", [(None, 502), ([], 502), ("", 422), (" \n", 422), ("a\x00b", 502)])
def test_asr_empty_invalid_transcript_does_not_return_fixed_sample(text, status):
    with pytest.raises(AppError) as caught:
        asr_adapter(lambda request: asr_response(text)).transcribe(pcm_wav(), "audio/wav")
    assert caught.value.status == status


@pytest.mark.parametrize("reason", ["length", "content_filter", None])
def test_asr_incomplete_transcript_fails(reason):
    body = asr_response("可能被截断的文字").json()
    body["choices"][0]["finish_reason"] = reason
    with pytest.raises(AppError) as caught:
        asr_adapter(lambda request: httpx.Response(200, json=body)).transcribe(pcm_wav(), "audio/wav")
    assert caught.value.details["reason"] == "incomplete_transcript"


@pytest.mark.parametrize("body", [None, {}, {"error": {"message": KEY}}, {"choices": []}])
def test_asr_malformed_response_never_succeeds(body):
    with pytest.raises(AppError) as caught:
        asr_adapter(lambda request: httpx.Response(200, content=json.dumps(body),
            headers={"content-type": "application/json"})).transcribe(pcm_wav(), "audio/wav")
    assert caught.value.status == 502 and KEY not in str(caught.value)


def test_asr_explicit_injection_into_existing_ai01_keeps_media_auth_and_releases_tx(configured_audio):
    # A's ASR factory switch is still pending. Injection is explicit and test-only.
    app, client, seed, tokens, _ = configured_audio
    calls = []
    def handler(request):
        calls.append(request)
        with UnitOfWork(app.state.sessions) as unit:
            unit.session.connection().exec_driver_sql("SELECT 1")
            unit.commit()
        return asr_response("今天午餐吃了青菜、豆腐和米饭，请帮我记录。")
    app.state.agent_asr = asr_adapter(handler)
    uploaded = client.post("/api/v1/media", headers={**tokens["elder"], "Idempotency-Key": "asr-upload"},
        data={"purpose": "agent_audio", "elder_id": seed["elder"]["elder_id"]},
        files={"file": ("recording.wav", pcm_wav(), "audio/wav")})
    assert uploaded.status_code == 201, uploaded.text
    body = {"elder_id": seed["elder"]["elder_id"], "audio_asset_id": uploaded.json()["data"]["asset_id"]}
    denied = client.post("/api/v1/ai/asr", headers=tokens["unbound_child"], json=body)
    assert denied.status_code == 403 and calls == []
    result = client.post("/api/v1/ai/asr", headers=tokens["elder"], json=body)
    assert result.status_code == 200, result.text
    assert result.json()["data"]["provider"] == "real" and result.json()["data"]["is_mock"] is False
    assert len(calls) == 1


def test_asr_probe_requires_live_opt_in_before_reading_any_file(monkeypatch):
    monkeypatch.delenv("LIVE_ASR", raising=False)
    with pytest.raises(SystemExit) as caught:
        load_probe("probe_real_asr.py").run(["--env-file", "must-not-read.env", "--audio", "must-not-read.wav"])
    assert caught.value.code == 2


def test_asr_probe_one_substitute_request_no_false_edge_acceptance(monkeypatch, tmp_path):
    import os
    from unittest.mock import patch
    probe = load_probe("probe_real_asr.py")
    probe.BACKEND = tmp_path
    audio_path = tmp_path / "sample.wav"
    audio_path.write_bytes(pcm_wav())
    local_env = tmp_path / ".env"
    local_env.write_text(f"TTS_API_KEY={KEY}\nTTS_BASE_URL={MiMoASR.BASE_URL}\n", encoding="utf-8")
    calls = []
    original = MiMoASR.__init__
    def handler(request):
        calls.append(request)
        return asr_response("这是 HTTP 替身返回的测试转写。")
    def substituted_init(self, **kwargs):
        original(self, **kwargs, transport=httpx.MockTransport(handler))
    monkeypatch.setattr(MiMoASR, "__init__", substituted_init)
    with patch.dict(os.environ):
        for field in ["ASR_API_KEY", "ASR_BASE_URL", "ASR_MODEL"]:
            os.environ.pop(field, None)
        probe.run(["--env-file", str(local_env), "--audio", str(audio_path), "--live"])
    assert len(calls) == 1
    manifest = next(tmp_path.glob("data/f2-audio-b/asr-evidence/*/evidence.json"))
    result = json.loads(manifest.read_text(encoding="utf-8"))
    assert result["transcript"] == "这是 HTTP 替身返回的测试转写。"
    assert result["provider"] == "real" and result["is_mock"] is False
    assert result["edge_capture_verified"] is False and KEY not in manifest.read_text(encoding="utf-8")


def test_voicedesign_uses_description_and_exact_text_without_preset_or_rewrite():
    def handler(request):
        body=json.loads(request.content)
        assert body['model']==MiMoTTS.DESIGN_MODEL
        assert body['messages']==[{'role':'user','content':MiMoTTS.BOY_VOICE},{'role':'assistant','content':TEXT}]
        assert body['audio']=={'format':'wav','optimize_text_preview':False}
        response=audio_response(pcm_wav()).json();response['model']=MiMoTTS.DESIGN_MODEL
        return httpx.Response(200,json=response)
    provider=MiMoTTS(api_key=KEY,model=MiMoTTS.DESIGN_MODEL,voice='mimo_default',transport=httpx.MockTransport(handler))
    assert provider.synthesize(TEXT).text==TEXT
