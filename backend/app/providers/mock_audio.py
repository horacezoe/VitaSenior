"""Fixture audio only. No fake transcripts or synthetic tones posing as speech."""
from __future__ import annotations

import hashlib
import io
import json
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.core.errors import AppError
from app.schemas.agent import ASRResult

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "agent"


@dataclass(frozen=True)
class Speech:
    content: bytes
    mime_type: str
    duration_ms: int
    text: str
    is_mock: bool = True


class ASRProvider(Protocol):
    def transcribe(self, audio: bytes, mime_type: str, fixture_id: str | None = None) -> ASRResult: ...


class TTSProvider(Protocol):
    def synthesize(self, text: str, voice_id: str | None = None) -> Speech: ...


def inspect_wav(audio: bytes) -> int:
    try:
        with wave.open(io.BytesIO(audio), "rb") as reader:
            duration = reader.getnframes() * 1000 // reader.getframerate()
            if (reader.getcomptype() != "NONE" or reader.getnchannels() not in {1, 2}
                    or reader.getsampwidth() != 2 or reader.getnframes() == 0):
                raise ValueError("Unsupported PCM encoding")
            if len(reader.readframes(reader.getnframes())) != reader.getnframes() * reader.getnchannels() * 2:
                raise ValueError("Truncated WAV")
    except (wave.Error, EOFError, ValueError, ZeroDivisionError):
        raise AppError(415, "ASR_FORMAT_UNSUPPORTED", "A complete 16-bit PCM WAV is required")
    if duration > 60_000 or len(audio) > 15 * 1024 * 1024:
        raise AppError(413, "MEDIA_TOO_LARGE", "Audio exceeds the 60-second / 15-MiB limit")
    return duration


def _catalog():
    return json.loads((FIXTURES / "audio_manifest.json").read_text(encoding="utf-8-sig"))


class MockASR:
    name = "mock"

    def transcribe(self, audio: bytes, mime_type: str, fixture_id: str | None = None) -> ASRResult:
        if mime_type not in {"audio/wav", "audio/x-wav", "audio/wave"}:
            raise AppError(415, "ASR_FORMAT_UNSUPPORTED", "Mock ASR accepts genuine PCM WAV only")
        inspect_wav(audio)
        digest = hashlib.sha256(audio).hexdigest()
        for row in _catalog():
            if row["sha256"] == digest and (fixture_id is None or row["fixture_id"] == fixture_id):
                return ASRResult(transcript=row["text"], language="zh-CN", provider="mock", is_mock=True)
        raise AppError(422, "VALIDATION_ERROR", "This recording has no matching mock transcript; use text input")


class MockTTS:
    name = "mock"

    def synthesize(self, text: str, voice_id: str | None = None) -> Speech:
        if voice_id not in {None, "huihui_mock"}:
            raise AppError(422, "VALIDATION_ERROR", "Unknown mock voice")
        for row in _catalog():
            if row["text"] != text:
                continue
            audio = (FIXTURES / row["file"]).read_bytes()
            if hashlib.sha256(audio).hexdigest() != row["sha256"]:
                raise AppError(502, "PROVIDER_ERROR", "Mock speech fixture failed integrity check")
            return Speech(audio, "audio/wav", inspect_wav(audio), text)
        raise AppError(501, "MODULE_NOT_IMPLEMENTED", "No exact spoken fixture for this text; retain text and report tts_unavailable")
