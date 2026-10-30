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
