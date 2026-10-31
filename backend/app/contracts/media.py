"""Controlled media reads and writes across domain boundaries.

The server keeps the absolute file path private; callers receive a short-lived
content URL (MediaAsset.content_url) or, inside the request, a MediaContent
handle whose bytes the HTTP layer streams back. No domain may guess a path.
"""
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class MediaContent:
    mime_type: str
    size_bytes: int
    path: Path

@dataclass(frozen=True)
class GeneratedAudio:
    """Bytes produced OUTSIDE the write transaction (TTS / pre-rendered speech).

    Flows prepare this before opening the write UoW, then register it in-tx through
    MediaPort so no provider call ever sits inside BEGIN IMMEDIATE."""
    content: bytes
    mime_type: str
    duration_ms: int | None = None

@dataclass(frozen=True)
class SpokenNotice:
    """A complete spoken notice whose `text` is exactly what the audio says.

    Proposal notifications must carry the actual spoken content: a beep cannot
    prove the elder heard the change, so it may never start the auto-apply window."""
    text: str
    audio: GeneratedAudio

