from dataclasses import replace
from datetime import date, timedelta

import pytest
from sqlalchemy import select, func

from app.core.errors import AppError
from app.models.agent import AgentTurn, AgentAction, MemoryDocument
from app.models.health import Checkin, DailyTask, MedicationPlan
from app.schemas.agent import AgentTurnWrite, ActionDecision


def body(h,fixture='exercise_walk',client='client1',**kwargs):
    return AgentTurnWrite(elder_id=h.elder_id,client_turn_id=client,text='我散步了20分钟',mock_fixture_id=fixture,**kwargs)


def count(h,model):
    with h.tx(write=False) as tx:return tx.scalar(select(func.count()).select_from(model))


def test_pending_confirm_once_and_turn_retry(h):
    request=body(h)
    turn=h.turn(request)
    action_id=turn.actions[0].action_id
    assert turn.actions[0].status=='pending' and count(h,Checkin)==0
    assert h.turn(request)==turn and count(h,AgentAction)==1
    with pytest.raises(AppError) as exc:h.turn(request.model_copy(update={'text':'改为40分钟'}))
    assert exc.value.code=='IDEMPOTENCY_CONFLICT'
    with h.tx() as tx:confirmed=h.agent.decide(tx,h.actor(),action_id,ActionDecision(decision='confirm'))
    with h.tx() as tx:again=h.agent.decide(tx,h.actor(),action_id,ActionDecision(decision='confirm',amendments=None))
    assert confirmed==again and count(h,Checkin)==1 and h.tools.calls==1
    assert confirmed.result.source=='agent_confirmed'
    with pytest.raises(AppError):
        with h.tx() as tx:h.agent.decide(tx,h.actor(),action_id,ActionDecision(decision='confirm',amendments={'activity':'walk','duration_minutes':40}))


def test_confirmation_can_amend_matching_payload_only(h):
    turn=h.turn(body(h))
    action=turn.actions[0].action_id
    with pytest.raises(AppError):
        with h.tx() as tx:h.agent.decide(tx,h.actor(),action,ActionDecision(decision='confirm',amendments={'meal_slot':'lunch','foods':['rice']}))
    with h.tx() as tx:
        result=h.agent.decide(tx,h.actor(),action,ActionDecision(decision='confirm',amendments={'activity':'walk','duration_minutes':25}))
        assert result.result.payload.duration_minutes==25


def test_failed_tool_write_rolls_back_and_action_stays_pending(h):
    turn=h.turn(body(h))
    h.tools.fail_after_write=True
    with pytest.raises(AppError):
        with h.tx() as tx:h.agent.decide(tx,h.actor(),turn.actions[0].action_id,ActionDecision(decision='confirm'))
    assert count(h,Checkin)==0
    with h.tx(write=False) as tx:
        row=tx.get(AgentAction,turn.actions[0].action_id)
        assert row.status=='pending' and row.result_json is None
    h.tools.fail_after_write=False
    with h.tx() as tx:h.agent.decide(tx,h.actor(),turn.actions[0].action_id,ActionDecision(decision='confirm'))
    assert count(h,Checkin)==1


def test_cancel_and_clock_expiry(h):
    turn=h.turn(body(h))
    action=turn.actions[0].action_id
    with h.tx() as tx:cancel=h.agent.decide(tx,h.actor(),action,ActionDecision(decision='cancel'))
    with h.tx() as tx:assert h.agent.decide(tx,h.actor(),action,ActionDecision(decision='cancel'))==cancel
    with pytest.raises(AppError) as exc:
        with h.tx() as tx:h.agent.decide(tx,h.actor(),action,ActionDecision(decision='confirm'))
    assert exc.value.code=='ACTION_CANCELLED'
    turn=h.turn(body(h,client='expires'))
    h.clock.advance(seconds=601)
    with pytest.raises(AppError) as exc:
        with h.tx() as tx:h.agent.decide(tx,h.actor(),turn.actions[0].action_id,ActionDecision(decision='confirm'))
    assert exc.value.code=='ACTION_EXPIRED' and count(h,Checkin)==0


def test_unique_next_turn_confirmation_and_multiple_actions_clarify(h):
    first=h.turn(body(h,conversation_id='conversation'))
    # Two pending actions in the same conversation require explicit selection.
    second=h.turn(body(h,client='second',conversation_id='conversation'))
    confirm=AgentTurnWrite(elder_id=h.elder_id,client_turn_id='confirm',conversation_id='conversation',text='确认')
    ambiguous=h.turn(confirm)
    assert ambiguous.scene=='clarify' and count(h,Checkin)==0
    selected=confirm.model_copy(update={'client_turn_id':'selected','context':confirm.context.model_copy(update={'pending_action_id':first.actions[0].action_id})})
    done=h.turn(selected)
    assert done.actions[0].status=='confirmed' and count(h,Checkin)==1
    assert h.turn(selected)==done and h.tools.calls==1


