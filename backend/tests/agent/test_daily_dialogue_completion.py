"""Daily conversation completion against real business ports, no paid calls."""
from datetime import datetime
from dataclasses import replace
import json

import pytest
from sqlalchemy import select

from test_f2_http import real_api, turn, upload, count
from test_http import api
from test_real_understanding import candidate, response
from app.contracts.context import Actor
from app.core.clock import HK
from app.core.errors import AppError
from app.core.uow import UnitOfWork
from app.models.agent import AgentTurn, AgentAction
from app.models.health import Checkin
from app.schemas.enums import Role
from app.schemas.health import CheckinUpdate


def saved(api):
    with api[0].state.sessions() as tx:
        row = tx.scalar(select(Checkin))
        return row.id, row.version, row.payload_json


@pytest.mark.parametrize('hour,minute,slot', [
    (4, 59, 'dinner'), (5, 0, 'breakfast'), (10, 59, 'breakfast'),
    (11, 0, 'lunch'), (16, 59, 'lunch'), (17, 0, 'dinner'), (23, 59, 'dinner'),
])
def test_spoken_meal_uses_server_local_time_and_saves_once(real_api, hour, minute, slot):
    api, captured = real_api
    target = datetime(2026, 10, 31, hour, minute, tzinfo=HK)
    api[2].advance(seconds=(target - api[2].now()).total_seconds())
    result = turn(api, text='我刚吃了青菜和豆腐。')
    assert result.status_code == 201, result.text
    data = result.json()['data']
    action = data['actions'][0]
    assert action['status'] == 'confirmed' and not action['requires_confirmation']
    assert action['preview']['meal_slot'] == slot and count(api, Checkin) == 1
    prompt = json.loads(captured.calls[-1].content)['messages'][0]['content']
    assert prompt.startswith(f'当前会话时间：2026-10-31 {hour:02}:{minute:02}:00')
    assert 'UTC+08:00' in prompt and '小孩形象的数字人' in prompt
    assert '不要反复要求“明确确认”' in prompt
    assert turn(api, text='我刚吃了青菜和豆腐。').json()['data'] == data
    assert count(api, Checkin) == 1 and len(captured.calls) == 1
    with api[0].state.sessions() as tx:
        assert tx.scalar(select(Checkin)).source == 'agent_confirmed'


def test_explicit_meal_wins_over_time_and_model(real_api):
    api, captured = real_api
    captured.handler = lambda request: response(candidate(meal_slot='dinner'))
    result = turn(api, text='今天早餐吃了青菜和豆腐。')
    assert result.status_code == 201, result.text
    assert saved(api)[2]['meal_slot'] == 'breakfast'


def test_partial_meal_keeps_initial_time_across_a_meal_boundary(real_api):
    api, captured = real_api
    target = datetime(2026, 10, 30, 16, 59, tzinfo=HK)
    api[2].advance(seconds=(target - api[2].now()).total_seconds())
    captured.handler = lambda request: response(candidate(intent='clarify', foods=[], food_groups=[]))
    first = turn(api, text='我刚吃饭了。').json()['data']
    assert first['actions'] == [] and count(api, Checkin) == 0
    api[2].advance(seconds=120)
    captured.handler = lambda request: response(candidate(foods=['豆腐'], meal_slot='dinner'))
    result = turn(api, key='food-detail', text='吃了豆腐。', conversation_id=first['conversation_id'])
    assert result.status_code == 201, result.text
    assert saved(api)[2]['meal_slot'] == 'lunch'
    prompt = json.loads(captured.calls[-1].content)['messages'][0]['content']
    assert '17:01:00' in prompt


def test_meal_fragment_photo_and_chitchat_share_one_task(real_api):
    api, captured = real_api
    first = turn(api, text='午餐').json()['data']
    captured.handler = lambda request: response(candidate(intent='chat', foods=[], food_groups=[], reply='我在呢，您慢慢说。'))
    chatting = turn(api, key='chitchat', text='你先别着急呀。', conversation_id=first['conversation_id'])
    assert chatting.status_code == 201 and count(api, Checkin) == 0
    captured.handler = lambda request: response(candidate(meal_slot=None))
    image = upload(api)
    result = turn(api, key='meal-photo', text=None, image_asset_ids=[image], context={'scene': 'meal'},
                  conversation_id=first['conversation_id'])
    assert result.status_code == 201, result.text
    data = result.json()['data']
    assert data['actions'][0]['status'] == 'confirmed' and count(api, Checkin) == 1
    assert saved(api)[2]['image_asset_ids'] == [image]
    messages = json.loads(captured.calls[-1].content)['messages']
    assert any(message.get('content') == '午餐' for message in messages)
    assert any(message.get('content') == '你先别着急呀。' for message in messages)
    sent = captured.calls[-1].content.decode()
    assert first['conversation_id'] not in sent and image not in sent


