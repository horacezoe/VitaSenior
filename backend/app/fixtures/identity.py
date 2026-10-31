"""Entirely fictional community records seeded into the application's SQLite.

Medicine labels and dose text are synthetic existing-plan fields, not prescriptions.
"""
from copy import deepcopy

DEFAULT_PERSONA = "community_sample_001"
UNMATCHED_PERSONA = "community_unmatched"
COMMUNITY_NAME = "银龄演示社区"


def medicine(key: str, *, evening: bool = False, after_meal: bool = False) -> dict:
    slot = ({"slot_id": "after_lunch", "meal_slot": "lunch", "delay_minutes": 30}
            if after_meal else
            {"slot_id": "evening" if evening else "morning",
             "local_time": "20:00" if evening else "08:00"})
    return {
        "template_key": key,
        "plan": {
            "name": f"演示药品{key.upper()}",
            "dose_display": "演示档案中的既定用量",
            "schedule": {"mode": "after_meal" if after_meal else "fixed", "slots": [slot]},
            "start_date": None,
            "notes": "来源于预置演示档案；虚构用药字段",
        },
    }


# Fixed fixtures, not clinical advice. Variations are authored, never inferred.
_PEOPLE = [
    ("陈阿姨", "1958-05-12", "female", ["糖尿病（演示档案）"], [], "社区体检样本档案", [medicine("a")]),
    ("张伯伯", "1952-09-18", "male", ["高血压（演示档案）"], [], "习惯在纸本记录血压，建档时请一并核对。", [medicine("a")]),
    ("李阿姨", "1960-03-08", "female", ["血脂异常（演示档案）"], [], "既往复查信息为虚构，喜欢和家人一起做饭。", [medicine("a", evening=True)]),
    ("王伯伯", "1949-11-23", "male", ["冠心病（演示档案）"], ["青霉素（虚构过敏史）"], "日常活动记录与既定计划均待本人核对。", [medicine("a"), medicine("b", evening=True)]),
    ("赵阿姨", "1955-06-16", "female", ["脑卒中后遗症（演示档案）"], [], "虚构既往病史：左侧肢体活动不便，活动记录采用坐位伸展。", [medicine("a")]),
    ("刘伯伯", "1951-02-27", "male", ["慢性阻塞性肺疾病（演示档案）"], [], "虚构既往病史：慢性呼吸系统疾病，记录中无急性发作。", [medicine("a"), medicine("b", evening=True)]),
    ("周阿姨", "1959-07-05", "female", ["膝骨关节炎（演示档案）"], [], "膝部不适为虚构既往信息，尚未登记长期用药计划。", []),
    ("吴阿姨", "1954-12-11", "female", ["骨质疏松（演示档案）"], [], "预置有一项待核对的演示计划。", [medicine("a", after_meal=True)]),
    ("郑伯伯", "1957-04-20", "male", ["痛风（演示档案）"], [], "虚构既往病史：间歇关节不适，历史中无急性发作。", [medicine("a")]),
    ("何伯伯", "1950-08-14", "male", ["慢性肾脏病（演示档案）"], ["某演示药品（虚构过敏史）"], "未设置疾病分期或检验数值，既有信息待本人确认。", [medicine("a")]),
    ("孙阿姨", "1956-10-09", "female", ["高血压（演示档案）", "糖尿病（演示档案）"], [], "两项既定演示计划分别核对，可单独移除。", [medicine("a"), medicine("b", after_meal=True)]),
    ("许伯伯", "1948-01-30", "male", ["高血压（演示档案）", "糖尿病（演示档案）", "血脂异常（演示档案）"], [], "多病共存演示，三项计划均是静态虚构字段。", [medicine("a"), medicine("b", after_meal=True), medicine("c", evening=True)]),
    ("林阿姨", "1961-06-02", "female", [], [], "无已登记基础慢病或长期用药，用于演示空计划场景。", []),
]

SAMPLE_PROFILES: dict[str, dict] = {}
for index, (name, birthday, sex, conditions, allergies, notes, templates) in enumerate(_PEOPLE, 1):
    key = f"community_sample_{index:03d}"
    SAMPLE_PROFILES[key] = {
        "record_number": f"VS-DEMO-{index:03d}",
        "community_name": COMMUNITY_NAME,
        "profile": {"display_name": name, "birth_date": birthday, "sex": sex,
                    "conditions": conditions, "allergies": allergies,
                    "medical_notes": notes, "source": "community_mock"},
        "medication_templates": templates,
        "history_key": key,
        "history_medication": [
            {"plan_key": p["template_key"], "slot_id": s["slot_id"]}
            for p in templates for s in p["plan"]["schedule"]["slots"]
        ],
        "history_activity": "坐位伸展" if index in {5, 7, 8} else "散步",
        "history_minutes": 10 if index in {5, 6, 7, 8} else 20,
    }

EMPTY_DRAFT = {"display_name": "待完善", "birth_date": None, "sex": "unknown",
               "conditions": [], "allergies": [], "medical_notes": ""}


def match_sample(sample_identity_key: str) -> dict | None:
    """Legacy fixture reader; HTTP matching reads the persisted community table."""
    sample = SAMPLE_PROFILES.get(sample_identity_key)
    return deepcopy(sample) if sample else None
