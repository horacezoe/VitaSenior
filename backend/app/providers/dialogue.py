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
AGREE = {'好', '好的', '好呀', '好啊', '嗯', '嗯嗯', '是', '是的', '对', '对的', '没错', '就这样', '就这些', '记吧', '记上吧', '帮我记上', '是我吃的'}
CANCEL = {'取消', '取消记录', '取消这条', '不要记录', '不确认', '算了', '算啦', '不用记了', '不记了', '别记了', '不要记了', '不要保存'}
CORRECTION = re.compile(r'^(?:更正|改成|改为|纠正|不是|不对|修改这条|修改记录|把这条|把这份)|(?:改成|改为|更正为|纠正为)')


def normalized(text):
    return ''.join(c for c in unicodedata.normalize('NFKC', text or '')
                   if not c.isspace() and not unicodedata.category(c).startswith('P'))


def meal_slots(text):
    return {slot for slot, words in MEALS.items() if any(word in text for word in words)}


def meal_at(now):
    """A default for this meal, in the project's business timezone (UTC+8)."""
    hour = now.astimezone(ZoneInfo('Asia/Hong_Kong')).hour
    return 'breakfast' if 5 <= hour < 11 else 'lunch' if 11 <= hour < 17 else 'dinner'


def review_requested(text):
    return bool(re.search(r'先.{0,5}(?:别|不要|不|不用|暂不).{0,3}(?:记|存)|(?:核对|确认)(?:后|再)(?:记|保存)|先(?:让我)?核对', normalized(text)))


def duration_minutes(text):
    if '一刻钟' in text:
        return 15
    found = re.search(r'([0-9零〇一二两三四五六七八九十百千]+)(?:个)?(半小时|小时|分钟)', text)
    if not found:
        return 30 if '半小时' in text else None
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
    if found.group(2) != '分钟':
        value = value * 60 + (30 if found.group(2) == '半小时' else 0)
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
    has_target = snapshot.selected_action is not None or snapshot.active_action_id is not None or snapshot.draft is not None
    confirm = text in CONFIRM or (has_target and text in AGREE) or bool(re.fullmatch(
        r'(?:好的|是的|对的)?(?:请)?(?:帮我)?确认(?:一下)?(?:提交|这条|这次|这份)?(?:记录|动作)?', text))
    cancel = text in CANCEL or bool(re.fullmatch(r'(?:请)?(?:帮我)?(?:取消|撤销)(?:一下)?(?:这条|这次|这份)?(?:记录|草稿|动作)?', text))
    if not confirm and not cancel:
        return None
    kind = 'confirm' if confirm else 'cancel'
    prefix = '【模拟】' if provider == 'mock' else ''
    def result(reply, **values):
        return Plan(request_digest(request), 'clarify', prefix + reply, chat_provider=provider, **values)
    if kind == 'confirm' and re.search(r'[?？]', request.text or ''):
        return result('您核对好了再告诉我就行，不想记也没关系。', draft=snapshot.draft, active_action_id=snapshot.active_action_id)
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
        reply = '好呀，已经帮您记好了。' if kind == 'confirm' else '好，那这条就不记了。'
        return result(reply, decision_action_id=selected, decision_kind=kind)
    if snapshot.draft is not None:
        if kind == 'cancel':
            return result('好，那这次就不记了。')
        if provider != 'mock' and snapshot.draft.kind in {'diet', 'exercise'}:
            draft = snapshot.draft
            if draft.kind == 'diet' and draft.meal_slot is None:
                draft = draft.model_copy(update={'meal_slot': meal_at(draft.occurred_at)})
            return draft_plan(request, snapshot, draft, provider=provider, auto_record=True)
        return result('还差一点信息，您接着说就好。', draft=snapshot.draft)
    return result('这会儿没有等着处理的记录，您想记什么直接告诉我就好。')


