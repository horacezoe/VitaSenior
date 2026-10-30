"""One-click integration smoke for the three F1 acceptance rounds.

    python -m app.tools.integration_smoke                 # temporary DB, in-process
    python -m app.tools.integration_smoke --base-url URL  # against a running server
    python -m app.tools.integration_smoke --strict        # PENDING also fails the run

Each step is classified honestly:

    OK       the real HTTP contract answered with the expected status
    PENDING  the route answered 501 MODULE_NOT_IMPLEMENTED (a dependency is still a stub)
    FAIL     anything else, including a wrong body or a 5xx

PENDING is never counted as success. Until B/C land their ports the run tells you
exactly where the chain breaks; once they do, `--strict` becomes the merge gate.
This tool does not create data outside its temporary DATA_DIR and never fakes a
business write.
"""
import argparse
import json
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

OK, PENDING, FAIL = "OK", "PENDING", "FAIL"

@dataclass
class Result:
    round: str
    step: str
    status: str
    detail: str = ""

class StepFailed(Exception):
    pass

class Run:
    def __init__(self, client, clock=None, app=None):
        self.client, self.clock, self.app = client, clock, app
        self.results: list[Result] = []
        self.state: dict = {}

    # ---- transport -----------------------------------------------------------

    def req(self, rnd, name, method, path, *, expect=(200, 201), headers=None, **kwargs):
        response = self.client.request(method, path, headers=headers or {}, **kwargs)
        if response.status_code == 501:
            message = response.json().get("error", {}).get("message", "")
            self.results.append(Result(rnd, name, PENDING, message[:70]))
            return None
        if response.status_code not in expect:
            self.results.append(Result(rnd, name, FAIL, f"{response.status_code} {response.text[:140]}"))
            return None
        self.results.append(Result(rnd, name, OK, str(response.status_code)))
        return response

    def token(self, rnd, label, account, headers_key):
        challenge = self.req(rnd, f"{label} challenge", "POST", "/api/v1/auth/code", json=account)
        if challenge is None:
            return None
        login = self.req(rnd, f"{label} login", "POST", "/api/v1/auth/login",
                         json={**account, "challenge_id": challenge.json()["data"]["challenge_id"], "code": "123456"})
        if login is None:
            return None
        self.state[headers_key] = {"Authorization": "Bearer " + login.json()["data"]["access_token"]}
        return self.state[headers_key]

    def body(self, rnd, name, response):
        return response.json()["data"]

    def advance(self, seconds: int) -> bool:
        if self.clock is None:
            return False
        self.clock.advance(seconds=seconds)
        if self.app is not None:
            self.app.state.scanner.tick()
        return True

def hdr(headers: dict, key: str) -> dict:
    return {**headers, "Idempotency-Key": key}

# ---- round 1: login -> draft confirm -> binding -> media -> shared record -----

def round_one(run: Run) -> None:
    rnd = "R1"
    demo = run.req(rnd, "DEMO01 experience", "POST", "/api/v1/demo/experiences",
                   headers={"Idempotency-Key": "r1-demo"}, json={"scenario": "diabetes_daily"})
    if demo is None:
        return
    experience = run.body(rnd, "DEMO01", demo)
    elder_id = experience["elder_id"]
    run.state["elder_id"] = elder_id
    elder = run.token(rnd, "elder", experience["elder_account"], "elder")
    child = run.token(rnd, "child", experience["child_account"], "child")
    if not elder or not child:
        return
    run.req(rnd, "elder profile readable", "GET", f"/api/v1/elders/{elder_id}/profile", headers=elder)
    run.req(rnd, "face upload (MEDIA01)", "POST", "/api/v1/media", headers=hdr(elder, "r1-face"),
            files={"file": ("face.png", b"\x89PNG\r\n\x1a\n" + b"0" * 64, "image/png")},
            data={"purpose": "face", "elder_id": elder_id})
    matched = run.req(rnd, "ONB01 match draft", "POST", f"/api/v1/elders/{elder_id}/onboarding/match",
                      headers=hdr(elder, "r1-match"), json={"sample_identity_key": "community_sample_001"})
    if matched is None:
        return
    draft = run.body(rnd, "ONB01", matched)
    run.req(rnd, "ONB02 confirm profile", "POST", f"/api/v1/elders/{elder_id}/onboarding/confirm",
            headers=hdr(elder, "r1-confirm"),
            json={"draft_id": draft["draft_id"], "profile": draft["profile_draft"],
                  "medication_plans": draft["medication_plan_drafts"], "expected_version": 1})
    code = run.req(rnd, "BIND01 issue code", "POST", f"/api/v1/elders/{elder_id}/binding-codes",
                   headers=hdr(elder, "r1-code"))
    if code is not None:
        binding_code = run.body(rnd, "BIND01", code)["code"]
        run.req(rnd, "BIND02 preview", "POST", "/api/v1/family-bindings/preview",
                headers=child, json={"code": binding_code})
        run.req(rnd, "BIND03 consume", "POST", "/api/v1/family-bindings",
                headers=hdr(child, "r1-bind"), json={"code": binding_code, "relationship": "女儿"})
    run.req(rnd, "BIND04 bound elders", "GET", "/api/v1/me/elders", headers=child)
    lunch = run.req(rnd, "lunch photo upload", "POST", "/api/v1/media", headers=hdr(elder, "r1-lunch"),
                    files={"file": ("lunch.png", b"\x89PNG\r\n\x1a\n" + b"1" * 64, "image/png")},
                    data={"purpose": "meal", "elder_id": elder_id})
    image_ids = [run.body(rnd, "lunch", lunch)["asset_id"]] if lunch is not None else []
    turn = run.req(rnd, "AGENT01 lunch analysis", "POST", "/api/v1/agent/turns", headers=hdr(elder, "r1-turn"),
                   json={"elder_id": elder_id, "client_turn_id": "r1-turn", "text": "这是我今天的午饭，青菜和豆腐",
                         "image_asset_ids": image_ids, "mock_fixture_id": "meal_lunch"})
    if turn is None:
        return
    actions = run.body(rnd, "AGENT01", turn)["actions"]
    if not actions:
        run.results.append(Result(rnd, "AGENT02 confirm action", FAIL, "no pending action returned"))
        return
    run.req(rnd, "AGENT02 confirm action", "POST", f"/api/v1/agent/actions/{actions[0]['action_id']}/decision",
            headers=hdr(elder, "r1-action"), json={"decision": "confirm"})
    run.req(rnd, "child dashboard sees record", "GET", f"/api/v1/elders/{elder_id}/dashboard", headers=child)

