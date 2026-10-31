"""Conversation regression tests: real planner, explicit HTTP seam, real A/B ports."""
from dataclasses import replace
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from test_f2_http import real_api, turn, upload, count
from test_http import api, hdr
from test_real_understanding import candidate, response
from app.core.uow import UnitOfWork
from app.core.errors import AppError
from app.contracts.context import Actor
from app.main import create_app
from app.models.agent import AgentAction, AgentTurn
from app.models.health import Checkin
from app.providers.real_understanding import RealUnderstanding
from app.providers.mock_audio import FIXTURES, Speech
from app.schemas.agent import ASRResult
from app.schemas.enums import Role
from app.schemas.health import MedicationPlanWrite, PlanPatch
import httpx


@pytest.mark.parametrize('spoken', ['确认。', '确认！', '好的，确认。', '请帮我确认这条记录。', '确认一下。'])
def test_asr_punctuation_and_camera_frame_do_not_hide_confirmation(real_api, spoken):
    api, captured = real_api
    pending = turn(api).json()['data']
    image = upload(api)
    done = turn(api, key='spoken-confirm', text=spoken, image_asset_ids=[image],
        conversation_id=pending['conversation_id'],
        context={'pending_action_id': pending['actions'][0]['action_id']})
    assert done.status_code == 201, done.text
    assert done.json()['data']['actions'][0]['status'] == 'confirmed'
    assert count(api, Checkin) == 1 and len(captured.calls) == 1


def test_photo_then_meal_slot_continues_saved_candidate_without_another_model(real_api):
    api, captured = real_api
    image = upload(api)
    first = turn(api, text=None, image_asset_ids=[image], context={'scene': 'meal'})
    assert first.status_code == 201, first.text
    draft = first.json()['data']
    assert draft['actions'] == [] and count(api, Checkin) == 0
    second = turn(api, key='meal-slot', text='午餐', conversation_id=draft['conversation_id'])
    assert second.status_code == 201, second.text
    action = second.json()['data']['actions'][0]
    assert action['preview']['image_asset_ids'] == [image]
    assert action['preview']['foods'] == ['青菜', '豆腐']
    assert action['status'] == 'pending' and len(captured.calls) == 1 and count(api, Checkin) == 0


def test_spoken_cancel_with_frame_is_idempotent_and_cannot_be_confirmed(real_api):
    api, captured = real_api
    pending = turn(api).json()['data']
    context = {'pending_action_id': pending['actions'][0]['action_id']}
    image = upload(api)
    kwargs = {'text': '取消。', 'image_asset_ids': [image], 'context': context,
              'conversation_id': pending['conversation_id']}
    cancelled = turn(api, key='cancel', **kwargs)
    assert cancelled.status_code == 201, cancelled.text
    assert cancelled.json()['data']['actions'][0]['status'] == 'cancelled'
    assert turn(api, key='cancel', **kwargs).json()['data'] == cancelled.json()['data']
    assert turn(api, key='cancel-again', **kwargs).json()['data']['actions'][0]['status'] == 'cancelled'
    failed = turn(api, key='after-cancel', text='确认。', context=context)
    assert failed.status_code == 409 and failed.json()['error']['code'] == 'ACTION_CANCELLED'
    assert count(api, Checkin) == 0 and len(captured.calls) == 1


@pytest.mark.parametrize('correction', ['改成晚餐。', '把这条改成晚餐。', '不是午餐，是晚餐。'])
def test_correction_replaces_pending_action_atomically_and_requires_new_confirmation(real_api, correction):
    api, captured = real_api
    image = upload(api)
    first = turn(api, image_asset_ids=[image]).json()['data']
    old_id = first['actions'][0]['action_id']
    revised = turn(api, key='revise', text=correction, image_asset_ids=[upload(api)],
        context={'pending_action_id': old_id}, conversation_id=first['conversation_id'])
    assert revised.status_code == 201, revised.text
    action = revised.json()['data']['actions'][0]
    assert action['action_id'] != old_id and action['status'] == 'pending'
    assert action['preview']['meal_slot'] == 'dinner' and action['preview']['image_asset_ids'] == [image]
    assert count(api, Checkin) == 0 and len(captured.calls) == 1
    with api[0].state.sessions() as tx:
        assert tx.get(AgentAction, old_id).status == 'cancelled'
    done = turn(api, key='confirm-revised', text='确认。',
        context={'pending_action_id': action['action_id']})
    assert done.status_code == 201, done.text
    with api[0].state.sessions() as tx:
        saved = tx.scalar(select(Checkin))
        assert saved.payload_json['meal_slot'] == 'dinner' and saved.source == 'agent_confirmed'


