"""Full-content speech, not a cue or a category-only spoken sentence."""
import hashlib
import json
import pytest
from pydantic import TypeAdapter

from app.core.errors import AppError
from app.providers.mock_audio import Speech
from app.providers.proposal_notice import (
    FIXTURES, ProposalFixtureTTS, prepare_proposal_notice, proposal_text,
)
from app.schemas.health import MedicationPlan
from app.schemas.identity import ChangeProposalWrite


def cases():
    return json.loads((FIXTURES / 'proposal_cases.json').read_text(encoding='utf-8'))


def parse(case):
    body = TypeAdapter(ChangeProposalWrite).validate_python(case['body'])
    plan = MedicationPlan.model_validate(case['plan']) if 'plan' in case else None
    return body, plan


@pytest.mark.parametrize('case', cases(), ids=lambda case: case['fixture_id'])
def test_all_five_types_have_exact_full_content_speech(case):
    body, plan = parse(case)
    text, notice = prepare_proposal_notice(body, plan=plan, tts=ProposalFixtureTTS())
    assert notice is not None and notice.text == text
    manifest = json.loads((FIXTURES / 'proposal_manifest.json').read_text(encoding='utf-8-sig'))
    row = next(row for row in manifest if row['fixture_id'] == case['fixture_id'])
    assert row['text'] == proposal_text(body, plan=plan) == text
    assert hashlib.sha256(notice.audio.content).hexdigest() == row['sha256']
    assert notice.audio.content == (FIXTURES / row['file']).read_bytes()
    assert notice.audio.duration_ms > 5000 and notice.audio.mime_type == 'audio/wav'
    if body.operation == 'deactivate':
        assert plan.name in text and plan.plan_id in text and body.reason in text
    elif body.target_type == 'profile':
        assert body.patch.medical_notes in text
    elif body.target_type == 'reminder_settings':
        assert '运动提醒：关闭' in text and '17:00' in text and '语音提醒：关闭' in text
    elif body.operation == 'create':
        assert '演示药' in text and '一片' in text and '08:00' in text and '2026-10-31' in text
    else:
        assert '两片' in text and '晚餐后30分钟' in text and '结束日期：清除该值' in text


def test_different_actual_value_never_reuses_generic_or_other_proposal_audio():
    case = cases()[0]
    case['body']['patch']['medical_notes'] = '完全不同的一条新备注'
    body, _ = parse(case)
    text, notice = prepare_proposal_notice(body, tts=ProposalFixtureTTS())
    assert '完全不同的一条新备注' in text and notice is None


def test_all_profile_fields_and_explicit_clears_are_narrated():
    body = TypeAdapter(ChangeProposalWrite).validate_python({
        'target_type': 'profile', 'target_id': 'elder', 'operation': 'update', 'base_version': 1,
        'patch': {'display_name': '阿华', 'birth_date': None, 'sex': 'female',
                  'conditions': ['已确认疾病甲'], 'allergies': [], 'medical_notes': ''},
        'reason': '已与本人核对',
    })
    text = proposal_text(body)
    for value in ['阿华', '出生日期：清除该值', '性别：女', '已确认疾病甲',
                  '过敏信息：清空列表', '医疗备注：清空文字', '已与本人核对']:
        assert value in text
    partial = body.model_copy(update={'patch': body.patch.model_validate({'medical_notes': '单字段'})})
    assert '出生日期' not in proposal_text(partial) and '称呼' not in proposal_text(partial)


def test_full_settings_replacements_include_enabled_and_disabled_times():
    body = TypeAdapter(ChangeProposalWrite).validate_python({
        'target_type': 'reminder_settings', 'target_id': 'elder', 'operation': 'update', 'base_version': 1,
        'patch': {'meals': [{'slot': 'breakfast', 'enabled': True, 'local_time': '08:15'},
                            {'slot': 'dinner', 'enabled': False, 'local_time': '18:45'}],
                  'exercise': {'enabled': True, 'local_time': '16:00'},
                  'daily_summary': {'enabled': False, 'local_time': '21:30'}, 'voice_enabled': False},
    })
    text = proposal_text(body)
    for value in ['早餐', '08:15', '晚餐', '18:45', '运动提醒：开启', '16:00',
                  '每日总结提醒：关闭', '21:30', '语音提醒：关闭']:
        assert value in text


def test_plan_narration_rechecks_target_identity_and_version():
    body, plan = parse(cases()[3])
    for wrong in [None, plan.model_copy(update={'plan_id': 'foreign'}), plan.model_copy(update={'version': 2})]:
        with pytest.raises(AppError) as exc:
            proposal_text(body, plan=wrong)
        assert exc.value.status == 409


@pytest.mark.parametrize('status,code', [(501, 'MODULE_NOT_IMPLEMENTED'), (502, 'PROVIDER_ERROR'), (504, 'PROVIDER_TIMEOUT')])
def test_known_speech_failure_retains_complete_text_without_audio(status, code):
    class Failed:
        def synthesize(self, text):
            raise AppError(status, code, 'Explicit provider failure')
    body, _ = parse(cases()[0])
    text, notice = prepare_proposal_notice(body, tts=Failed())
    assert '补充社区复查记录' in text and notice is None


def test_mismatched_generic_sentence_is_never_accepted_as_full_speech():
    class Generic:
        def synthesize(self, text):
            return Speech(b'generic audio', 'audio/wav', 8000, '孩子帮您更新档案，请听取修改内容。')
    body, _ = parse(cases()[0])
    with pytest.raises(AppError) as exc:
        prepare_proposal_notice(body, tts=Generic())
    assert exc.value.status == 502


def test_unexpected_provider_failure_is_not_swallowed():
    class Broken:
        def synthesize(self, text):
            raise RuntimeError('unexpected bug')
    body, _ = parse(cases()[0])
    with pytest.raises(RuntimeError, match='unexpected bug'):
        prepare_proposal_notice(body, tts=Broken())