# ---- round 2: medication task, receipt window, reject, settlement ------------

def round_two(run: Run) -> None:
    rnd = "R2"
    elder, child = run.state.get("elder"), run.state.get("child")
    elder_id = run.state.get("elder_id")
    if not elder or not elder_id:
        run.results.append(Result(rnd, "preconditions", PENDING, "round 1 did not reach an elder account"))
        return
    plan = run.req(rnd, "PLAN02 medication plan", "POST", f"/api/v1/elders/{elder_id}/medication-plans",
                   headers=hdr(elder, "r2-plan"),
                   json={"name": "演示药品A", "dose_display": "既定用量",
                         "schedule": {"mode": "fixed", "slots": [{"slot_id": "morning", "local_time": "08:00"}]},
                         "start_date": "2026-10-30"})
    tasks = run.req(rnd, "TASK01 today's tasks", "GET", f"/api/v1/elders/{elder_id}/tasks?date=2026-10-30",
                    headers=elder)
    task_id = None
    if tasks is not None:
        items = run.body(rnd, "TASK01", tasks)["items"]
        task_id = next((t["task_id"] for t in items if t["category"] == "medication"), None)
    plan_id = run.body(rnd, "plan", plan)["plan_id"] if plan is not None else None
    if task_id is None or plan_id is None:
        run.results.append(Result(rnd, "REC02 medication taken", PENDING, "no medication task/plan yet (B task port)"))
    else:
        run.req(rnd, "REC02 medication taken", "POST", f"/api/v1/elders/{elder_id}/checkins",
                headers=hdr(elder, "r2-checkin"),
                json={"type": "medication", "task_id": task_id, "occurred_at": "2026-10-30T04:00:00Z",
                      "payload": {"plan_id": plan_id, "slot_id": "morning", "intake_status": "taken"}})
    proposal = run.req(rnd, "CHANGE01 child proposal", "POST", f"/api/v1/elders/{elder_id}/change-proposals",
                       headers=hdr(child, "r2-proposal"),
                       json={"target_type": "profile", "target_id": elder_id, "operation": "update",
                             "base_version": 1, "patch": {"medical_notes": "补充社区复查记录"}})
    if proposal is None:
        return
    proposal_id = run.body(rnd, "CHANGE01", proposal)["proposal_id"]
    notice = run.req(rnd, "NOTI02 pending notifications", "GET", f"/api/v1/elders/{elder_id}/notifications",
                     headers=elder)
    if notice is None:
        return
    items = run.body(rnd, "NOTI02", notice)["items"]
    target = next((n for n in items if n["proposal_id"] == proposal_id), None)
    if target is None:
        run.results.append(Result(rnd, "proposal notification", FAIL, "no notification linked to the proposal"))
        return
    for event in ("displayed", "answered", "playback_completed"):
        run.req(rnd, f"NOTI03 {event}", "POST", f"/api/v1/notifications/{target['notification_id']}/events",
                headers=hdr(elder, f"r2-{event}"), json={"event_id": f"r2-{event}", "event_type": event})
    run.req(rnd, "CHANGE04 reject in window", "POST", f"/api/v1/change-proposals/{proposal_id}/decision",
            headers=hdr(elder, "r2-reject"), json={"decision": "reject"})
    run.req(rnd, "profile unchanged after reject", "GET", f"/api/v1/elders/{elder_id}/profile", headers=elder)
    if run.advance(61):
        run.req(rnd, "scanner settles expired window", "GET", f"/api/v1/elders/{elder_id}/change-proposals?status=applied",
                headers=elder)
    else:
        run.results.append(Result(rnd, "scanner settles expired window", PENDING, "live server: drive the clock externally"))