def test_food_correction_passes_only_authorized_candidate_and_keeps_original_media(real_api):
    api, captured = real_api
    image = upload(api)
    first = turn(api, image_asset_ids=[image]).json()['data']
    captured.handler = lambda request: response(candidate(foods=['鱼']))
    revised = turn(api, key='correct-food', text='更正，是鱼。', conversation_id=first['conversation_id'],
        context={'pending_action_id': first['actions'][0]['action_id']})
    assert revised.status_code == 201, revised.text
    action = revised.json()['data']['actions'][0]
    assert action['preview']['foods'] == ['鱼'] and action['preview']['image_asset_ids'] == [image]
    sent = captured.calls[-1].content.decode()
    assert '上轮待补充候选' in sent and image not in sent and first['conversation_id'] not in sent
    assert count(api, Checkin) == 0


@pytest.mark.parametrize('switch', ['取消。', '今天的日报'])
def test_cancel_or_task_switch_discards_diet_clarification(real_api, switch):
    api, captured = real_api
    first = turn(api, text=None, image_asset_ids=[upload(api)], context={'scene': 'meal'}).json()['data']
    changed = turn(api, key='switch', text=switch, conversation_id=first['conversation_id'])
    assert changed.status_code == 201, changed.text
    follow = turn(api, key='after-switch', text='午餐', conversation_id=first['conversation_id'])
    assert follow.status_code == 201, follow.text
    assert follow.json()['data']['actions'] == [] and len(captured.calls) == 1 and count(api, Checkin) == 0


def test_draft_does_not_leak_into_another_conversation(real_api):
    api, captured = real_api
    turn(api, text=None, image_asset_ids=[upload(api)], context={'scene': 'meal'})
    follow = turn(api, key='foreign-chat', text='午餐', conversation_id='a-different-conversation')
    assert follow.status_code == 201, follow.text
    assert follow.json()['data']['actions'] == [] and len(captured.calls) == 1


@pytest.mark.parametrize('draft_only', [False, True])
def test_expired_action_and_clarification_are_not_silently_reused(real_api, draft_only):
    api, captured = real_api
    first = turn(api, text=None, image_asset_ids=[upload(api)], context={'scene': 'meal'}).json()['data'] if draft_only else turn(api).json()['data']
    api[2].advance(seconds=601)
    follow = turn(api, key='after-expiry', text='午餐' if draft_only else '确认。', conversation_id=first['conversation_id'])
    if draft_only:
        assert follow.status_code == 201 and '过期' in follow.json()['data']['reply']['text']
        assert not follow.json()['data']['actions']
    else:
        assert follow.status_code == 409 and follow.json()['error']['code'] == 'ACTION_EXPIRED'
    assert count(api, Checkin) == 0 and len(captured.calls) == 1


def test_saved_draft_survives_app_restart_with_same_database(real_api):
    api, captured = real_api
    image = upload(api)
    first = turn(api, text=None, image_asset_ids=[image], context={'scene': 'meal'}).json()['data']
    restarted = create_app(api[0].state.settings, clock=api[2])
    restarted.state.agent_chat = RealUnderstanding(api_key='explicit-substitute', base_url='https://provider.test/v1',
        model='test', transport=httpx.MockTransport(lambda request: pytest.fail('Saved candidate must not be inferred again')))
    with TestClient(restarted, raise_server_exceptions=False) as client:
        follow = client.post('/api/v1/agent/turns', headers=hdr(api, 'restart'), json={
            'elder_id': api[3]['elder']['elder_id'], 'client_turn_id': 'restart',
            'conversation_id': first['conversation_id'], 'text': '午餐'})
    assert follow.status_code == 201, follow.text
    assert follow.json()['data']['actions'][0]['preview']['image_asset_ids'] == [image]
    assert len(captured.calls) == 1


def test_concurrent_same_conversation_change_rejects_stale_draft_merge(real_api):
    api, captured = real_api
    first = turn(api, text=None, image_asset_ids=[upload(api)], context={'scene': 'meal'}).json()['data']
    def concurrent(request):
        switched = turn(api, key='concurrent-switch', text='今天的日报', conversation_id=first['conversation_id'])
        assert switched.status_code == 201, switched.text
        return response(candidate(foods=['青菜', '豆腐']))
    captured.handler = concurrent
    stale = turn(api, key='stale', text='还有豆腐', conversation_id=first['conversation_id'])
    assert stale.status_code == 409 and stale.json()['error']['code'] == 'VERSION_CONFLICT'
    assert count(api, Checkin) == 0 and count(api, AgentTurn) == 2


@pytest.mark.parametrize('text', ['确认？', '不要确认', '我还没确认'])
def test_ambiguous_or_negative_confirmation_never_executes(real_api, text):
    api, captured = real_api
    first = turn(api).json()['data']
    captured.handler = lambda request: response(candidate(intent='chat', foods=[], food_groups=[], reply='请核对后明确决定。'))
    follow = turn(api, key='not-confirmed', text=text, conversation_id=first['conversation_id'],
        context={'pending_action_id': first['actions'][0]['action_id']})
    assert follow.status_code == 201 and count(api, Checkin) == 0