def test_known_foods_do_not_trigger_another_meal_question(real_api):
    api, captured = real_api
    captured.handler = lambda request: response(candidate(intent='clarify', meal_slot=None, reply='这是哪一餐？'))
    result = turn(api, text='这顿吃了青菜和豆腐。')
    assert result.status_code == 201, result.text
    data = result.json()['data']
    assert count(api, Checkin) == 1 and data['actions'][0]['status'] == 'confirmed'
    assert '哪一' not in data['reply']['text'] and '确认' not in data['reply']['text']


@pytest.mark.parametrize('with_draft', [False, True])
def test_meal_word_with_camera_frame_is_understood_immediately(real_api, with_draft):
    api, captured = real_api
    conversation = turn(api, text='午餐').json()['data']['conversation_id'] if with_draft else None
    image = upload(api)
    result = turn(api, key='frame-and-meal', text='午餐', image_asset_ids=[image], conversation_id=conversation)
    assert result.status_code == 201, result.text
    assert result.json()['data']['actions'][0]['status'] == 'confirmed'
    assert saved(api)[2]['image_asset_ids'] == [image] and len(captured.calls) == 1


def test_exercise_supplement_finishes_in_two_turns_without_model(real_api):
    api, captured = real_api
    first = turn(api, text='我散步了。').json()['data']
    assert first['actions'] == [] and '多久' in first['reply']['text']
    result = turn(api, key='duration', text='二十分钟。', conversation_id=first['conversation_id'])
    assert result.status_code == 201, result.text
    data = result.json()['data']
    assert data['actions'][0]['status'] == 'confirmed' and count(api, Checkin) == 1
    assert saved(api)[2]['activity'] == '散步' and saved(api)[2]['duration_minutes'] == 20
    assert not captured.calls
    assert all(word not in data['reply']['text'] for word in ('候选', '草稿', '业务', '确认'))


@pytest.mark.parametrize('duration,minutes', [('半小时', 30), ('一个半小时', 90), ('两小时', 120), ('一刻钟', 15)])
def test_conversational_exercise_durations(real_api, duration, minutes):
    api, captured = real_api
    result = turn(api, text=f'我散步了{duration}。')
    assert result.status_code == 201, result.text
    assert saved(api)[2]['duration_minutes'] == minutes and not captured.calls


def test_completed_meal_addition_and_correction_update_the_same_record(real_api):
    api, captured = real_api
    captured.handler = lambda request: response(candidate(foods=['青菜'], food_groups=['vegetable']))
    first = turn(api, text='我吃了青菜。').json()['data']
    original_id = saved(api)[0]
    captured.handler = lambda request: response(candidate(foods=['米饭'], food_groups=['staple']))
    extra = turn(api, key='add-food', text='还有一碗米饭。', conversation_id=first['conversation_id'])
    assert extra.status_code == 201, extra.text
    assert saved(api)[0:2] == (original_id, 2) and saved(api)[2]['foods'] == ['青菜', '米饭']
    corrected = turn(api, key='correct-meal', text='刚才那条改成晚餐。', conversation_id=first['conversation_id'])
    assert corrected.status_code == 201, corrected.text
    assert saved(api)[0:2] == (original_id, 3) and saved(api)[2]['meal_slot'] == 'dinner'
    assert count(api, Checkin) == 1 and len(captured.calls) == 2
    again = turn(api, key='correct-meal', text='刚才那条改成晚餐。', conversation_id=first['conversation_id'])
    assert again.json()['data'] == corrected.json()['data'] and saved(api)[1] == 3
    ack = turn(api, key='ack', text='好的。', conversation_id=first['conversation_id'])
    assert ack.status_code == 201 and ack.json()['data']['actions'] == [] and len(captured.calls) == 2


def test_completed_exercise_correction_does_not_create_another_record(real_api):
    api, captured = real_api
    first = turn(api, text='我散步了二十分钟。').json()['data']
    original_id = saved(api)[0]
    result = turn(api, key='correct-duration', text='刚才那次改成三十分钟。', conversation_id=first['conversation_id'])
    assert result.status_code == 201, result.text
    assert saved(api)[0:2] == (original_id, 2) and saved(api)[2]['duration_minutes'] == 30
    assert count(api, Checkin) == 1 and not captured.calls


def test_external_record_edit_rejects_stale_conversation_update(real_api):
    api, captured = real_api
    first = turn(api, text='我吃了青菜和豆腐。').json()['data']
    record_id, _, _ = saved(api)
    actor = Actor(api[3]['elder']['user_id'], Role.elder)
    with UnitOfWork(api[0].state.sessions) as unit:
        api[0].state.services.checkins.create_or_update(unit.session, actor, api[3]['elder']['elder_id'],
            CheckinUpdate(expected_version=1, payload={'meal_slot': 'lunch', 'foods': ['鱼']}), checkin_id=record_id)
        unit.commit()
    result = turn(api, key='stale-add', text='还有米饭。', conversation_id=first['conversation_id'])
    assert result.status_code == 409, result.text
    assert saved(api)[1] == 2 and saved(api)[2]['foods'] == ['鱼']
    assert count(api, AgentTurn) == count(api, AgentAction) == count(api, Checkin) == 1


