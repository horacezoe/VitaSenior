"""HTTP substitutes by default. Test PCM is not evidence of synthesized speech.

Only test_live_tts_and_media_round_trip can incur a charge, and requires an
explicit VITASENIOR_LIVE_TTS=1 plus local MiMo credentials/configuration.
"""
import asyncio
import base64
import hashlib
import io
import json
import os
import struct
import time
import wave
from datetime import datetime, timezone
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
    assert caught.value.status == 422 and caught.value.code == "VALIDATION_ERROR"
    assert calls == []
    if len(text) > 200:
        assert caught.value.details == {"max_chars": 200, "actual_chars": 201}


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


def test_optional_audio_format_and_exact_transcript_are_accepted():
    body = audio_response(pcm_wav()).json()
    body["choices"][0]["message"]["audio"].update(format="wav", transcript=TEXT)
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


@pytest.mark.skipif(os.getenv("VITASENIOR_LIVE_TTS") != "1", reason="Paid TTS is opt-in: VITASENIOR_LIVE_TTS=1")
def test_live_tts_and_media_round_trip(tmp_path):
    required = ["MIMO_API_KEY", "MIMO_TTS_MODEL", "MIMO_TTS_VOICE"]
    if any(not os.getenv(name) for name in required):
        pytest.skip("Live TTS not run: local key/model/voice missing")
    text = os.getenv("VITASENIOR_LIVE_TTS_TEXT") or (
        "您好，这是银龄健康助手的新语音测试。请先查看页面上的完整文字，再听这段语音。测试时间："
        + datetime.now(timezone.utc).strftime("%Y年%m月%d日%H时%M分%S秒") + "。")
    provider = MiMoTTS(api_key=os.environ[required[0]], model=os.environ[required[1]],
                      voice=os.environ[required[2]])
    started = time.monotonic()
    speech = provider.synthesize(text)  # Exactly one paid request, no automatic retry.
    elapsed = time.monotonic() - started
    assert speech.text == text and speech.is_mock is False
    assert_media_round_trip(speech, tmp_path)
    output = tmp_path / "live-tts.wav"
    output.write_bytes(speech.content)
    evidence = {"provider": provider.name, "is_mock": speech.is_mock, "model": provider.model,
                "voice": provider.voice, "text": text, "mime_type": speech.mime_type,
                "size_bytes": len(speech.content), "duration_ms": speech.duration_ms,
                "elapsed_seconds": round(elapsed, 3), "sha256": hashlib.sha256(speech.content).hexdigest(),
                "generated_at": datetime.now(timezone.utc).isoformat(), "listened": False,
                "scope": "direct provider + existing MediaPort/MEDIA03; AI02/Agent not wired"}
    (tmp_path / "live-tts.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print("LIVE_TTS_OK", json.dumps({"audio": str(output), **evidence}, ensure_ascii=False))