def test_foreign_frame_is_checked_even_for_confirmation(real_api):
    api, captured = real_api
    first = turn(api).json()['data']
    foreign = upload(api, owner='stranger_elder')
    result = turn(api, key='foreign-frame', text='确认。', image_asset_ids=[foreign],
        context={'pending_action_id': first['actions'][0]['action_id']})
    assert result.status_code in {403, 404} and count(api, Checkin) == 0 and len(captured.calls) == 1


def test_real_exercise_clarification_confirmation_and_report(real_api):
    api, captured = real_api
    first = turn(api, text='我散步了').json()['data']
    assert first['actions'] == []
    prepared = turn(api, key='minutes', text='二十分钟。', conversation_id=first['conversation_id'])
    assert prepared.status_code == 201, prepared.text
    action = prepared.json()['data']['actions'][0]
    assert action['type'] == 'record_exercise' and action['preview']['duration_minutes'] == 20
    done = turn(api, key='exercise-confirm', text='确认。', context={'pending_action_id': action['action_id']})
    assert done.status_code == 201, done.text
    report = turn(api, key='report', text='今天的日报')
    assert report.status_code == 201, report.text
    assert '运动记录 1/1' in report.json()['data']['reply']['text']
    assert report.json()['data']['providers']['chat'] == 'not_used' and not captured.calls
    assert count(api, Checkin) == 1


def test_binding_profile_and_explicit_memory_use_actual_ports(real_api):
    api, captured = real_api
    binding = turn(api, text='生成绑定码。')
    assert binding.status_code == 201 and binding.json()['data']['actions'][0]['status'] == 'confirmed'
    assert '绑定码是' in binding.json()['data']['reply']['text']
    profile = turn(api, key='profile', text='请叫我陈伯。').json()['data']
    action = profile['actions'][0]
    assert action['type'] == 'update_profile' and action['status'] == 'pending'
    done = turn(api, key='profile-confirm', text='确认。', context={'pending_action_id': action['action_id']})
    assert done.status_code == 201, done.text
    with api[0].state.sessions() as tx:
        actual = api[0].state.services.profile.read(tx, Actor(api[3]['elder']['user_id'], Role.elder), api[3]['elder']['elder_id'])
        assert actual.display_name == '陈伯'
    assert turn(api, key='preference', text='我喜欢清淡饮食').json()['data']['memory']['changed']
    remembered = turn(api, key='recall', text='我喜欢什么').json()['data']['reply']['text']
    assert '清淡饮食' in remembered and not captured.calls


@pytest.mark.parametrize('intent,scene', [('chat', 'health_qa'), ('ingredient', 'ingredient_advice')])
def test_real_general_chat_and_ingredient_advice_do_not_create_actions(real_api, intent, scene):
    api, captured = real_api
    captured.handler = lambda request: response(candidate(intent=intent, foods=[], food_groups=[], reply='可以聊聊您今天喜欢做的事情。'))
    result = turn(api, text='你好，陪我聊聊天', context={'scene': 'ingredient'} if intent == 'ingredient' else {})
    assert result.status_code == 201, result.text
    data = result.json()['data']
    assert data['scene'] == scene and data['providers']['chat'] == 'real' and not data['actions']
    assert count(api, Checkin) == 0 and count(api, AgentAction) == 0


def test_asr_transcript_with_frame_routes_confirmation_before_understanding(real_api):
    api, captured = real_api
    first = turn(api).json()['data']
    class RealASRSubstitute:
        name, is_mock = 'real', False
        def transcribe(self, audio, mime_type, fixture_id=None):
            return ASRResult(transcript='确认。', language='zh-CN', provider='real', is_mock=False)
    api[0].state.agent_asr = RealASRSubstitute()
    audio = api[1].post('/api/v1/media', headers=hdr(api, 'voice-upload'),
        data={'purpose': 'agent_audio', 'elder_id': api[3]['elder']['elder_id']},
        files={'file': ('confirm.wav', (FIXTURES / 'greeting.wav').read_bytes(), 'audio/wav')})
    assert audio.status_code == 201, audio.text
    result = turn(api, key='asr-confirm', text=None, audio_asset_id=audio.json()['data']['asset_id'],
        image_asset_ids=[upload(api)], context={'pending_action_id': first['actions'][0]['action_id']})
    assert result.status_code == 201, result.text
    data = result.json()['data']
    assert data['transcript'] == '确认。' and data['providers']['asr'] == 'real'
    assert data['actions'][0]['status'] == 'confirmed' and len(captured.calls) == 1