def draft_plan(request, snapshot, draft, *, provider='not_used', supersede=None, auto_record=False):
    if draft.expires_at <= snapshot.now:
        return Plan(request_digest(request), 'clarify', '刚才那次已经隔了一会儿啦，您再跟我说说这次要记的吧。', chat_provider=provider)
    if draft.kind == 'diet' and (not draft.foods or draft.meal_slot is None):
        reply = '这是哪一顿饭呀？' if draft.foods else '这顿吃了些什么呀？说给我听，或者把饭菜给我看看就行。'
        return Plan(request_digest(request), 'clarify', reply, chat_provider=provider, draft=draft,
                    supersede_action_id=supersede)
    if draft.kind == 'exercise' and (not draft.activity or draft.duration_minutes is None):
        reply = '大概动了多久呀？' if draft.activity else '做了什么运动呀？'
        return Plan(request_digest(request), 'clarify', reply,
                    chat_provider=provider, draft=draft, supersede_action_id=supersede)
    if draft.kind == 'diet':
        summary = '、'.join(food[:20] for food in draft.foods[:4]) + ('等' if len(draft.foods) > 4 else '')
        body = DietWrite(type='diet', occurred_at=draft.occurred_at, payload={
            'meal_slot': draft.meal_slot, 'foods': draft.foods, 'food_groups': draft.food_groups,
            'image_asset_ids': draft.image_asset_ids, 'notes': '日常对话记录'})
        reply = (f'好呀，{MEAL_NAMES[draft.meal_slot]}吃了{summary}，我帮您记下啦。' if auto_record else
                 f'我听到的是{MEAL_NAMES[draft.meal_slot]}吃了{summary}，这样记对吗？')
        scene = 'meal_checkin'
    else:
        body = ExerciseWrite(type='exercise', occurred_at=draft.occurred_at, payload={
            'activity': draft.activity, 'duration_minutes': draft.duration_minutes, 'notes': '日常对话记录'})
        reply = (f'{draft.activity}了{draft.duration_minutes}分钟，真不错，我帮您记好啦。' if auto_record else
                 f'这次{draft.activity}{draft.duration_minutes}分钟，这样记对吗？')
        scene = 'exercise_checkin'
    execution = {'checkin': body.model_dump(mode='json')}
    if draft.checkin_id:
        execution.update(checkin_id=draft.checkin_id, checkin_version=draft.checkin_version)
    prepared = action(request, snapshot, 'record_' + body.type, body.payload.model_dump(),
                      execution, confirm=not auto_record, expires_at=draft.expires_at)
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
                             expires_at=public.expires_at, review_before_save=True,
                             checkin_id=payload.get('checkin_id'), checkin_version=payload.get('checkin_version'), **fields)


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
        return result('health_qa', ('我记得：' + '；'.join(entries)) if entries else '您可以跟我说说平时的喜好，我帮您记着。')
    preference = re.fullmatch(r'我(?:喜欢|偏好|不喜欢)([^。！？!?]{1,80})[。！!]?\s*', request.text or '')
    if preference and not re.search(r'药|疾病|诊断|过敏|血糖|血压', preference.group(1)):
        return result('memory_update', '好呀，我记住您的喜好啦。', preference=(request.text or '').strip())
    profile = re.fullmatch(r'(?:把我的称呼改成|把称呼改为|我的称呼改成|请叫我)(.{1,40})',
                           (request.text or '').strip().rstrip('。！!'))
    if profile:
        if snapshot.profile is None:
            return result('clarify', '请先完成个人档案。')
        update = {'expected_version': snapshot.profile.version, 'patch': {'display_name': profile.group(1)}}
        return result('profile_update', f'以后就叫您{profile.group(1)}，对吗？',
                      action(request, snapshot, 'update_profile', update,
                             {'target_id': request.elder_id, 'update': update}))
    if text in {'拒绝修改', '取消修改', '接受修改'}:
        if snapshot.proposal_id is None:
            return result('clarify', '请先选择对应的修改通知。')
        data = {'proposal_id': snapshot.proposal_id, 'decision': 'accept' if text == '接受修改' else 'reject'}
        return result('reminder_response', '好，我帮您处理这次修改。',
                      action(request, snapshot, 'decide_change', data, data, confirm=False))
    if text in {'稍后', '等会', '稍后再提醒', '处理好了'}:
        if not request.context.notification_id:
            return result('clarify', '请先选择要处理的提醒。')
        event = {'event_id': new_id('event'), 'event_type': 'handled' if text == '处理好了' else 'snoozed'}
        if event['event_type'] == 'snoozed':
            event['snooze_minutes'] = 10
        return result('reminder_response', '好，过十分钟再提醒您。' if event['event_type'] == 'snoozed' else '好，这条提醒已经处理好啦。', action(
            request, snapshot, 'respond_notification', {'notification_id': request.context.notification_id, **event},
            {'notification_id': request.context.notification_id, 'event': event}, confirm=False))
    return None