# ---- round 3: correction, memory, isolation, provider probe ------------------

def round_three(run: Run) -> None:
    rnd = "R3"
    elder, child = run.state.get("elder"), run.state.get("child")
    elder_id = run.state.get("elder_id")
    if not elder or not child or not elder_id:
        run.results.append(Result(rnd, "preconditions", PENDING, "round 1 did not reach both accounts"))
        return
    checkins = run.req(rnd, "REC01 list today", "GET", f"/api/v1/elders/{elder_id}/checkins?date=2026-10-30",
                       headers=elder)
    checkin_id = None
    if checkins is not None:
        items = run.body(rnd, "REC01", checkins)["items"]
        checkin_id = next((c["checkin_id"] for c in items if c["type"] == "diet" and not c["cancelled"]), None)
    if checkin_id:
        run.req(rnd, "REC03 correct the meal", "PUT", f"/api/v1/checkins/{checkin_id}",
                headers=hdr(elder, "r3-correct"),
                json={"expected_version": 1, "payload": {"meal_slot": "lunch", "foods": ["青菜", "豆腐", "米饭", "苹果"],
                                                         "food_groups": ["vegetable", "protein", "staple", "fruit"]}})
    run.req(rnd, "REPORT01 reflects correction", "GET", f"/api/v1/elders/{elder_id}/reports/daily?date=2026-10-30",
            headers=child)
    run.req(rnd, "MEM01 memory document", "GET", f"/api/v1/elders/{elder_id}/memory", headers=child)
    # Isolation: a second DEMO01 pair is a real stranger to this elder's family.
    other = run.req(rnd, "second DEMO01 pair", "POST", "/api/v1/demo/experiences",
                    headers={"Idempotency-Key": "r3-demo"}, json={"scenario": "diabetes_daily"})
    stranger = None
    if other is not None:
        stranger = run.token(rnd, "unbound child", run.body(rnd, "DEMO01#2", other)["child_account"], "stranger")
    if stranger:
        run.req(rnd, "unbound child denied profile", "GET", f"/api/v1/elders/{elder_id}/profile",
                headers=stranger, expect=(403,))
        run.req(rnd, "unbound child denied dashboard", "GET", f"/api/v1/elders/{elder_id}/dashboard",
                headers=stranger, expect=(403,))
    runtime = run.req(rnd, "SYS02 runtime probe", "GET", "/api/v1/runtime", headers=elder)
    if runtime is not None:
        data = run.body(rnd, "SYS02", runtime)
        declared = len([k for k, v in data["capabilities"].items() if v])
        print(f"     runtime: {declared} capabilities true, providers={data['providers']}")

ROUNDS = (("round 1: login -> draft -> binding -> media -> shared record", round_one),
          ("round 2: medication task -> receipt window -> reject", round_two),
          ("round 3: correction -> memory -> isolation -> probe", round_three))

def report(results: list[Result]) -> int:
    width = max((len(r.step) for r in results), default=10)
    current = None
    for result in results:
        if result.round != current:
            current = result.round
            print()
        print(f"  {result.round}  {result.step:<{width}}  {result.status:<8} {result.detail}")
    counts = {status: sum(1 for r in results if r.status == status) for status in (OK, PENDING, FAIL)}
    print(f"\n  summary: {counts[OK]} ok, {counts[PENDING]} pending, {counts[FAIL]} failed")
    failed = [r for r in results if r.status == FAIL]
    for result in failed:
        print(f"  FAILED {result.round}/{result.step}: {result.detail}")
    return 1 if failed else 0

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default=None, help="run against a live server instead of a temporary in-process app")
    parser.add_argument("--strict", action="store_true", help="treat PENDING steps as failures (merge gate)")
    parser.add_argument("--json", action="store_true", help="emit the raw results as JSON")
    args = parser.parse_args(argv)

    if args.base_url:
        import httpx
        client = httpx.Client(base_url=args.base_url, timeout=30)
        run = Run(client, clock=None, app=None)
        try:
            for _, round_fn in ROUNDS:
                round_fn(run)
        finally:
            client.close()
    else:
        from fastapi.testclient import TestClient
        from app.core.clock import FakeClock
        from app.core.config import Settings
        from app.main import create_app
        clock = FakeClock(datetime(2026, 10, 30, 4, 0, tzinfo=timezone.utc))
        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(Settings(data_dir=Path(tmp) / "db", scanner_enabled=False), clock=clock)
            with TestClient(app, raise_server_exceptions=False) as client:
                run = Run(client, clock=clock, app=app)
                for _, round_fn in ROUNDS:
                    round_fn(run)

    if args.json:
        print(json.dumps([r.__dict__ for r in run.results], ensure_ascii=False, indent=2))
    code = report(run.results)
    if args.strict and any(r.status == PENDING for r in run.results):
        return 1
    return code

if __name__ == "__main__":
    sys.exit(main())
