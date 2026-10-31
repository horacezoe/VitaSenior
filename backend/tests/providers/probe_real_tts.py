"""Explicit one-request MiMo TTS probe through A's normal factory and AI02.

python tests/providers/probe_real_tts.py --env-file .env --live
No pytest collection, no automatic retries, no keys/tokens/tickets in output.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import sys
import tempfile
import time
import wave
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

BACKEND = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND))


def run(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, help="Explicit local TTS_* file; never auto-loaded")
    parser.add_argument("--live", action="store_true", help="Enable exactly one potentially billable TTS request")
    parser.add_argument("--text", help="New Chinese demo text, at most 200 characters")
    args = parser.parse_args(argv)
    if not args.live and os.getenv("LIVE_TTS") != "1":
        parser.error("Real requests are disabled; explicitly pass --live or set LIVE_TTS=1")
    if args.env_file:
        allowed = {"TTS_API_KEY", "TTS_BASE_URL", "TTS_MODEL", "TTS_VOICE"}
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
    required = ["TTS_API_KEY", "TTS_BASE_URL", "TTS_MODEL"]
    missing = [key for key in required if not os.getenv(key)]
    if missing:
        parser.error("Missing local configuration: " + ", ".join(missing))
    text = args.text or ("您好，这是银龄健康助手的新语音测试。请先查看页面上的完整文字，再听这段语音。测试时间："
                        + datetime.now(ZoneInfo("Asia/Hong_Kong")).strftime("%Y年%m月%d日%H时%M分%S秒") + "。")
    if not text.strip() or len(text) > 200 or "\x00" in text:
        parser.error("Use non-blank demo text of at most 200 characters")
    parent = BACKEND / ".pytest_cache" / "f2-audio-b-probe"
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="run-", dir=parent) as temporary:
        # Ignore any DB/data/provider switches in the supplied file. This probe
        # always uses its own short-lived DB and the normal real TTS factory.
        os.environ.pop("DATABASE_URL", None)
        os.environ.update(DATA_DIR=temporary, CHAT_PROVIDER="mock", ASR_PROVIDER="mock",
                          TTS_PROVIDER="real", SCANNER_ENABLED="false", APP_ENV="demo",
                          APP_TIMEZONE="Asia/Hong_Kong", PUBLIC_BASE_URL="http://testserver")
        from fastapi.testclient import TestClient
        from app.main import create_app
        from app.providers.real_tts import MiMoTTS
        from app.seed import framework_seed

        app = create_app()  # No provider/service/Settings injection.
        if not isinstance(app.state.agent_tts, MiMoTTS) or app.state.agent_tts.name != "real":
            raise RuntimeError("Normal factory did not construct real MiMo TTS")
        with TestClient(app, raise_server_exceptions=False) as client:
            def checked(method, path, **kwargs):
                response = client.request(method, path, **kwargs)
                if response.status_code != 200:
                    try:
                        error = response.json().get("error", {})
                    except ValueError:
                        error = {}
                    code = error.get("code", "NON_JSON_RESPONSE")
                    reason = error.get("details", {}).get("reason", "unavailable")
                    raise RuntimeError(f"{method} {path.split('?')[0]}: {response.status_code} {code} {reason}")
                return response

            seed = framework_seed(app.state.sessions, app.state.clock)
            account = {key: seed["elder"][key] for key in ["phone", "role"]}
            challenge = checked("POST", "/api/v1/auth/code", json=account).json()["data"]["challenge_id"]
            login = checked("POST", "/api/v1/auth/login", json={**account, "challenge_id": challenge,
                            "code": "123456"}).json()["data"]
            headers = {"Authorization": "Bearer " + login["access_token"]}
            runtime = checked("GET", "/api/v1/runtime", headers=headers).json()["data"]["providers"]
            if runtime != {"chat": "mock", "asr": "mock", "tts": "real"}:
                raise RuntimeError("Runtime does not match the actual configured providers")
            started = time.monotonic()
            result = checked("POST", "/api/v1/ai/tts", headers=headers,
                             json={"elder_id": seed["elder"]["elder_id"], "text": text}).json()["data"]
            elapsed = time.monotonic() - started
            if result["provider"] != "real" or result["is_mock"] is not False:
                raise RuntimeError("AI02 returned incorrect provenance")
            asset = result["audio_asset"]
            media = checked("GET", asset["content_url"])
            audio = media.content
            if (asset["mime_type"] != "audio/wav" or media.headers.get("content-type") != "audio/wav"
                    or not 0 < len(audio) <= 15 * 1024 * 1024 or asset["size_bytes"] != len(audio)
                    or not asset["duration_ms"] or asset["duration_ms"] <= 0):
                raise RuntimeError("MEDIA03 bytes/type/duration mismatch")
            with wave.open(io.BytesIO(audio), "rb") as reader:
                if len(reader.readframes(reader.getnframes())) != reader.getnframes() * reader.getsampwidth() * reader.getnchannels():
                    raise RuntimeError("Incomplete retrieved WAV")
            provider = app.state.agent_tts
            evidence = {"provider": result["provider"], "supplier": "mimo", "is_mock": False,
                        "model": provider.model, "voice": provider.voice, "text": text,
                        "mime_type": asset["mime_type"], "duration_ms": asset["duration_ms"],
                        "size_bytes": len(audio), "elapsed_seconds": round(elapsed, 3),
                        "sha256": hashlib.sha256(audio).hexdigest(), "runtime": runtime,
                        "generated_at": datetime.now(timezone.utc).isoformat(), "listened": False,
                        "scope": "normal factory + authenticated AI02 + ticket MEDIA03 (TestClient)"}
        output = BACKEND / "data" / "f2-audio-b" / "evidence" / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid4().hex[:8])
        output.mkdir(parents=True)
        (output / "speech.wav").write_bytes(audio)
        (output / "evidence.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
        print("B_LIVE_TTS_OK", json.dumps({"output": str(output), **evidence}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        run()
    except RuntimeError as error:
        print("B_LIVE_TTS_FAILED", str(error), file=sys.stderr)
        raise SystemExit(1)
    except Exception as error:
        # Configuration/OS/encoding exceptions can contain paths or credentials;
        # avoid dumping a traceback or arbitrary exception message in live mode.
        print("B_LIVE_TTS_FAILED", type(error).__name__, file=sys.stderr)
        raise SystemExit(1)
