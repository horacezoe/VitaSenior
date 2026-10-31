"""Server-owned dialogue control and typed business plans, with no I/O.

Camera frames are data, never a reason to bypass an explicit control command.
Only the application/service can read ports or execute these plans.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import timedelta
from zoneinfo import ZoneInfo

from pydantic import TypeAdapter

from app.core.clock import local_date
from app.core.errors import AppError
from app.core.ids import new_id
from app.providers.planning import ConversationDraft, Plan, PlannedAction, request_digest
from app.schemas.agent import Action
from app.schemas.health import DietWrite, ExerciseWrite, MedicationWrite

MEALS = {'breakfast': ('早餐', '早饭'), 'lunch': ('午餐', '午饭'), 'dinner': ('晚餐', '晚饭')}
MEAL_NAMES = {'breakfast': '早餐', 'lunch': '午餐', 'dinner': '晚餐'}
CONFIRM = {'确认', '确认记录', '好的确认', '是的确认', '确认提交', '确认这条'}
CANCEL = {'取消', '取消记录', '取消这条', '不要记录', '不确认', '算了'}
CORRECTION = re.compile(r'^(?:更正|改成|改为|纠正|不是|不对|修改这条|修改记录|把这条|把这份)|(?:改成|改为|更正为|纠正为)')


def normalized(text):
    return ''.join(c for c in unicodedata.normalize('NFKC', text or '')
                   if not c.isspace() and not unicodedata.category(c).startswith('P'))


def meal_slots(text):
    return {slot for slot, words in MEALS.items() if any(word in text for word in words)}


def duration_minutes(text):
    found = re.search(r'([0-9零〇一二两三四五六七八九十百千]+)分钟', text)
    if not found:
        return None
    number = found.group(1)
    if number.isascii() and number.isdigit():
        value = int(number)
    else:
        digits = {'零': 0, '〇': 0, '一': 1, '二': 2, '两': 2, '三': 3, '四': 4, '五': 5,
                  '六': 6, '七': 7, '八': 8, '九': 9}
        value, current = 0, 0
        for char in number:
            if char in digits:
                current = digits[char]
            elif char in {'十', '百', '千'}:
                value += (current or 1) * {'十': 10, '百': 100, '千': 1000}[char]
                current = 0
            else:
                return None
        value += current
    if not 1 <= value <= 1440:
        raise AppError(422, 'VALIDATION_ERROR', 'Actual exercise duration must be within 1..1440 minutes')
    return value


def action(request, snapshot, kind, preview, execution, *, confirm=True, expires_at=None):
    public = TypeAdapter(Action).validate_python({
        'action_id': new_id('action'), 'type': kind,
        'status': 'pending' if confirm else 'confirmed', 'requires_confirmation': confirm,
        'expires_at': expires_at or snapshot.now + timedelta(minutes=10), 'preview': preview,
    })
    return PlannedAction(public, {'elder_id': request.elder_id, **execution})


def control_plan(request, snapshot, *, provider='not_used'):
    text = normalized(request.text)
    confirm = text in CONFIRM or bool(re.fullmatch(
        r'(?:好的|是的|对的)?(?:请)?(?:帮我)?确认(?:一下)?(?:提交|这条|这次|这份)?(?:记录|动作)?', text))
    cancel = text in CANCEL or bool(re.fullmatch(r'(?:请)?(?:帮我)?(?:取消|撤销)(?:一下)?(?:这条|这次|这份)?(?:记录|草稿|动作)?', text))
    if not confirm and not cancel:
        return None
    kind = 'confirm' if confirm else 'cancel'
    prefix = '【模拟】' if provider == 'mock' else ''
    def result(reply, **values):
        return Plan(request_digest(request), 'clarify', prefix + reply, chat_provider=provider, **values)
    if kind == 'confirm' and re.search(r'[?？]', request.text or ''):
        return result('请明确说“确认”或“取消”。', draft=snapshot.draft, active_action_id=snapshot.active_action_id)
    selected = request.context.pending_action_id
    if selected is None and len(snapshot.pending_action_ids) <= 1:
        selected = snapshot.active_action_id
    # Direct adapter tests may supply IDs without the persistence layer. Real
    # requests always receive a conversation revision; no cross-chat inference.
    if selected is None and snapshot.conversation_revision is None and request.conversation_id and len(snapshot.pending_action_ids) == 1:
        selected = snapshot.pending_action_ids[0]
    if selected is not None:
        known = snapshot.selected_action
        if known is not None and known.action.action_id == selected:
            status = known.action.status
            if (known.action.expires_at <= snapshot.now and status == 'pending') or status == 'expired':
                raise AppError(409, 'ACTION_EXPIRED', 'Action expired; please start a new request')
            if status == 'cancelled' and kind == 'confirm':
                raise AppError(409, 'ACTION_CANCELLED', 'Action was cancelled')
        elif selected not in snapshot.pending_action_ids:
            raise AppError(404, 'NOT_FOUND', 'Action unavailable in this conversation')
        reply = '已确认，业务服务已成功处理。' if kind == 'confirm' else '已取消，没有执行该动作。'
        return result(reply, decision_action_id=selected, decision_kind=kind)
    if snapshot.draft is not None:
        if kind == 'cancel':
            return result('已取消这份未完成草稿，没有写入健康记录。')
        return result('草稿尚未生成待确认动作，请先补充或核对内容。', draft=snapshot.draft)
    return result('请指定要' + ('确认' if kind == 'confirm' else '取消') + '的当前会话动作。')


def draft_plan(request, snapshot, draft, *, provider='not_used', supersede=None):
    if draft.expires_at <= snapshot.now:
        return Plan(request_digest(request), 'clarify', '上一份草稿已过期，请重新描述或发送餐食照片。', chat_provider=provider)
    if draft.kind == 'diet' and (not draft.foods or draft.meal_slot is None):
        reply = '请说明这次要记为早餐、午餐还是晚餐。' if draft.foods else '请补充这次实际吃的食物名称或清楚的餐食照片。'
        return Plan(request_digest(request), 'clarify', reply, chat_provider=provider, draft=draft,
                    supersede_action_id=supersede)
    if draft.kind == 'exercise' and (not draft.activity or draft.duration_minutes is None):
        return Plan(request_digest(request), 'clarify', '请补充实际完成的运动种类和时长（分钟）。',
                    chat_provider=provider, draft=draft, supersede_action_id=supersede)
    if draft.kind == 'diet':
        body = DietWrite(type='diet', occurred_at=draft.occurred_at, payload={
            'meal_slot': draft.meal_slot, 'foods': draft.foods, 'food_groups': draft.food_groups,
            'image_asset_ids': draft.image_asset_ids, 'notes': 'AI识别候选，经用户确认后记录'})
        reply = f'食物候选为{"、".join(draft.foods)}，要记为这次{MEAL_NAMES[draft.meal_slot]}吗？请核对后明确确认。'
        scene = 'meal_checkin'
    else:
        body = ExerciseWrite(type='exercise', occurred_at=draft.occurred_at, payload={
            'activity': draft.activity, 'duration_minutes': draft.duration_minutes, 'notes': '用户待确认'})
        reply, scene = f'要记下这次{draft.activity}{draft.duration_minutes}分钟吗？请明确确认。', 'exercise_checkin'
    prepared = action(request, snapshot, 'record_' + body.type, body.payload.model_dump(),
                      {'checkin': body.model_dump(mode='json')}, expires_at=draft.expires_at)
    return Plan(request_digest(request), scene, reply, (prepared,), chat_provider=provider,
                supersede_action_id=supersede)


def pending_draft(snapshot):
    selected = snapshot.selected_action
    if selected is None:
        return None
    public, payload = selected.action, selected.payload
    if public.status != 'pending' or public.expires_at <= snapshot.now:
        code = ('ACTION_CANCELLED' if public.status == 'cancelled' else
                'IDEMPOTENCY_CONFLICT' if public.status == 'confirmed' else 'ACTION_EXPIRED')
        raise AppError(409, code,
                       'Only a current pending action can be corrected')
    if public.type not in {'record_diet', 'record_exercise'}:
        return None  # Medication targets/doses cannot be revised by inference.
    checkin = payload['checkin']
    fields = {key: value for key, value in checkin['payload'].items()
              if key in ConversationDraft.model_fields}
    return ConversationDraft(kind=checkin['type'], occurred_at=checkin['occurred_at'],
                             expires_at=public.expires_at, **fields)


def report_day(text, now):
    compact = normalized(text)
    if re.fullmatch(r'(?:查看|查询|看看|给我|读一下)?(?:今天|今日|昨天|昨日)?(?:的)?(?:日报|报告|健康日报)', compact):
        return local_date(now) - timedelta(days=1 if '昨天' in compact or '昨日' in compact else 0)
    return None


def server_plan(request, snapshot):
    """Explicit business commands use actual ports, without fixture planning."""
    text = normalized(request.text)
    def result(scene, reply, *actions, **values):
        return Plan(request_digest(request), scene, reply, tuple(actions), chat_provider='not_used', **values)
    day = report_day(text, snapshot.now)
    if day is not None:
        return result('daily_query', snapshot.report_text or '将读取指定日期的真实日报。',
                      action(request, snapshot, 'query_report', {'date': day.isoformat()},
                             {'date': day.isoformat()}, confirm=False))
    if re.search(r'(绑定|配对)码|绑定家人|连接家人|家庭连接|家人连接', text):
        return result("clarify", "请结束通话后进入设置里的家庭连接，生成并分享绑定码。")
    if text in {'我喜欢什么', '我的偏好是什么', '你记得我的偏好吗', '你观察到什么规律'}:
        patterns = '规律' in text
        entries = [entry.text for entry in snapshot.memory.entries
                   if (entry.source_type == 'observed_pattern' if patterns else entry.kind == 'food_preference')]
        return result('health_qa', ('已保存：' + '；'.join(entries)) if entries else '目前没有这类已保存的有效记忆。')
    preference = re.fullmatch(r'我(?:喜欢|偏好|不喜欢)([^。！？!?]{1,80})[。！!]?\s*', request.text or '')
    if preference and not re.search(r'药|疾病|诊断|过敏|血糖|血压', preference.group(1)):
        return result('memory_update', '我会记住您明确表达的偏好。', preference=(request.text or '').strip())
    profile = re.fullmatch(r'(?:把我的称呼改成|把称呼改为|我的称呼改成|请叫我)(.{1,40})',
                           (request.text or '').strip().rstrip('。！!'))
    if profile:
        if snapshot.profile is None:
            return result('clarify', '请先完成个人档案。')
        update = {'expected_version': snapshot.profile.version, 'patch': {'display_name': profile.group(1)}}
        return result('profile_update', f'要把您的称呼改为{profile.group(1)}吗？请明确确认。',
                      action(request, snapshot, 'update_profile', update,
                             {'target_id': request.elder_id, 'update': update}))
    if text in {'拒绝修改', '取消修改', '接受修改'}:
        if snapshot.proposal_id is None:
            return result('clarify', '请先选择对应的修改通知。')
        data = {'proposal_id': snapshot.proposal_id, 'decision': 'accept' if text == '接受修改' else 'reject'}
        return result('reminder_response', '将处理您对这份提案的明确决定。',
                      action(request, snapshot, 'decide_change', data, data, confirm=False))
    if text in {'稍后', '等会', '稍后再提醒', '处理好了'}:
        if not request.context.notification_id:
            return result('clarify', '请先选择要处理的提醒。')
        event = {'event_id': new_id('event'), 'event_type': 'handled' if text == '处理好了' else 'snoozed'}
        if event['event_type'] == 'snoozed':
            event['snooze_minutes'] = 10
        return result('reminder_response', '将更新这条提醒的处理状态。', action(
            request, snapshot, 'respond_notification', {'notification_id': request.context.notification_id, **event},
            {'notification_id': request.context.notification_id, 'event': event}, confirm=False))
    return None


def medication_plan(request, snapshot):
    """Intake only: choose among actual due tasks; never create/change a plan."""
    text = normalized(request.text)
    intake = re.fullmatch(r'(?:我)?(?:已经|刚刚|刚才)?(?:吃了药|吃药了|服药了|服用了(.+)|吃了(.+))', text)
    draft = snapshot.draft if snapshot.draft is not None and snapshot.draft.kind == 'medication' else None
    if draft is not None and draft.expires_at <= snapshot.now:
        return Plan(request_digest(request), 'clarify', '服药记录草稿已过期，请重新核对并说明。', chat_provider='not_used')
    if draft is None and (not intake or not ('药' in text or '服用' in text or intake.group(1))):
        return None
    if draft is not None and intake is None and not any(name in text for name in snapshot.medication_names.values()) and not re.search(r'早上|上午|中午|下午|晚上|时段|药', text):
        return None
    draft = draft or ConversationDraft(kind='medication', occurred_at=snapshot.now,
                                       expires_at=snapshot.now + timedelta(minutes=10))
    tasks = [task for task in snapshot.tasks if task.category == 'medication' and task.plan_id and not task.cancelled
             and task.completion == 'pending' and task.date == local_date(snapshot.now)
             and task.due_at is not None and task.due_at <= draft.occurred_at and not task.waiting_for_meal]
    named = (intake.group(1) or intake.group(2)) if intake is not None else None
    if named:
        tasks = [task for task in tasks if named in task.title]
    elif any(name in text for name in snapshot.medication_names.values()):
        tasks = [task for task in tasks if snapshot.medication_names.get(task.task_id, '') in text]
    if re.search(r'早上|上午|中午|下午|晚上', text):
        def matches_time(task):
            hour = task.due_at.astimezone(ZoneInfo('Asia/Hong_Kong')).hour
            return (hour < 12 if re.search(r'早上|上午', text) else
                    11 <= hour < 14 if '中午' in text else 12 <= hour < 18 if '下午' in text else hour >= 18)
        tasks = [task for task in tasks if matches_time(task)]
    if len(tasks) != 1 or tasks[0].task_id not in snapshot.medication_slots:
        return Plan(request_digest(request), 'clarify', '请核对并说明药品及服药时段；我只记录已存在且到时的明确任务。',
                    chat_provider='not_used', draft=draft)
    task = tasks[0]
    body = MedicationWrite(type='medication', occurred_at=draft.occurred_at, task_id=task.task_id, payload={
        'plan_id': task.plan_id, 'slot_id': snapshot.medication_slots[task.task_id],
        'intake_status': 'taken', 'notes': '等待老人明确确认'})
    preview = {**body.payload.model_dump(), 'task_id': task.task_id}
    prepared = action(request, snapshot, 'record_medication', preview,
                      {'checkin': body.model_dump(mode='json'), 'task_plan_version': task.plan_version}, expires_at=draft.expires_at)
    return Plan(request_digest(request), 'medication_checkin', f'请确认已按既定计划服用了{task.title}，用量以已确认计划为准。',
                (prepared,), chat_provider='not_used')
