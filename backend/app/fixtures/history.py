"""14-day demo history template (B imports it after a matched ONB02).

A schedules the import (app/seed.py::import_demo_history); B maps these rows to
daily_tasks/checkins with source="demo_seed" and the demo_id as source key, so a
repeated confirm or login imports nothing new. C seeds matching memory entries.

Everything here is obviously synthetic demo content: it must never be read as a
medical recommendation, and medication rows carry no invented dosage - they point
at a plan index from the imported draft.
"""

from app.fixtures.identity import SAMPLE_PROFILES

HISTORY_DAYS = 14
SCENARIOS = ("diabetes_daily", *SAMPLE_PROFILES)

def history_template(scenario: str = "diabetes_daily") -> tuple[dict, ...]:
    """Return immutable day rows with day_offset<0 (relative to the confirm day).

    day_offset -1 is yesterday. Nothing is generated for the confirm day itself:
    today's tasks come from the normal planner so the demo stays consistent.
    """
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown demo scenario: {scenario}")
    sample = SAMPLE_PROFILES.get(scenario)
    refs = sample["history_medication"] if sample else [{"plan_index": 0, "slot_id": "morning"}]
    has_lunch_plan = any(r["slot_id"] == "after_lunch" for r in refs)
    days = []
    for offset in range(-HISTORY_DAYS, 0):
        index = -offset  # 1..14
        day = {
            "day_offset": offset,
            "diet": [
                {
                    "meal_slot": "lunch" if index % 2 or has_lunch_plan else "dinner",
                    "foods": ["青菜", "豆腐", "米饭"] if index % 2 else ["小米粥", "清蒸鱼", "炒时蔬"],
                    "food_groups": ["vegetable", "protein", "staple"],
                    "notes": "演示历史记录",
                }
            ],
            "exercise": [] if index % 7 == 0 else [
                {"activity": sample["history_activity"] if sample else "散步",
                 "duration_minutes": (sample["history_minutes"] if sample else 20) + (index % 3) * 5,
                 "notes": "演示历史记录"}
            ],
            "medication": [
                {**ref, "intake_status": "taken" if (index + position) % 5 else "not_taken"}
                for position, ref in enumerate(refs)
            ],
        }
        days.append(day)
    return tuple(days)
