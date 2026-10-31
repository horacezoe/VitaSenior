"""Opt-in MiMo audio adapters; no database, media writes or fallback.

The public TTSProvider method remains synchronous. A owns configuration and
assembly; callers release their UoW before synthesis and register the returned
Speech through MediaPort afterwards. ASR's production assembly belongs to A.
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import io
import json
import math
import struct
import wave

import httpx

from app.core.errors import AppError
from app.providers.mock_audio import Speech, inspect_wav
from app.schemas.agent import ASRResult


class MiMoTTS:
    """MiMo-V2.5-TTS preset or VoiceDesign, complete PCM WAV only.

    ``transport`` is an HTTPX test seam, not an alternate production provider.
    No environment is read here and construction never makes a paid request.
    """

    name = "mimo"
    is_mock = False
    MODEL = "mimo-v2.5-tts"
    DESIGN_MODEL = "mimo-v2.5-tts-voicedesign"
    BOY_VOICE = "清澈温暖的小男孩声音，普通话发音清晰，亲切自然，语速稍慢，耐心陪伴老人，不尖锐、不夸张。"
    ENDPOINT = "https://api.xiaomimimo.com/v1/chat/completions"
    MAX_TEXT_CHARS = 200
    MAX_AUDIO_BYTES = 15 * 1024 * 1024
    MAX_BASE64_CHARS = 4 * ((MAX_AUDIO_BYTES + 2) // 3)
    MAX_RESPONSE_BYTES = MAX_BASE64_CHARS + 64 * 1024
    MAX_DURATION_MS = 120_000
    SAMPLE_RATE = 24_000
    VOICES = frozenset({"mimo_default", "冰糖", "茉莉", "苏打", "白桦", "Mia", "Chloe", "Milo", "Dean"})

    def __init__(
        self, *, api_key: str, model: str, voice: str,
        timeout_seconds: float = 20.0, connect_timeout_seconds: float = 5.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        if (not isinstance(api_key, str) or not api_key or not api_key.isascii()
                or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in api_key)):
            raise ValueError("MiMo TTS requires a non-empty ASCII API key without whitespace or controls")
        if model not in {self.MODEL, self.DESIGN_MODEL}:
            raise ValueError("This adapter supports mimo-v2.5-tts and mimo-v2.5-tts-voicedesign")
        if model == self.MODEL and voice not in self.VOICES:
            raise ValueError("Configure one MiMo-V2.5-TTS preset voice")
        if (not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 20
                or not math.isfinite(connect_timeout_seconds)
                or not 0 < connect_timeout_seconds <= min(5, timeout_seconds)):
            raise ValueError("TTS requires a total deadline <=20s and connect timeout <=5s")
        self._api_key = api_key
        self.model = model
        self.voice = (self.BOY_VOICE if voice in {"", "mimo_default", "冰糖"} else voice) if model == self.DESIGN_MODEL else voice
        self.timeout_seconds = timeout_seconds
        self.connect_timeout_seconds = connect_timeout_seconds
        self._transport = transport

    def synthesize(self, text: str, voice_id: str | None = None) -> Speech:
        if not isinstance(text, str) or not text.strip() or "\x00" in text:
            raise AppError(422, "VALIDATION_ERROR", "TTS requires non-blank text without NUL characters")
        if len(text) > self.MAX_TEXT_CHARS:
            # Never slice, chunk or read only a prefix while claiming full speech.
            error = self._error(502, "text_too_long")
            error.details.update(max_chars=self.MAX_TEXT_CHARS, actual_chars=len(text))
            raise error
        if voice_id is not None and voice_id != self.voice:
            raise AppError(422, "VALIDATION_ERROR", "Only the configured TTS voice is enabled")
        # FastAPI's existing sync routes run this method in a worker thread.
        # Async HTTP is local to this call so cancellation also bounds a slow
        # trickle response: HTTPX's per-read timeout alone is not a total limit.
        content = self._decode_audio(asyncio.run(self._request(text)), text)
        duration_ms = self._inspect_audio(content)
        return Speech(content=content, mime_type="audio/wav", duration_ms=duration_ms,
                      text=text, is_mock=False)

    def _error(self, status: int, reason: str, *, retryable: bool = False,
               upstream_status: int | None = None) -> AppError:
        details = {"provider": self.name, "reason": reason}
        if upstream_status is not None:
            details["upstream_status"] = upstream_status
        # No upstream body, key, request text or response headers in public errors.
        return AppError(status, "PROVIDER_TIMEOUT" if status == 504 else "PROVIDER_ERROR",
                        "TTS unavailable; retain the full text", details, retryable=retryable)

    async def _request(self, text: str) -> bytes:
        try:
            async with asyncio.timeout(self.timeout_seconds):
                async with httpx.AsyncClient(
                    transport=self._transport,
                    timeout=httpx.Timeout(self.timeout_seconds, connect=self.connect_timeout_seconds),
                    follow_redirects=False, trust_env=False,
                ) as client:
                    async with client.stream(
                        "POST", self.ENDPOINT,
                        headers={"api-key": self._api_key, "Accept": "application/json",
                                 "Accept-Encoding": "identity"},
                        json={"model": self.model, "messages": ([{"role": "user", "content": self.voice}] if self.model == self.DESIGN_MODEL else []) + [{"role": "assistant", "content": text}],
                              "audio": ({"format": "wav", "optimize_text_preview": False} if self.model == self.DESIGN_MODEL else {"format": "wav", "voice": self.voice}), "stream": False},
                    ) as response:
                        status = response.status_code
                        if status != 200:
                            reason = ("authentication" if status in {401, 403} else
                                      "rate_limited" if status == 429 else
                                      "upstream_timeout" if status in {408, 504} else
                                      "upstream_error" if status >= 500 else "request_rejected")
                            raise self._error(504 if status in {408, 504} else 502, reason,
                                              retryable=status in {408, 429} or status >= 500,
                                              upstream_status=status)
                        mime = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                        if mime != "application/json":
                            raise self._error(502, "invalid_response_type")
                        encoding = response.headers.get("content-encoding", "identity").strip().lower()
                        if encoding != "identity":
                            raise self._error(502, "invalid_audio_encoding")
                        length = response.headers.get("content-length")
                        expected = None
                        if length is not None:
                            if len(length) > 10 or not length.isascii() or not length.isdigit():
                                raise self._error(502, "invalid_content_length")
                            expected = int(length)
                            if not 0 < expected <= self.MAX_RESPONSE_BYTES:
                                raise self._error(502, "invalid_response_size")
                        raw = bytearray()
                        async for chunk in response.aiter_bytes():
                            if len(raw) + len(chunk) > self.MAX_RESPONSE_BYTES:
                                raise self._error(502, "invalid_response_size")
                            raw.extend(chunk)
                        if expected is not None and len(raw) != expected:
                            raise self._error(502, "incomplete_audio")
                        return bytes(raw)
        except (TimeoutError, httpx.TimeoutException):
            raise self._error(504, "timeout", retryable=True) from None
        except httpx.HTTPError:
            raise self._error(502, "transport_error", retryable=True) from None

    def _decode_audio(self, raw: bytes, text: str) -> bytes:
        try:
            result = json.loads(raw)
        except (ValueError, UnicodeError, RecursionError):
            raise self._error(502, "invalid_json") from None
        if not isinstance(result, dict) or result.get("error") is not None:
            raise self._error(502, "invalid_response")
        if result.get("model", self.model) != self.model:
            raise self._error(502, "unexpected_model")
        choices = result.get("choices")
        if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
            raise self._error(502, "invalid_response")
        choice = choices[0]
        # Never accept a token-limited/filtered/unfinished response as full speech.
        if choice.get("finish_reason") != "stop":
            raise self._error(502, "incomplete_generation")
        message = choice.get("message")
        if not isinstance(message, dict) or message.get("role") != "assistant":
            raise self._error(502, "invalid_response")
        audio = message.get("audio")
        if not isinstance(audio, dict) or audio.get("format", "wav") != "wav":
            raise self._error(502, "invalid_audio")
        # MiMo's real WAV response explicitly sets transcript=null when no
        # separate transcript is supplied. A non-null transcript must still
        # match; absence is not evidence that different text was spoken.
        transcript = audio.get("transcript")
        if transcript is not None and transcript != text:
            raise self._error(502, "transcript_mismatch")
        encoded = audio.get("data")
        if not isinstance(encoded, str) or not encoded or len(encoded) > self.MAX_BASE64_CHARS:
            raise self._error(502, "invalid_audio_size")
        try:
            content = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error):
            raise self._error(502, "invalid_base64") from None
        if not 0 < len(content) <= self.MAX_AUDIO_BYTES:
            raise self._error(502, "invalid_audio_size")
        return content

    def _inspect_audio(self, content: bytes) -> int:
        """Check the entire RIFF container and all declared PCM frames.

        A valid container cannot prove that a model pronounced every word; that
        still requires the explicit live request and human listening acceptance.
        """
        try:
            if (len(content) < 44 or content[:4] != b"RIFF" or content[8:12] != b"WAVE"
                    or int.from_bytes(content[4:8], "little") + 8 != len(content)):
                raise ValueError("Incomplete RIFF container")
            offset, formats, data = 12, [], []
            while offset < len(content):
                if offset + 8 > len(content):
                    raise ValueError("Incomplete chunk header")
                kind, size = struct.unpack_from("<4sI", content, offset)
                start = offset + 8
                end = start + size
                if end > len(content):
                    raise ValueError("Incomplete chunk")
                if kind == b"fmt ":
                    formats.append(content[start:end])
                elif kind == b"data":
                    data.append((start, size))
                offset = end + (size & 1)
            if offset != len(content) or len(formats) != 1 or len(data) != 1 or len(formats[0]) < 16:
                raise ValueError("Invalid WAV chunks")
            encoding, channels, rate, byte_rate, block_align, bits = struct.unpack_from("<HHIIHH", formats[0])
            data_start, data_size = data[0]
            if (encoding != 1 or channels not in {1, 2} or rate != self.SAMPLE_RATE or bits != 16
                    or block_align != channels * 2 or byte_rate != rate * block_align
                    or not data_size or data_size % block_align):
                raise ValueError("Unexpected PCM format")
            with wave.open(io.BytesIO(content), "rb") as reader:
                frames = reader.getnframes()
                pcm = reader.readframes(frames)
                if reader.getcomptype() != "NONE" or len(pcm) != data_size:
                    raise ValueError("Incomplete PCM frames")
            duration_ms = math.ceil(frames * 1000 / rate)
            if not 0 < duration_ms <= self.MAX_DURATION_MS:
                raise ValueError("Audio duration outside Demo limit")
            # Reject obvious empty/silent provider responses, never fabricate a
            # tone or substitute fixture. Human intelligibility remains untested.
            if not any(content[data_start:data_start + data_size]):
                raise ValueError("Silent audio")
            return duration_ms
        except (ValueError, wave.Error, EOFError, struct.error):
            raise self._error(502, "invalid_audio") from None


class MiMoASR:
    """One Chinese PCM WAV -> real transcription adapter, no fixture fallback.

    This does not make Edge recording work by itself. The browser capture
    format and A's factory/configuration must be integrated separately.
    """

    name = "real"
    is_mock = False
    MODEL = "mimo-v2.5-asr"
    BASE_URL = "https://api.xiaomimimo.com/v1"
    MAX_AUDIO_BYTES = 7 * 1024 * 1024  # Base64 stays below the supplier's 10 MB.
    MAX_RESPONSE_BYTES = 64 * 1024

    def __init__(self, *, api_key: str, base_url: str, model: str,
                 timeout_seconds: float = 20.0, connect_timeout_seconds: float = 5.0,
                 transport: httpx.AsyncBaseTransport | None = None):
        if (not isinstance(api_key, str) or not api_key or not api_key.isascii()
                or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in api_key)):
            raise ValueError("MiMo ASR requires a non-empty ASCII API key without whitespace or controls")
        if not isinstance(base_url, str) or base_url.rstrip("/") != self.BASE_URL:
            raise ValueError("MiMo ASR requires the official HTTPS API root")
        if model != self.MODEL:
            raise ValueError("This ASR adapter supports mimo-v2.5-asr only")
        if (not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 20
                or not math.isfinite(connect_timeout_seconds)
                or not 0 < connect_timeout_seconds <= min(5, timeout_seconds)):
            raise ValueError("ASR requires a total deadline <=20s and connect timeout <=5s")
        self._api_key, self.base_url, self.model = api_key, self.BASE_URL, model
        self.timeout_seconds, self.connect_timeout_seconds = timeout_seconds, connect_timeout_seconds
        self._transport = transport

    def transcribe(self, audio: bytes, mime_type: str, fixture_id: str | None = None) -> ASRResult:
        if fixture_id is not None:
            raise AppError(422, "VALIDATION_ERROR", "Real ASR does not accept mock fixture IDs")
        if not isinstance(audio, bytes) or not audio:
            raise AppError(422, "VALIDATION_ERROR", "A non-empty recording is required")
        if len(audio) > self.MAX_AUDIO_BYTES:
            raise AppError(413, "MEDIA_TOO_LARGE", "ASR recording exceeds 7 MiB")
        mime = (mime_type or "").split(";", 1)[0].strip().lower()
        if (mime not in {"audio/wav", "audio/x-wav", "audio/wave"} or len(audio) < 44
                or audio[:4] != b"RIFF" or audio[8:12] != b"WAVE"
                or int.from_bytes(audio[4:8], "little") + 8 != len(audio)):
            raise AppError(415, "ASR_FORMAT_UNSUPPORTED", "This ASR adapter requires complete PCM WAV; no transcoding is enabled")
        if inspect_wav(audio) <= 0:
            raise AppError(415, "ASR_FORMAT_UNSUPPORTED", "Recording has no complete millisecond of audio")
        raw = asyncio.run(self._request(audio))
        try:
            result = json.loads(raw)
        except (ValueError, UnicodeError, RecursionError):
            raise self._error(502, "invalid_json") from None
        if (not isinstance(result, dict) or result.get("error") is not None
                or result.get("model", self.model) != self.model):
            raise self._error(502, "invalid_response")
        choices = result.get("choices")
        if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
            raise self._error(502, "invalid_response")
        choice = choices[0]
        if choice.get("finish_reason") != "stop":
            raise self._error(502, "incomplete_transcript")
        message = choice.get("message")
        if not isinstance(message, dict) or message.get("role") != "assistant":
            raise self._error(502, "invalid_response")
        text = message.get("content")
        if not isinstance(text, str) or len(text) > 5000 or "\x00" in text:
            raise self._error(502, "invalid_transcript")
        if not text.strip():
            raise AppError(422, "VALIDATION_ERROR", "No speech recognized; use text input or record again")
        return ASRResult(transcript=text, language="zh-CN", provider=self.name, is_mock=False)

    def _error(self, status: int, reason: str, *, upstream_status: int | None = None,
               retryable: bool = False) -> AppError:
        details = {"provider": self.name, "modality": "asr", "reason": reason}
        if upstream_status is not None:
            details["upstream_status"] = upstream_status
        return AppError(status, "PROVIDER_TIMEOUT" if status == 504 else "PROVIDER_ERROR",
                        "ASR unavailable; retain the recording and offer text input", details,
                        retryable=retryable)

    async def _request(self, audio: bytes) -> bytes:
        try:
            async with asyncio.timeout(self.timeout_seconds):
                async with httpx.AsyncClient(
                    transport=self._transport, follow_redirects=False, trust_env=False,
                    timeout=httpx.Timeout(self.timeout_seconds, connect=self.connect_timeout_seconds),
                ) as client:
                    async with client.stream(
                        "POST", self.base_url + "/chat/completions",
                        headers={"api-key": self._api_key, "Accept": "application/json", "Accept-Encoding": "identity"},
                        json={"model": self.model, "messages": [{"role": "user", "content": [{
                            "type": "input_audio", "input_audio": {"format": "wav",
                                "data": "data:audio/wav;base64," + base64.b64encode(audio).decode("ascii")}}]}],
                            "asr_options": {"language": "zh"}, "stream": False},
                    ) as response:
                        status = response.status_code
                        if status != 200:
                            raise self._error(504 if status in {408, 504} else 502, "upstream_error",
                                upstream_status=status, retryable=status in {408, 429} or status >= 500)
                        if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                            raise self._error(502, "invalid_response_type")
                        if response.headers.get("content-encoding", "identity").strip().lower() != "identity":
                            raise self._error(502, "invalid_response_encoding")
                        length = response.headers.get("content-length")
                        expected = None
                        if length is not None:
                            if len(length) > 10 or not length.isascii() or not length.isdigit():
                                raise self._error(502, "invalid_content_length")
                            expected = int(length)
                            if not 0 < expected <= self.MAX_RESPONSE_BYTES:
                                raise self._error(502, "invalid_response_size")
                        raw = bytearray()
                        async for chunk in response.aiter_bytes():
                            if len(raw) + len(chunk) > self.MAX_RESPONSE_BYTES:
                                raise self._error(502, "invalid_response_size")
                            raw.extend(chunk)
                        if expected is not None and len(raw) != expected:
                            raise self._error(502, "incomplete_response")
                        return bytes(raw)
        except (TimeoutError, httpx.TimeoutException):
            raise self._error(504, "timeout", retryable=True) from None
        except httpx.HTTPError:
            raise self._error(502, "transport_error", retryable=True) from None
