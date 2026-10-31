"""Full proposal narration; pure rendering and exact, genuine speech fixtures.

No database/session, no provider or file work belongs in the change write UoW.
A supplies a current MedicationPlan from its short read for update/deactivate.
Unknown speech is text-only; no generic sentence can stand in for patch content.
"""
from __future__ import annotations

import hashlib
import io
import json
import wave
from pathlib import Path

from app.contracts.media import GeneratedAudio, SpokenNotice
from app.core.errors import AppError
from app.providers.mock_audio import Speech, TTSProvider
from app.schemas.health import MedicationPlan
from app.schemas.identity import ChangeProposalWrite

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "agent"
MEALS = {"breakfast": "早餐", "lunch": "午餐", "dinner": "晚餐"}
LABELS = {
    "display_name": "称呼", "birth_date": "出生日期", "sex": "性别",
    "conditions": "已确认疾病", "allergies": "过敏信息", "medical_notes": "医疗备注",
    "name": "药品名称", "dose_display": "每次用量", "schedule": "服药时间安排",
    "start_date": "开始日期", "end_date": "结束日期", "medicine_asset_id": "药品图片引用",
    "notes": "计划备注", "meals": "饮食提醒安排", "exercise": "运动提醒",
    "daily_summary": "每日总结提醒", "voice_enabled": "语音提醒",
}


def _quoted(value: str) -> str:
    # JSON quoting keeps user punctuation/newlines inside an explicit value.
    return json.dumps(value, ensure_ascii=False)


def _value(field: str, value) -> str:
    if value is None:
        return "清除该值"
    if field == "sex":
        return {"male": "男", "female": "女", "other": "其他", "unknown": "未知"}[value]
    if field == "schedule":
        parts = []
        for slot in value["slots"]:
            timing = (slot["local_time"] if value["mode"] == "fixed" else
                      f'{MEALS[slot["meal_slot"]]}后{slot["delay_minutes"]}分钟')
            parts.append(f'时段{_quoted(slot["slot_id"])}，{timing}')
        return "替换为以下全部时段：" + "；".join(parts)
    if field == "meals":
        return ("替换为以下全部饮食提醒：" + "；".join(
            f'{MEALS[row["slot"]]}，{_value("exercise", row)}' for row in value)
            if value else "清空全部饮食提醒")
    if field in {"exercise", "daily_summary"}:
        return f'{"开启" if value["enabled"] else "关闭"}，保存时间为{value["local_time"]}'
    if isinstance(value, bool):
        return "开启" if value else "关闭"
    if isinstance(value, list):
        return "、".join(_quoted(item) for item in value) if value else "清空列表"
    return _quoted(value) if value else "清空文字"


def proposal_text(body: ChangeProposalWrite, *, plan: MedicationPlan | None = None, is_mock: bool = True) -> str:
    """Narrate EVERY submitted field; no provider calls and no omitted nulls.

    Only replacement plan creation includes all defaults. Updates preserve the
    schema distinction between absent and explicitly cleared fields. A rechecks
    target/binding/base_version in its final write UoW after preparing audio.
    """
    if body.target_type == "profile":
        introduction = "孩子申请修改您的档案。"
    elif body.target_type == "reminder_settings":
        introduction = "孩子申请修改您的提醒设置。"
    elif body.operation == "create":
        introduction = "孩子申请新增以下用药计划。"
    else:
        if plan is None or plan.plan_id != body.target_id or plan.version != body.base_version:
            raise AppError(409, "VERSION_CONFLICT", "Narration requires the current target plan")
        verb = "停用" if body.operation == "deactivate" else "修改"
        introduction = (f'孩子申请{verb}用药计划，计划编号{_quoted(plan.plan_id)}，'
                        f'药品{_quoted(plan.name)}，原用量{_quoted(plan.dose_display)}。')
    patch = body.patch.model_dump(mode="json", exclude_unset=body.operation != "create")
    parts = [("【模拟】" if is_mock else "") + introduction]
    for key, value in patch.items():
        if key not in LABELS:
            raise AppError(501, "MODULE_NOT_IMPLEMENTED", f"No complete narration for field {key}")
        parts.append(f'{LABELS[key]}：{_value(key, value)}。')
    if body.reason:
        parts.append(f'申请原因：{_quoted(body.reason)}。')
    parts.append("以上是本次完整提案。完整播放结束后，您有60秒可以拒绝；也可以明确接受或拒绝。")
    return "".join(parts)


def prepare_proposal_notice(body: ChangeProposalWrite, *, tts: TTSProvider,
                            plan: MedicationPlan | None = None) -> tuple[str, SpokenNotice | None]:
    """Call OUTSIDE all UoWs. Return full text even if no matching speech exists.

    Missing fixture/known provider failure gives (text, None): A must save this
    full text without audio, preserve pending_notice, and never arm the window.
    Validation/unexpected exceptions propagate; mismatched speech is a hard error.
    """
    is_mock = bool(getattr(tts, 'is_mock', getattr(tts, 'name', 'mock') == 'mock'))
    text = proposal_text(body, plan=plan, is_mock=is_mock)
    try:
        speech = tts.synthesize(text)
    except AppError as exc:
        if (exc.status, exc.code) in {(501, "MODULE_NOT_IMPLEMENTED"),
                                           (502, "PROVIDER_ERROR"), (504, "PROVIDER_TIMEOUT")}:
            return text, None
        raise
    if bool(speech.is_mock) != is_mock:
        raise AppError(502, 'PROVIDER_ERROR', 'Proposal speech provenance differs from its provider')
    if speech.text != text or not speech.content or speech.duration_ms <= 0:
        raise AppError(502, "PROVIDER_ERROR", "Proposal speech does not match the complete text")
    return text, SpokenNotice(text, GeneratedAudio(speech.content, speech.mime_type, speech.duration_ms))


class ProposalFixtureTTS:
    """Five complete examples. Arbitrary changed values never get generic audio.

    Runtime is cross-platform: offline SAPI was used only to create versioned WAVs.
    This separate catalog does not expand mock ASR or promise arbitrary text TTS.
    """
    name = "mock"

    def synthesize(self, text: str, voice_id: str | None = None) -> Speech:
        if voice_id not in {None, "huihui_mock"}:
            raise AppError(422, "VALIDATION_ERROR", "Unknown mock voice")
        manifest = json.loads((FIXTURES / "proposal_manifest.json").read_text(encoding="utf-8-sig"))
        row = next((row for row in manifest if row["text"] == text), None)
        if row is None:
            raise AppError(501, "MODULE_NOT_IMPLEMENTED", "No exact full-proposal speech fixture")
        content = (FIXTURES / row["file"]).read_bytes()
        if hashlib.sha256(content).hexdigest() != row["sha256"]:
            raise AppError(502, "PROVIDER_ERROR", "Proposal fixture integrity check failed")
        with wave.open(io.BytesIO(content)) as reader:
            duration = reader.getnframes() * 1000 // reader.getframerate()
            complete = len(reader.readframes(reader.getnframes())) == reader.getnframes() * reader.getnchannels() * reader.getsampwidth()
            if (reader.getcomptype() != "NONE" or reader.getsampwidth() != 2 or
                    reader.getnchannels() != 1 or not complete or not 0 < duration <= 180_000):
                raise AppError(502, "PROVIDER_ERROR", "Invalid complete proposal speech")
        return Speech(content, "audio/wav", duration, text)
