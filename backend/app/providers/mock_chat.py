"""Deterministic, explicitly labelled mock; unknown images are never classified."""
from __future__ import annotations

import re
from datetime import timedelta
from pathlib import Path

from pydantic import TypeAdapter

from app.core.clock import local_date
from app.core.errors import AppError
from app.core.ids import new_id
from app.providers.planning import Plan, PlannedAction, Snapshot, request_digest
from app.schemas.agent import Action, AgentTurnWrite
from app.schemas.health import CheckinWrite
from app.schemas.identity import ProfileUpdate

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "agent"
SCENARIOS = {
    "meal_lunch", "ingredient_advice", "exercise_walk", "medication_ambiguous",
    "medication_confirm", "binding_code", "profile_update", "daily_query",
    "explicit_preference", "reject_change", "provider_timeout",
}


class MockUnderstanding:
    name = "mock"

    def plan(self, request: AgentTurnWrite, snapshot: Snapshot) -> Plan:
        if request.elder_id != snapshot.elder_id:
            raise AppError(403, "ELDER_ACCESS_DENIED", "Snapshot elder does not match request")
        fixture = request.mock_fixture_id
        if fixture is not None and fixture not in SCENARIOS:
            raise AppError(422, "VALIDATION_ERROR", "Unknown mock fixture")
        if fixture == "provider_timeout":
            raise AppError(504, "PROVIDER_TIMEOUT", "Simulated understanding timeout", retryable=True)

        def result(scene, text, *actions, preference=None, decision=None):
            return Plan(request_digest(request), scene, "【模拟】" + text, tuple(actions), preference, decision)

        def action(kind, preview, execution, *, confirm=True):
            public = TypeAdapter(Action).validate_python({
                "action_id": new_id("action"), "type": kind,
                "status": "pending" if confirm else "confirmed",
                "requires_confirmation": confirm,
                "expires_at": snapshot.now + timedelta(minutes=10), "preview": preview,
            })
            return PlannedAction(public, {"elder_id": request.elder_id, **execution})

        text = (request.text or "").strip()
        if fixture is None and text in {"我喜欢什么", "我的偏好是什么", "你记得我的偏好吗"}:
            preferences = [entry.text for entry in snapshot.memory.entries if entry.kind == "food_preference"]
            return result("health_qa", "已保存的偏好：" + "；".join(preferences) if preferences else "目前没有已保存的饮食偏好，您可以明确告诉我。")
        if fixture is None and text == "你观察到什么规律":
            patterns = [entry.text for entry in snapshot.memory.entries if entry.source_type == "observed_pattern"]
            return result("health_qa", "有效证据支持的规律：" + "；".join(patterns) if patterns else "还没有足够的有效日期记录来归纳规律。")
        if fixture is None and text in {"确认", "确认记录", "好的，确认"}:
            candidates = snapshot.pending_action_ids
            selected = request.context.pending_action_id
            if selected is not None and selected not in candidates:
                raise AppError(404, "NOT_FOUND", "Pending action unavailable in this conversation")
            if selected is None and len(candidates) == 1:
                selected = candidates[0]
            if selected is None:
                return result("clarify", "请指定要确认的动作。")
            return result("clarify", "正在确认您指定的动作。", decision=selected)

        if fixture == "meal_lunch":
            payload = {"meal_slot": "lunch", "foods": ["青菜", "豆腐", "米饭"],
                       "food_groups": ["vegetable", "protein", "staple"],
                       "image_asset_ids": request.image_asset_ids,
                       "notes": "mock_fixture:meal_lunch"}
            execution = TypeAdapter(CheckinWrite).validate_python({
                "type": "diet", "occurred_at": snapshot.now, "payload": payload,
            }).model_dump(mode="json")
            return result("meal_checkin", "演示素材是青菜、豆腐和米饭，要记为午餐吗？",
                          action("record_diet", payload, {"checkin": execution}))
        if fixture == "exercise_walk" or (fixture is None and re.fullmatch(r"(?:我)?(?:散步|走路)(?:了)?\s*\d{1,4}\s*分钟[。！]?", text)):
            match = re.search(r"(\d+)\s*分钟", text)
            minutes = int(match.group(1)) if match else 20
            if not 1 <= minutes <= 1440:
                return result("clarify", "请提供一到一千四百四十分钟内的实际运动时长。")
            payload = {"activity": "散步", "duration_minutes": minutes, "notes": "用户待确认"}
            execution = TypeAdapter(CheckinWrite).validate_python({
                "type": "exercise", "occurred_at": snapshot.now, "payload": payload,
            }).model_dump(mode="json")
            return result("exercise_checkin", f"要记下这次散步{minutes}分钟吗？",
                          action("record_exercise", payload, {"checkin": execution}))
        if fixture == "ingredient_advice":
            return result("ingredient_advice", "这是一份演示食材建议；您可以补充食材与做法，不会自动生成打卡。")
        if fixture in {"medication_confirm", "medication_ambiguous"} or (fixture is None and text in {"吃了药", "我吃药了"}):
            tasks = [t for t in snapshot.tasks if t.category == "medication"
                     and not t.cancelled and t.completion == "pending" and t.date == local_date(snapshot.now)
                     and t.plan_id and t.due_at is not None and t.due_at <= snapshot.now
                     and not t.waiting_for_meal]
            if fixture == "medication_ambiguous" or len(tasks) != 1:
                return result("clarify", "请说明是哪种药和哪个服药时段，我不会替您选择药品。")
            task = tasks[0]
            slot_id = snapshot.medication_slots.get(task.task_id)
            if not slot_id:
                return result("clarify", "需要核对档案中的具体服药时段后才能记录。")
            payload = {"plan_id": task.plan_id, "slot_id": slot_id, "intake_status": "taken",
                       "notes": "等待老人明确确认"}
            execution = TypeAdapter(CheckinWrite).validate_python({
                "type": "medication", "task_id": task.task_id,
                "occurred_at": snapshot.now, "payload": payload,
            }).model_dump(mode="json")
            return result("medication_checkin", f"请确认已按既定计划服用了{task.title}。",
                          action("record_medication", {**payload, "task_id": task.task_id},
                                 {"checkin": execution, "task_date": task.date.isoformat(),
                                  "task_plan_version": task.plan_version}))
        if fixture == "binding_code" or text in {"生成绑定码", "给我绑定码"}:
            return result("binding_code", "将通过家庭绑定服务生成绑定码。",
                          action("create_binding_code", {}, {}, confirm=False))
        if fixture == "daily_query" or text in {"今天的日报", "查看日报"}:
            day = local_date(snapshot.now).isoformat()
            return result("daily_query", "将读取今天的真实日报。",
                          action("query_report", {"date": day}, {"date": day}, confirm=False))
        if fixture == "profile_update":
            profile = snapshot.profile
            if profile is None or profile.elder_id != request.elder_id:
                return result("clarify", "请先读取并确认当前档案版本。")
            body = ProfileUpdate(expected_version=profile.version,
                                 patch={"medical_notes": "补充社区复查记录（演示修改，需确认）"})
            return result("profile_update", "要将演示复查备注更新到您的档案吗？",
                          action("update_profile", body.model_dump(mode="json", exclude_unset=True),
                                 {"target_id": profile.elder_id, "update": body.model_dump(mode="json", exclude_unset=True)}))
        if fixture == "reject_change":
            if snapshot.proposal_id:
                return result("reminder_response", "将通过真实提案服务拒绝这次修改。",
                              action("decide_change", {"proposal_id": snapshot.proposal_id, "decision": "reject"},
                                     {"proposal_id": snapshot.proposal_id, "decision": "reject"}, confirm=False))
            return result("reminder_response", "拒绝修改需要关联的真实提案；请使用提案的明确拒绝入口。")
        if fixture is None and text in {"拒绝修改", "取消修改", "接受修改"}:
            if not snapshot.proposal_id:
                return result("clarify", "请先选择这次修改对应的真实通知。")
            decision = "accept" if text == "接受修改" else "reject"
            return result("reminder_response", "将通过真实提案服务处理您的决定。",
                          action("decide_change", {"proposal_id": snapshot.proposal_id, "decision": decision},
                                 {"proposal_id": snapshot.proposal_id, "decision": decision}, confirm=False))
        if fixture is None and text in {"稍后", "等会", "稍后再提醒", "处理好了"}:
            if not request.context.notification_id:
                return result("clarify", "请先选择要处理的提醒。")
            event = {"event_id": new_id("event"), "event_type": "handled" if text == "处理好了" else "snoozed"}
            if event["event_type"] == "snoozed":
                event["snooze_minutes"] = 10
            return result("reminder_response", "将更新这条提醒的处理状态，播放本身不会记录服药。",
                          action("respond_notification", {"notification_id": request.context.notification_id, **event},
                                 {"notification_id": request.context.notification_id, "event": event}, confirm=False))
        preference = None
        if fixture == "explicit_preference":
            preference = "喜欢清淡饮食（演示偏好）"
        elif fixture is None:
            matched = re.fullmatch(r"我(?:喜欢|偏好)([^。！？]{1,80})[。！]?", text)
            if matched:
                preference = "喜欢" + matched.group(1).strip()
        if preference:
            return result("memory_update", "我会记住这条明确表达的偏好。", preference=preference)
        return result("clarify", "请描述想记录的饮食、运动或明确偏好。未知照片需要您补充内容，不会自动识别成固定菜品。")
