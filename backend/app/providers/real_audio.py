"""One opt-in SiliconFlow TTS adapter; no database, media writes or fallback.

The public TTSProvider method remains synchronous. A owns configuration and
assembly; callers release their UoW before synthesis and register the returned
Speech through MediaPort afterwards. ASR is deliberately deferred.
"""
from __future__ import annotations

import asyncio
import io
import math
import struct
import wave

import httpx

from app.core.errors import AppError
from app.providers.mock_audio import Speech


class SiliconFlowTTS:
    """CosyVoice2, one configured voice, complete PCM WAV responses only.

    ``transport`` is an HTTPX test seam, not an alternate production provider.
    No environment is read here and construction never makes a paid request.
    """

    name = "siliconflow"
    is_mock = False
    MODEL = "FunAudioLLM/CosyVoice2-0.5B"
    ENDPOINT = "https://api.siliconflow.cn/v1/audio/speech"
    MAX_TEXT_CHARS = 200
    MAX_AUDIO_BYTES = 15 * 1024 * 1024
    MAX_DURATION_MS = 120_000
    SAMPLE_RATE = 24_000
    VOICES = frozenset({"alex", "benjamin", "charles", "david", "anna", "bella", "claire", "diana"})

    def __init__(
        self, *, api_key: str, model: str, voice: str,
        timeout_seconds: float = 20.0, connect_timeout_seconds: float = 5.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        if not isinstance(api_key, str) or not api_key.strip() or any(c.isspace() for c in api_key):
            raise ValueError("SiliconFlow TTS requires a non-empty API key without whitespace")
        if model != self.MODEL:
            raise ValueError("This adapter supports FunAudioLLM/CosyVoice2-0.5B only")
        if voice not in {f"{model}:{item}" for item in self.VOICES}:
            raise ValueError("Configure one CosyVoice2 system voice using the full model:voice ID")
        if (not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 20
                or not math.isfinite(connect_timeout_seconds)
                or not 0 < connect_timeout_seconds <= min(5, timeout_seconds)):
            raise ValueError("TTS requires a total deadline <=20s and connect timeout <=5s")
        self._api_key = api_key
        self.model, self.voice = model, voice
        self.timeout_seconds = timeout_seconds
        self.connect_timeout_seconds = connect_timeout_seconds
        self._transport = transport

    def synthesize(self, text: str, voice_id: str | None = None) -> Speech:
        if not isinstance(text, str) or not text.strip() or "\x00" in text:
            raise AppError(422, "VALIDATION_ERROR", "TTS requires non-blank text without NUL characters")
        if len(text) > self.MAX_TEXT_CHARS:
            # Never slice, chunk or read only a prefix while claiming full speech.
            raise AppError(422, "VALIDATION_ERROR", "TTS text exceeds the Demo limit; retain the full text",
                           {"max_chars": self.MAX_TEXT_CHARS, "actual_chars": len(text)})
        if voice_id is not None and voice_id != self.voice:
            raise AppError(422, "VALIDATION_ERROR", "Only the configured TTS voice is enabled")
        # FastAPI's existing sync routes run this method in a worker thread.
        # Async HTTP is local to this call so cancellation also bounds a slow
        # trickle response: HTTPX's per-read timeout alone is not a total limit.
        content = asyncio.run(self._request(text))
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
                        headers={"Authorization": f"Bearer {self._api_key}", "Accept": "audio/wav",
                                 "Accept-Encoding": "identity"},
                        json={"model": self.model, "voice": self.voice, "input": text,
                              "response_format": "wav", "sample_rate": self.SAMPLE_RATE,
                              "stream": False, "speed": 1.0},
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
                        if mime not in {"audio/wav", "audio/x-wav", "audio/wave", "application/octet-stream"}:
                            raise self._error(502, "invalid_audio_type")
                        encoding = response.headers.get("content-encoding", "identity").strip().lower()
                        if encoding != "identity":
                            raise self._error(502, "invalid_audio_encoding")
                        length = response.headers.get("content-length")
                        expected = None
                        if length is not None:
                            if len(length) > 10 or not length.isascii() or not length.isdigit():
                                raise self._error(502, "invalid_content_length")
                            expected = int(length)
                            if not 0 < expected <= self.MAX_AUDIO_BYTES:
                                raise self._error(502, "invalid_audio_size")
                        raw = bytearray()
                        async for chunk in response.aiter_bytes():
                            if len(raw) + len(chunk) > self.MAX_AUDIO_BYTES:
                                raise self._error(502, "invalid_audio_size")
                            raw.extend(chunk)
                        if expected is not None and len(raw) != expected:
                            raise self._error(502, "incomplete_audio")
                        return bytes(raw)
        except (TimeoutError, httpx.TimeoutException):
            raise self._error(504, "timeout", retryable=True) from None
        except httpx.HTTPError:
            raise self._error(502, "transport_error", retryable=True) from None

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
