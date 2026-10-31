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
from app.providers.real_audio import MiMoTTS
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


def load_probe():
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("audio_probe_for_test", Path(__file__).with_name("probe_real_tts.py"))
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
