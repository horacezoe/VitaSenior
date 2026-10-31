"""Explicit one-request MiMo PCM WAV probe; not collected by pytest.

python tests/providers/probe_real_asr.py --env-file .env --audio demo.wav --live
This verifies the supplier adapter only, not Edge capture or A's default factory.
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

BACKEND = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND))

from app.core.errors import AppError
from app.providers.real_audio import MiMoASR


def run(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", type=Path, help="Non-private demo PCM WAV, at most 7 MiB / 60 seconds")
    parser.add_argument("--env-file", type=Path, help="Explicit local MiMo settings; never auto-loaded")
    parser.add_argument("--live", action="store_true", help="Enable exactly one potentially billable ASR request")
    args = parser.parse_args(argv)
    if not args.live and os.getenv("LIVE_ASR") != "1":
        parser.error("Real requests are disabled; explicitly pass --live or set LIVE_ASR=1")
    if args.audio is None:
        parser.error("--audio is required")
    if args.env_file:
        allowed = {"ASR_API_KEY", "ASR_BASE_URL", "ASR_MODEL", "TTS_API_KEY", "TTS_BASE_URL"}
        for number, line in enumerate(args.env_file.read_text(encoding="utf-8-sig").splitlines(), 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, separator, value = line.partition("=")
            key, value = key.strip(), value.strip()
            if not separator or not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
                parser.error(f"Invalid env syntax at line {number}")
            if key in allowed:
                if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                    value = value[1:-1]
                os.environ[key] = value
    # Reuse the explicitly configured same MiMo account for this isolated probe.
    # These are not production Settings aliases or an implicit provider fallback.
    key = os.getenv("ASR_API_KEY") or os.getenv("TTS_API_KEY")
    base_url = os.getenv("ASR_BASE_URL") or os.getenv("TTS_BASE_URL")
    if not key or not base_url:
        parser.error("Configure local ASR_API_KEY/ASR_BASE_URL or the same MiMo TTS account")
    with args.audio.open("rb") as stream:
        audio = stream.read(MiMoASR.MAX_AUDIO_BYTES + 1)
    if len(audio) > MiMoASR.MAX_AUDIO_BYTES:
        parser.error("Audio exceeds the 7 MiB Demo limit")
    provider = MiMoASR(api_key=key, base_url=base_url, model=os.getenv("ASR_MODEL") or MiMoASR.MODEL)
    started = time.monotonic()
    result = provider.transcribe(audio, "audio/wav")
    elapsed = time.monotonic() - started
    output = BACKEND / "data/f2-audio-b/asr-evidence" / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid4().hex[:8])
    output.mkdir(parents=True)
    evidence = {"provider": result.provider, "supplier": "mimo", "model": provider.model,
                "is_mock": result.is_mock, "language": result.language, "transcript": result.transcript,
                "input_file": str(args.audio.resolve()), "input_size_bytes": len(audio),
                "input_sha256": hashlib.sha256(audio).hexdigest(), "mime_type": "audio/wav",
                "elapsed_seconds": round(elapsed, 3), "generated_at": datetime.now(timezone.utc).isoformat(),
                "edge_capture_verified": False,
                "scope": "direct ASR supplier adapter; default app factory and Edge capture not verified"}
    (output / "evidence.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print("B_ASR_WAV_PROBE_OK", json.dumps({"output": str(output), **evidence}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        run()
    except AppError as error:
        print("B_ASR_WAV_PROBE_FAILED", error.status, error.code, error.details.get("reason", "audio_validation_failed"), file=sys.stderr)
        raise SystemExit(1)
    except Exception as error:
        print("B_ASR_WAV_PROBE_FAILED", type(error).__name__, file=sys.stderr)
        raise SystemExit(1)
