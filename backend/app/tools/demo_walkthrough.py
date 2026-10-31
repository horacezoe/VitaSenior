"""Runnable front-end walkthrough: DEMO01 -> login -> draft -> binding -> agent -> dashboard.

Prints every request and a trimmed response so the front-end team can mirror the
exact shapes instead of guessing. Runs against a temporary in-process app with a
fixed clock, or against a live server:

    python -m app.tools.demo_walkthrough
    python -m app.tools.demo_walkthrough --base-url http://127.0.0.1:8000

Read docs/协作/F2交接/前端接入.md for the written contract; this script is the
executable version of that document. It never touches a real DATA_DIR.
"""
import argparse
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

DEMO_DATE = "2026-10-30"

def hdr(auth: dict, key: str) -> dict:
    return {**auth, "Idempotency-Key": key}

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default=None, help="target a running server instead of a temporary app")
    parser.add_argument("--full", action="store_true", help="print complete bodies instead of 700 chars")
    args = parser.parse_args(argv)

    if args.base_url:
        import httpx
        client = httpx.Client(base_url=args.base_url, timeout=30)
        close = client.close
    else:
        from fastapi.testclient import TestClient
        from app.core.clock import FakeClock
        from app.core.config import Settings
        from app.main import create_app
        tmp = tempfile.TemporaryDirectory()
        app = create_app(Settings(data_dir=Path(tmp.name) / "db", scanner_enabled=False),
                         clock=FakeClock(datetime(2026, 10, 30, 4, 0, tzinfo=timezone.utc)))
        client = TestClient(app, raise_server_exceptions=False)
        client.__enter__()  # run lifespan so app.state.sessions/engine exist
        def close():
            client.__exit__(None, None, None)
            tmp.cleanup()

    def call(step: str, method: str, path: str, *, auth: str = "", **kwargs):
        response = client.request(method, "/api/v1" + path, headers=kwargs.pop("headers", {}), **kwargs)
        ctype = response.headers.get("content-type", "")
        body = response.json() if ctype.startswith("application/json") else {"binary_bytes": len(response.content)}
        shown = json.dumps(body, ensure_ascii=False, indent=1)
        if not args.full:
            shown = shown[:700] + ("..." if len(shown) > 700 else "")
        print(f"\n### {step}\n{method} {path}  ->  {response.status_code}  ({auth or 'public'})\n{shown}")
        return response

    def login(label: str, account: dict) -> dict:
        challenge = call(f"{label}: request code", "POST", "/auth/code", json=account)
        token = call(f"{label}: login", "POST", "/auth/login",
                     json={**account, "challenge_id": challenge.json()["data"]["challenge_id"], "code": "123456"})
        return {"Authorization": "Bearer " + token.json()["data"]["access_token"]}

    try:
        demo = call("1. create a demo family (public, idempotent)", "POST", "/demo/experiences",
                    headers=hdr({}, "demo-1"), json={"scenario": "diabetes_daily"}).json()["data"]
        elder = login("2. elder", demo["elder_account"])
        child = login("3. child", demo["child_account"])
        elder_id = demo["elder_id"]

        matched = call("4. match the community sample", "POST", f"/elders/{elder_id}/onboarding/match",
                       headers=hdr(elder, "match-1"), json={"sample_identity_key": "community_sample_001"}).json()["data"]
        call("5. confirm the profile (imports the draft plans)", "POST", f"/elders/{elder_id}/onboarding/confirm",
             headers=hdr(elder, "confirm-1"),
             json={"draft_id": matched["draft_id"], "profile": matched["profile_draft"],
                   "medication_plans": matched["medication_plan_drafts"], "expected_version": 1})

        code = call("6. elder issues a binding code", "POST", f"/elders/{elder_id}/binding-codes",
                    headers=hdr(elder, "code-1")).json()["data"]["code"]
        call("7. child previews the code", "POST", "/family-bindings/preview", headers=child, json={"code": code})
        call("8. child binds", "POST", "/family-bindings", headers=hdr(child, "bind-1"),
             json={"code": code, "relationship": "女儿"})

        turn = call("9. agent turn: lunch photo + text", "POST", "/agent/turns", headers=hdr(elder, "turn-1"),
                    json={"elder_id": elder_id, "client_turn_id": "walkthrough-1",
                          "text": "这是我的演示午餐", "mock_fixture_id": "meal_lunch"}).json()["data"]
        action = turn["actions"][0]["action_id"]
        call("10. elder confirms the pending action", "POST", f"/agent/actions/{action}/decision",
             headers=hdr(elder, "action-1"), json={"decision": "confirm"})

        call("11. child dashboard (same record)", "GET", f"/elders/{elder_id}/dashboard?date={DEMO_DATE}", headers=child)
        call("12. elder daily report", "GET", f"/elders/{elder_id}/reports/daily?date={DEMO_DATE}", headers=elder)
        call("13. runtime capabilities/providers", "GET", "/runtime", headers=elder)
        print("\nWALKTHROUGH_OK")
        return 0
    finally:
        close()

if __name__ == "__main__":
    sys.exit(main())