def test_user_can_request_review_then_agree_naturally(real_api):
    api, captured = real_api
    first = turn(api).json()['data']
    assert first['actions'][0]['status'] == 'pending' and count(api, Checkin) == 0
    done = turn(api, key='agree', text='好呀。', image_asset_ids=[upload(api)], conversation_id=first['conversation_id'])
    assert done.status_code == 201, done.text
    assert done.json()['data']['actions'][0]['status'] == 'confirmed'
    assert count(api, Checkin) == 1 and len(captured.calls) == 1


@pytest.mark.parametrize('text', ['我准备吃豆腐。', '今天午餐还没吃。', '这个菜怎么做呀？'])
def test_planned_food_and_advice_are_not_saved_even_if_model_says_diet(real_api, text):
    api, _ = real_api
    result = turn(api, text=text)
    assert result.status_code == 201, result.text
    assert result.json()['data']['actions'] == [] and count(api, Checkin) == 0


def test_completed_record_context_is_not_reused_in_another_conversation(real_api):
    api, _ = real_api
    turn(api, text='我散步了二十分钟。')
    result = turn(api, key='separate', text='刚才那次改成三十分钟。', conversation_id='another-chat')
    assert result.status_code == 201 and result.json()['data']['actions'] == []
    assert count(api, Checkin) == 1 and saved(api)[1] == 1


def test_exercise_plan_cannot_complete_an_existing_draft(real_api):
    api, _ = real_api
    first = turn(api, text='我散步了。').json()['data']
    result = turn(api, key='future', text='还没散完，准备走二十分钟。', conversation_id=first['conversation_id'])
    assert result.status_code == 201 and result.json()['data']['actions'] == [] and count(api, Checkin) == 0


def test_automatic_business_failure_rolls_back_and_same_turn_can_retry(real_api):
    api, captured = real_api
    agent = api[0].state.agent
    bundle = agent.services
    class FailAfterWrite:
        def create_or_update(self, *args, source='user', **kwargs):
            bundle.checkins.create_or_update(*args, source=source, **kwargs)
            raise AppError(502, 'PROVIDER_ERROR', 'Explicit test business failure')
    agent.services = replace(bundle, checkins=FailAfterWrite())
    failed = turn(api, text='我吃了青菜和豆腐。')
    assert failed.status_code == 502, failed.text
    assert count(api, Checkin) == count(api, AgentTurn) == count(api, AgentAction) == 0
    agent.services = bundle
    retried = turn(api, text='我吃了青菜和豆腐。')
    assert retried.status_code == 201, retried.text
    assert count(api, Checkin) == 1 and len(captured.calls) == 2


def test_tts_failure_keeps_text_and_successful_daily_record(real_api):
    api, _ = real_api
    class FailedSpeech:
        name, is_mock = 'real', False
        def synthesize(self, text, voice_id=None):
            raise AppError(504, 'PROVIDER_TIMEOUT', 'Explicit test speech failure')
    api[0].state.agent_tts = FailedSpeech()
    result = turn(api, text='我吃了青菜和豆腐。')
    assert result.status_code == 201, result.text
    data = result.json()['data']
    assert data['actions'][0]['status'] == 'confirmed' and count(api, Checkin) == 1
    assert data['reply']['text'] and data['reply']['audio_asset_id'] is None
    assert data['degraded'] == ['tts_unavailable']


def test_uncertain_incidental_camera_frame_is_not_a_meal_record(real_api):
    api, captured = real_api
    captured.handler = lambda request: response(candidate(intent='clarify', reply='这是您想记的这顿饭吗？'))
    result = turn(api, text='看看这个。', image_asset_ids=[upload(api)])
    assert result.status_code == 201 and result.json()['data']['actions'] == [] and count(api, Checkin) == 0


def test_future_lifestyle_chat_can_still_receive_guidance(real_api):
    api, captured = real_api
    captured.handler = lambda request: response(candidate(intent='chat', foods=[], food_groups=[],
                                                          reply='明天想散步挺好呀，按自己的身体情况慢慢走。'))
    result = turn(api, text='明天想去公园走走。')
    assert result.status_code == 201, result.text
    assert result.json()['data']['scene'] == 'health_qa' and len(captured.calls) == 1 and count(api, Checkin) == 0


def test_past_exercise_is_not_silently_saved_as_today(real_api):
    api, captured = real_api
    captured.handler = lambda request: response(candidate(intent='exercise', activity='散步', duration_minutes=20))
    result = turn(api, text='昨天散步二十分钟。')
    assert result.status_code == 201 and result.json()['data']['actions'] == [] and count(api, Checkin) == 0
