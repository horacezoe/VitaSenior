"""Pre-rendered spoken proposal notices (Windows SAPI zh-CN, generated offline).

A tone is not evidence that the elder heard the change, so every proposal type has
its own complete spoken sentence and the notification text is exactly that
sentence. The bytes are prepared OUTSIDE the write transaction; only registration
happens in-tx (see identity_flows.create_change).

Regenerate with fixtures/identity/generate_notices.ps1 when a sentence changes.
"""
import io
import json
import wave
from functools import lru_cache
from pathlib import Path

from app.contracts.media import GeneratedAudio, SpokenNotice

HERE = Path(__file__).resolve().parents[2] / "fixtures" / "identity"
MANIFEST = json.loads((HERE / "proposal_notices.json").read_text(encoding="utf-8-sig"))
_BY_KEY = {row["notice"]: row for row in MANIFEST}

KEYS = {
    ("profile", "update"): "profile_update",
    ("reminder_settings", "update"): "settings_update",
    ("medication_plan", "create"): "plan_create",
    ("medication_plan", "update"): "plan_update",
    ("medication_plan", "deactivate"): "plan_deactivate",
}

@lru_cache(maxsize=None)
def notice_for(target_type: str, operation: str) -> SpokenNotice:
    """Return the spoken notice whose text is exactly what gets spoken."""
    row = _BY_KEY[KEYS[(target_type, operation)]]
    content = (HERE / row["file"]).read_bytes()
    with wave.open(io.BytesIO(content)) as wav:
        duration_ms = int(1000 * wav.getnframes() / wav.getframerate())
    return SpokenNotice(text=row["text"], audio=GeneratedAudio(content=content, mime_type="audio/wav", duration_ms=duration_ms))
