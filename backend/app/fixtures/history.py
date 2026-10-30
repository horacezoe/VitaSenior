"""14-day demo history template (B imports it after a matched ONB02).

A schedules the import (app/seed.py::import_demo_history); B maps these rows to
daily_tasks/checkins with source="demo_seed" and the demo_id as source key, so a
repeated confirm or login imports nothing new. C seeds matching memory entries.

Everything here is obviously synthetic demo content: it must never be read as a
medical recommendation, and medication rows carry no invented dosage - they point
at a plan index from the imported draft.
"""

HISTORY_DAYS = 14
SCENARIOS = ("diabetes_daily",)

def history_template(scenario: str = "diabetes_daily") -> tuple[dict, ...]:
    """Return immutable day rows with day_offset<0 (relative to the confirm day).

    day_offset -1 is yesterday. Nothing is generated for the confirm day itself:
    today's tasks come from the normal planner so the demo stays consistent.
    """
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown demo scenario: {scenario}")
    days = []
    for offset in range(-HISTORY_DAYS, 0):
        index = -offset  # 1..14
        day = {
            "day_offset": offset,
            "diet": [
                {
                    "meal_slot": "lunch" if index % 2 else "dinner",
                    "foods": ["青菜", "豆腐", "米饭"] if index % 2 else ["小米粥", "清蒸鱼", "炒时蔬"],
                    "food_groups": ["vegetable", "protein", "staple"],
                    "notes": "演示历史记录",
                }
            ],
            "exercise": [] if index % 7 == 0 else [
                {"activity": "散步", "duration_minutes": 20 + (index % 3) * 5, "notes": "演示历史记录"}
            ],
            "medication": [
                {"plan_index": 0, "slot_id": "morning", "intake_status": "taken" if index % 5 else "not_taken"},
            ],
        }
        days.append(day)
    return tuple(days)