def test_other_elder_action_conversation_and_media_references_denied(h):
    turn=h.turn(body(h,conversation_id='private-conversation'))
    stranger=h.actor('stranger_elder')
    with pytest.raises(AppError) as exc:
        with h.tx() as tx:h.agent.decide(tx,stranger,turn.actions[0].action_id,ActionDecision(decision='confirm'))
    assert exc.value.status==404
    foreign=AgentTurnWrite(elder_id=h.seed['stranger_elder']['elder_id'],client_turn_id='foreign',conversation_id='private-conversation',text='hello')
    with pytest.raises(AppError):h.turn(foreign,actor=stranger)
    with pytest.raises(AppError):h.turn(body(h,image_asset_ids=['foreign-asset']))
    with pytest.raises(AppError) as exc:h.turn(body(h,audio_asset_id='owned-image'))
    assert exc.value.status==415
    assert count(h,Checkin)==0


def test_model_failure_and_stale_memory_snapshot_leave_no_partial_writes(h):
    with pytest.raises(AppError):h.turn(body(h,'provider_timeout'))
    assert count(h,AgentTurn)==count(h,AgentAction)==count(h,Checkin)==0
    request=body(h)
    with h.tx(write=False) as tx:snapshot=h.agent.read_snapshot(tx,h.actor(),request)
    plan=h.provider.plan(request,snapshot)
    preference=body(h,'explicit_preference','preference')
    h.turn(preference)
    with pytest.raises(AppError) as exc:
        with h.tx() as tx:h.agent.record_turn(tx,h.actor(),request,snapshot,plan)
    assert exc.value.code=='VERSION_CONFLICT' and count(h,AgentAction)==0


def test_preference_across_conversations_does_not_become_a_pattern(h):
    first=h.turn(body(h,'explicit_preference','pref',conversation_id='one'))
    assert first.memory.changed
    query=AgentTurnWrite(elder_id=h.elder_id,client_turn_id='query',conversation_id='two',text='你好')
    with h.tx(write=False) as tx:
        snapshot=h.agent.read_snapshot(tx,h.actor(),query)
        assert '喜欢清淡饮食' in snapshot.memory.markdown
        assert all(e.source_type=='explicit_statement' for e in snapshot.memory.entries)
    h.turn(query)
    assert count(h,MemoryDocument)==1
    h.turn(body(h,'meal_lunch','meal'))
    with h.tx(write=False) as tx:
        assert len(h.agent.read_snapshot(tx,h.actor(),query).memory.entries)==1


def test_existing_stub_is_never_swallowed_as_a_tool_success(h):
    # B is now implemented on integration/f1. Inject an explicit missing-port
    # test double to retain this failure/rollback assertion without freezing B.
    class MissingReport:
        def daily(self,*args):
            raise AppError(501,'MODULE_NOT_IMPLEMENTED','Explicit missing B test port')
    h.agent.services=replace(h.agent.services,reports=MissingReport())
    with pytest.raises(AppError) as exc:h.turn(body(h,'daily_query'))
    assert exc.value.status==501 and count(h,AgentTurn)==count(h,AgentAction)==0
    turn=h.turn(body(h,'binding_code','binding'))
    assert turn.actions[0].status=='confirmed' and h.binding.calls==1
    assert '0012' in turn.reply.text
    assert h.turn(body(h,'binding_code','binding'))==turn and h.binding.calls==1


def test_provider_phase_has_no_database_write_lock(h):
    class Provider:
        def plan(self,request,snapshot):
            # This independent writer would fail with database locked if the
            # application held BEGIN IMMEDIATE around the provider.
            with h.tx() as tx:
                tx.add(MemoryDocument(elder_id=h.seed['stranger_elder']['elder_id'],version=1,
                                      entries_json=[],revisions_json=[],updated_at=h.clock.now()))
            return h.provider.plan(request,snapshot)
    turn=h.turn(body(h),provider=Provider())
    assert turn.actions[0].status=='pending'