@pytest.mark.parametrize('scenario', ['single', 'ambiguous', 'changed'])
def test_real_medication_intake_requires_actual_due_task_and_stable_plan(real_api, scenario):
    api, captured = real_api
    app, _, clock, seed, _ = api
    actor = Actor(seed['elder']['user_id'], Role.elder)
    plans = []
    with UnitOfWork(app.state.sessions) as unit:
        for index in range(2 if scenario == 'ambiguous' else 1):
            plans.append(app.state.services.medication.apply_change(unit.session, actor, seed['elder']['elder_id'],
                'create', None, MedicationPlanWrite(name=f'既定药{index}', dose_display='用户既定用量',
                    schedule={'mode': 'fixed', 'slots': [{'slot_id': 'morning', 'local_time': '08:00'}]},
                    start_date='2026-10-31'), None))
        unit.commit()
    clock.advance(seconds=24 * 3600)
    prepared = turn(api, text='我吃药了。')
    assert prepared.status_code == 201, prepared.text
    data = prepared.json()['data']
    if scenario == 'ambiguous':
        assert not data['actions'] and '药品' in data['reply']['text']
        follow = turn(api, key='which-drug', text='既定药0，早上那次。', conversation_id=data['conversation_id'])
        assert follow.status_code == 201, follow.text
        chosen = follow.json()['data']['actions'][0]
        assert chosen['preview']['plan_id'] == plans[0].plan_id and chosen['status'] == 'pending'
        assert count(api, Checkin) == 0
    else:
        action = data['actions'][0]
        assert action['type'] == 'record_medication' and count(api, Checkin) == 0
        if scenario == 'changed':
            with UnitOfWork(app.state.sessions) as unit:
                app.state.services.medication.apply_change(unit.session, actor, seed['elder']['elder_id'],
                    'update', plans[0].plan_id, PlanPatch(notes='已修订的真实计划'), plans[0].version)
                unit.commit()
        confirmed = turn(api, key='medication-confirm', text='确认。', context={'pending_action_id': action['action_id']})
        assert confirmed.status_code == (409 if scenario == 'changed' else 201), confirmed.text
        assert count(api, Checkin) == (0 if scenario == 'changed' else 1)
    assert not captured.calls


def test_chat_keeps_bounded_same_actor_history_without_sending_action_results(real_api):
    api, captured = real_api
    captured.handler = lambda request: response(candidate(intent='chat', foods=[], food_groups=[], reply='我们可以聊聊公园。'))
    first = turn(api, text='我今天去了公园。').json()['data']
    second = turn(api, key='chat-follow', text='我刚才说去了哪里？', conversation_id=first['conversation_id'])
    assert second.status_code == 201, second.text
    messages = json.loads(captured.calls[-1].content)['messages']
    assert messages[1] == {'role': 'user', 'content': '我今天去了公园。'}
    assert messages[2] == {'role': 'assistant', 'content': '我们可以聊聊公园。'}
    assert first['conversation_id'] not in captured.calls[-1].content.decode()
    elsewhere = turn(api, key='another-chat', text='你好', conversation_id='separate-chat')
    assert elsewhere.status_code == 201
    assert len(json.loads(captured.calls[-1].content)['messages']) == 2


def test_real_proposal_formatter_uses_actual_provenance_and_preserves_full_text():
    from app.providers.proposal_notice import prepare_proposal_notice
    from app.schemas.identity import ProfileProposal
    captured = []
    class RealSpeechSubstitute:
        name, is_mock = 'real', False
        def synthesize(self, text):
            captured.append(text)
            return Speech((FIXTURES / 'greeting.wav').read_bytes(), 'audio/wav', 600, text, is_mock=False)
    body = ProfileProposal(target_type='profile', target_id='test-elder', operation='update',
                           base_version=1, patch={'medical_notes': '具体完整修改内容'})
    text, notice = prepare_proposal_notice(body, tts=RealSpeechSubstitute())
    assert '【模拟】' not in text and '具体完整修改内容' in text and notice is not None
    assert captured == [text]


def test_proposal_mock_audio_cannot_be_labelled_real():
    from app.providers.proposal_notice import prepare_proposal_notice
    from app.schemas.identity import ProfileProposal
    class WrongProvenance:
        name, is_mock = 'real', False
        def synthesize(self, text):
            return Speech(b'explicit-wrong-substitute', 'audio/wav', 600, text, is_mock=True)
    body = ProfileProposal(target_type='profile', target_id='test-elder', operation='update',
                           base_version=1, patch={'medical_notes': '具体完整修改内容'})
    with pytest.raises(AppError) as error:
        prepare_proposal_notice(body, tts=WrongProvenance())
    assert error.value.status == 502 and error.value.code == 'PROVIDER_ERROR'
