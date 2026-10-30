"""Community sample profiles for ONB01 (demo only, not a diagnosis).

A sample key either matches a known demo profile ("matched") or produces an empty
confirmable draft ("not_found"). Matching never touches the real profile: ONB02 is
what writes it.
"""
from copy import deepcopy

SAMPLE_PROFILES: dict[str, dict] = {
    "community_sample_001": {
        "profile": {
            "display_name": "陈阿姨",
            "birth_date": "1958-05-12",
            "sex": "female",
            "conditions": ["糖尿病（演示档案）"],
            "allergies": [],
            "medical_notes": "社区体检样本档案",
            "source": "community_mock",
        },
        "medication_plans": [
            {
                "name": "演示药品A",
                "dose_display": "演示档案中的既定用量",
                "schedule": {"mode": "fixed", "slots": [{"slot_id": "morning", "local_time": "08:00"}]},
                "start_date": None,  # resolved to the confirm day by ONB02
                "notes": "来源于预置演示档案",
            }
        ],
    },
}

EMPTY_DRAFT = {
    "display_name": "待完善",
    "birth_date": None,
    "sex": "unknown",
    "conditions": [],
    "allergies": [],
    "medical_notes": "",
}

def match_sample(sample_identity_key: str) -> dict | None:
    """Return a deep copy so callers cannot mutate the fixture."""
    sample = SAMPLE_PROFILES.get(sample_identity_key)
    return deepcopy(sample) if sample else None