def risk_requested(text):
    return bool(re.search(r'冲突|相互作用|风险|禁忌|副作用|能.{0,5}一起|一起.{0,5}(?:吃|服)|能不能吃|可不可以吃', normalized(text)))


def risk_summary_requested(text):
    """A request to read today's assessment, without new medical facts."""
    if not risk_requested(text):return False
    words=('我','我的','今天','今日','当日','现在','目前','这些','这几种','用药','药物','药','和','与','食物','饮食','膳食','的','里','有','没有','有没有','会不会','有无','需要','核对','潜在','相互作用','冲突','风险','副作用','禁忌','吗','呢','什么','哪些','会','是否','存在','一下','帮我','查','查看','看','检查','看看','请','能否','给我','说说')
    rest=re.sub('|'.join(re.escape(w) for w in sorted(words,key=len,reverse=True)), '', normalized(text))
    return not rest


def intake_spoken(text):
    """Speech evidence only; camera/model cannot assert ingestion."""
    if re.search(r'[?？]', text or ''):return False
    text = normalized(text)
    if re.search(r'还没|没(?:有)?(?:吃|服|吞)|未(?:曾)?(?:吃|服)|不(?:要|用|吃|服|想)|别|准备|打算|想|等会|待会|要不要|吗|么|能否|能不能|可以|不确定|记不清', text):
        return False
    return bool(re.search(r'(?:吃|服用|服下|服|吞)(?:了|过|完)|(?:吃药|服药)(?:了|过|完)|(?:药|片|胶囊)(?:已经|刚刚|都)?(?:吃|服用|服)(?:了|过|完)', text))


