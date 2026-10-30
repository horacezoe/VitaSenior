from __future__ import annotations

import calendar
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.context import Actor
from app.contracts.ports import AccessPort, MemoryPort
from app.core.clock import Clock, SystemClock, local_date
from app.models.identity import ElderProfile, FamilyBinding
from app.schemas.health import AttentionItem, Calendar, CalendarDay, DailyReport, Progress, ProgressCount, Records
from app.schemas.identity import Dashboard, ElderSummary, RiskAssessment
from app.services.health_service import authorize, checkin_dto, live_records, materialize_tasks, task_dto


class ReportService:
    def __init__(self, clock: Clock | None = None, *, access: AccessPort | None = None,
                 memory: MemoryPort | None = None):
        self.clock, self.access, self.memory = clock or SystemClock(), access, memory

    def _compute(self, tx, elder_id, day):
        now = self.clock.now()
        tasks = materialize_tasks(tx, elder_id, day, now)
        rows = live_records(tx, elder_id, day)
        views = [task_dto(t, rows) for t in tasks]
        counts = {}
        for category in ("diet", "exercise", "medication"):
            goals = [t for t in views if t.category == category]
            counts[category] = ProgressCount(completed=sum(t.completion == "completed" for t in goals),
                expected=len(goals), applicable=bool(goals))
        if day > local_date(now):
            state, color = "future", None
        elif not rows:
            state, color = "unrecorded", "gray"
        elif all(p.completed == p.expected for p in counts.values()) and any(p.applicable for p in counts.values()):
            state, color = "complete", "green"
        else:
            state, color = "partial", "yellow"
        completion = CalendarDay(date=day, state=state, color=color,
            is_today=day == local_date(now), progress=Progress(**counts))
        records = Records(**{c: [checkin_dto(r) for r in rows if r.type == c] for c in counts})
        attention = []
        for t in views:
            if t.completion == "not_taken":
                attention.append(AttentionItem(id=f"not_taken:{t.task_id}", kind="record_not_taken",
                    title=f"{t.title}：明确记录未服用", detail="本人明确记录未服用；不代表其他时段的情况。",
                    source_ids=t.checkin_ids, can_remind=True))
            elif t.completion == "pending" and day <= local_date(now) and (day < local_date(now) or (t.due_at and t.due_at <= now)):
                attention.append(AttentionItem(id=f"missing:{t.task_id}", kind="record_missing",
                    title=f"{t.title}：尚未记录", detail="尚无确认记录，不能据此推断实际未完成或未服药。",
                    source_ids=[t.task_id], can_remind=True))
        return completion, records, attention, views

    def daily(self, tx: Session, actor: Actor, elder_id: str, day: date) -> DailyReport:
        authorize(tx, actor, elder_id, access=self.access)
        completion, records, attention, _ = self._compute(tx, elder_id, day)
        p = completion.progress
        text = f"饮食记录 {p.diet.completed}/{p.diet.expected}，运动记录 {p.exercise.completed}/{p.exercise.expected}，明确确认服药 {p.medication.completed}/{p.medication.expected}。未记录不等于实际未完成。"
        return DailyReport(elder_id=elder_id, date=day, completion=completion, records=records,
            summary_text=text, attention_items=attention, updated_at=self.clock.now())

    def calendar(self, tx, actor, elder_id, month):
        authorize(tx, actor, elder_id, access=self.access)
        year, number = map(int, month.split("-"))
        days = [self._compute(tx, elder_id, date(year, number, n))[0]
            for n in range(1, calendar.monthrange(year, number)[1] + 1)]
        return Calendar(month=month, days=days)

    def dashboard(self, tx, actor, elder_id, day=None):
        authorize(tx, actor, elder_id, access=self.access)
        day = day or local_date(self.clock.now())
        completion, records, attention, tasks = self._compute(tx, elder_id, day)
        profile = tx.get(ElderProfile, elder_id).profile_json
        birth = date.fromisoformat(profile["birth_date"]) if profile.get("birth_date") else None
        today = local_date(self.clock.now())
        age = today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day)) if birth else None
        binding = tx.scalar(select(FamilyBinding).where(FamilyBinding.elder_id == elder_id,
            FamilyBinding.child_user_id == actor.user_id, FamilyBinding.status == "active"))
        return Dashboard(elder=ElderSummary(elder_id=elder_id, display_name=profile["display_name"],
            age=age, conditions=profile.get("conditions", []), binding_id=binding.id if binding else None,
            relationship=binding.relationship if binding else None), date=day, completion=completion,
            today_records=records, pending_tasks=[t for t in tasks if t.completion != "completed"],
            attention_items=attention, recommendations=[], memory_summary="", provider_mode="mock",
            risk_assessment=RiskAssessment())