def test_medication_amendments_cannot_redirect_plan_or_task(h):
    from app.schemas.health import DailyTask as TaskDTO
    with h.tx() as tx:
        tx.add(MedicationPlan(id='med-plan',elder_id=h.elder_id,name='既定药品',dose_display='档案用量',
                              schedule={'mode':'fixed','slots':[{'slot_id':'morning','local_time':'08:00'}]},
                              start_date=date(2026,10,30),updated_at=h.clock.now()))
        tx.flush()
        tx.add(DailyTask(id='med-task',elder_id=h.elder_id,local_date=date(2026,10,30),category='medication',
                         slot_key='med-slot',plan_id='med-plan',plan_version=1,title='既定药品',due_at=h.clock.now()))
    task=TaskDTO(task_id='med-task',date=date(2026,10,30),category='medication',slot_key='opaque',
                  plan_id='med-plan',plan_version=1,title='既定药品',dose_display='档案用量',due_at=h.clock.now(),
                  waiting_for_meal=False,completion='pending',checkin_ids=[])
    turn=h.turn(body(h,'medication_confirm'),tasks=[task],medication_slots={'med-task':'morning'})
    action=turn.actions[0].action_id
    with pytest.raises(AppError) as exc:
        with h.tx() as tx:h.agent.decide(tx,h.actor(),action,ActionDecision(decision='confirm',amendments={'plan_id':'foreign','slot_id':'morning','intake_status':'taken'}))
    assert exc.value.status==403 and count(h,Checkin)==0
    with h.tx() as tx:result=h.agent.decide(tx,h.actor(),action,ActionDecision(decision='confirm'))
    assert result.result.task_id=='med-task' and result.result.payload.intake_status=='taken'


def test_profile_action_roundtrips_without_inserting_null_patch_fields(h):
    from app.schemas.identity import Profile
    profile=Profile(elder_id=h.elder_id,version=2,onboarding_status='confirmed',display_name='测试',
                    timezone='Asia/Hong_Kong',source='user_confirmed',updated_at=h.clock.now())
    request=body(h,'profile_update')
    turn=h.turn(request,profile=profile)
    assert h.turn(request)==turn
    with h.tx(write=False) as tx:
        action=tx.get(AgentAction,turn.actions[0].action_id)
        assert set(action.payload_json['public']['preview']['patch']) == {'medical_notes'}


def test_next_conversation_uses_corrected_or_deleted_memory(h):
    h.turn(body(h,'explicit_preference','pref',conversation_id='one'))
    query=AgentTurnWrite(elder_id=h.elder_id,client_turn_id='query1',conversation_id='two',text='我喜欢什么')
    remembered=h.turn(query)
    assert '喜欢清淡饮食' in remembered.reply.text
    with h.tx() as tx:
        doc=h.memory.context(tx,h.actor(),h.elder_id)
        h.memory.update_entry(tx,h.actor(),h.elder_id,doc.entries[0].entry_id,doc.version,'喜欢清淡、不喜欢甜食')
    updated=h.turn(query.model_copy(update={'client_turn_id':'query2','conversation_id':'three'}))
    assert '不喜欢甜食' in updated.reply.text
    with h.tx() as tx:
        doc=h.memory.context(tx,h.actor(),h.elder_id)
        h.memory.delete_entry(tx,h.actor(),h.elder_id,doc.entries[0].entry_id,doc.version)
    removed=h.turn(query.model_copy(update={'client_turn_id':'query3','conversation_id':'four'}))
    assert '目前没有已保存' in removed.reply.text and '不喜欢甜食' not in removed.reply.text


def test_query_report_uses_actual_port_summary_and_replay(h):
    from app.schemas.health import DailyReport
    class ReportFixture:
        calls=0
        def daily(self,tx,actor,elder_id,day):
            self.calls+=1
            progress={k:{'completed':0,'expected':v,'applicable':bool(v)} for k,v in [('diet',3),('exercise',1),('medication',0)]}
            return DailyReport(elder_id=elder_id,date=day,
                               completion={'date':day,'state':'unrecorded','color':'gray','is_today':True,'progress':progress},
                               records={'diet':[],'exercise':[],'medication':[]},
                               summary_text='测试日报：尚无记录，不表示没有服药。',attention_items=[],updated_at=h.clock.now())
    report=ReportFixture()
    h.agent.services=replace(h.agent.services,reports=report)
    request=body(h,'daily_query')
    turn=h.turn(request)
    assert '测试日报：尚无记录' in turn.reply.text
    assert h.turn(request)==turn and report.calls==1


def test_validation_failure_after_memory_write_rolls_back_the_entire_turn(h):
    from pydantic import ValidationError
    class InvalidProvider:
        def plan(self,request,snapshot):
            return replace(h.provider.plan(request,snapshot),scene='invented-scene')
    with pytest.raises(ValidationError):
        h.turn(body(h,'explicit_preference'),provider=InvalidProvider())
    assert count(h,AgentTurn)==count(h,AgentAction)==count(h,MemoryDocument)==0