def medication_plan(request, snapshot):
    """Resolve today's actual plan slots; reminders do not gate intake facts."""
    text = normalized(request.text)
    if risk_requested(request.text or ''):
        return None
    known = {name for name in snapshot.medication_names.values() if name}
    drug_cue = bool(re.search(r'药|服用|服下|胶囊', text)) or any(name in text for name in known)
    intake = intake_spoken(request.text or '') and drug_cue
    draft = snapshot.draft if snapshot.draft is not None and snapshot.draft.kind == 'medication' else None
    if draft is not None and draft.expires_at <= snapshot.now:
        return Plan(request_digest(request), 'clarify', '刚才那次隔了一会儿啦，咱们重新核对一下吃的是哪种药吧。', chat_provider='not_used')
    if not intake and draft is None:
        return None
    if draft is not None and not intake and not drug_cue and not re.search(r'早上|上午|中午|下午|晚上|早餐|早饭|午餐|午饭|晚餐|晚饭', text):
        return None
    if draft is not None and re.search(r'没|未|不吃|不服|打算|准备|想', text):
        return Plan(request_digest(request), 'clarify', '好，先不记服药。等您实际服用后，再一起核对。', chat_provider='not_used')
    draft = draft or ConversationDraft(kind='medication', occurred_at=snapshot.now,
                                       expires_at=snapshot.now + timedelta(minutes=10))
    all_tasks = [t for t in snapshot.tasks if t.category == 'medication' and t.plan_id and not t.cancelled
                 and t.date == local_date(snapshot.now)]
    named = [name for name in known if name in text]
    if not named and draft.medication_name in known:
        named = [draft.medication_name]
    if len(named) == 1:
        draft = draft.model_copy(update={'medication_name': named[0]})
    # If no known name matches but a specific medicine was spoken, do not
    # silently bind it to the sole unrelated plan.
    generic = re.sub(r'(?:请|帮我|给我|记录|记下|打卡|一下|已经|刚刚|刚才|今天|早上|上午|中午|下午|晚上|那次|的|我|都|药|吃|服用|服下|吞|了|过|完|饭后|饭前|按时|按原计划|按计划|这次|那颗|那片|好了|把|服)', '', text)
    if not named and intake and generic:
        return Plan(request_digest(request), 'clarify', '这次药名还没和既定计划对上。请说完整药名，再到用药计划核对；我先不记录。', chat_provider='not_used', draft=draft)
    tasks = [t for t in all_tasks if not named or snapshot.medication_names.get(t.task_id) in named]
    period = ('breakfast' if re.search(r'早上|上午|早餐|早饭', text) else
              'lunch' if re.search(r'中午|午餐|午饭', text) else
              'afternoon' if '下午' in text else 'dinner' if re.search(r'晚上|晚餐|晚饭', text) else None)
    if period:
        def matches_time(task):
            detail = snapshot.medication_slot_details.get(task.task_id, {})
            if 'meal_slot' in detail:
                return detail['meal_slot'] == period
            clock = detail.get('local_time')
            hour = int(clock[:2]) if clock else task.due_at.astimezone(ZoneInfo('Asia/Hong_Kong')).hour if task.due_at else None
            if hour is None:return False
            return hour < 12 if period == 'breakfast' else 11 <= hour < 14 if period == 'lunch' else 12 <= hour < 18 if period == 'afternoon' else hour >= 18
        tasks = [t for t in tasks if matches_time(t)]
    # Actual intake may precede its reminder or an unrecorded meal. Only
    # occurrence time (not future), ownership, slot and confirmation gate writes.
    eligible = [t for t in tasks if t.completion == 'pending']
    def clarify(reply, *, keep=True):
        return Plan(request_digest(request), 'clarify', reply, chat_provider='not_used', draft=draft if keep else None)
    if not all_tasks:
        return clarify('今天还没有生效的用药任务。请到用药计划核对药名和起止日期，我先不替您记录。', keep=False)
    if not eligible and tasks and all(t.completion != 'pending' for t in tasks):
        return clarify('这次用药已有记录，我不会重复记。需要更正的话，请到用药记录核对。', keep=False)
    if len(eligible) == 1 and eligible[0].task_id not in snapshot.medication_slots:
        return clarify('这次任务与当前用药计划的版本不一致，请到用药计划和记录页面核对，我先不记录。', keep=False)
    if len(eligible) != 1 or len(tasks) > 1:
        def label(task):
            detail = snapshot.medication_slot_details.get(task.task_id, {})
            when = detail.get('local_time') or MEAL_NAMES.get(detail.get('meal_slot'), '')
            return snapshot.medication_names.get(task.task_id, task.title) + (f'（{when}那次）' if when else '')
        choices = '、'.join(dict.fromkeys(label(t) for t in tasks))
        return clarify('您吃的是哪种药呀？也跟我说说是早上还是晚上的那次。' + (f'待核对的有：{choices[:100]}。' if choices else ''))
    task = eligible[0]
    body = MedicationWrite(type='medication', occurred_at=draft.occurred_at, task_id=task.task_id, payload={
        'plan_id': task.plan_id, 'slot_id': snapshot.medication_slots[task.task_id],
        'intake_status': 'taken', 'notes': '老人明确确认的实际服药记录'})
    preview = {**body.payload.model_dump(), 'task_id': task.task_id}
    prepared = action(request, snapshot, 'record_medication', preview,
                      {'checkin': body.model_dump(mode='json'), 'task_plan_version': task.plan_version}, expires_at=draft.expires_at)
    return Plan(request_digest(request), 'medication_checkin',
                f'您已经吃了{task.title}，我帮您记今天这一次，对吗？' + (' 提醒时间不用再等，记好后不会再提醒您吃这一次。' if task.waiting_for_meal or (task.due_at and task.due_at > draft.occurred_at) else ''),
                (prepared,), chat_provider='not_used')
