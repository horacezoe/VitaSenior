from copy import deepcopy
import pytest
from sqlalchemy import select
from app.fixtures.identity import SAMPLE_PROFILES,LEGACY_SAMPLE_PROFILES
from app.schemas.health import MedicationPlanWrite
from app.tools.upgrade_sample_medications import upgrade
from app.core.uow import UnitOfWork
from app.models.identity import CommunityRecord,ElderProfile,DemoIdentity
from app.models.health import MedicationPlan
from test_community_matching import family,match,confirm


def test_all_authored_samples_have_named_valid_medication_and_route_context():
    for sample in SAMPLE_PROFILES.values():
        for template in sample['medication_templates']:
            plan=deepcopy(template['plan']);plan['start_date']='2026-11-01'
            value=MedicationPlanWrite.model_validate(plan)
            assert '演示药品' not in value.name and '既定用量' not in value.dose_display
            assert any(unit in value.dose_display for unit in ['mg','微克'])
    assert '不得吞服' in SAMPLE_PROFILES['community_sample_006']['medication_templates'][0]['plan']['dose_display']
    assert not SAMPLE_PROFILES['community_sample_007']['medication_templates']
    assert 'eGFR 52' in SAMPLE_PROFILES['community_sample_010']['profile']['medical_notes']


def test_guarded_upgrade_refreshes_old_draft_and_is_idempotent(env):
    app,client,clock,_=env
    with UnitOfWork(app.state.sessions) as u:
        record=u.session.get(CommunityRecord,'community_sample_001');record.sample_json=deepcopy(LEGACY_SAMPLE_PROFILES['community_sample_001']);u.commit()
    demo,auth=family(env,'community_sample_001');old=match(client,demo,auth)
    assert old['medication_plan_drafts'][0]['name']=='演示药品A'
    with UnitOfWork(app.state.sessions) as u:
        counts=upgrade(u.session,clock.now());assert counts['drafts']==1;u.commit()
    updated=match(client,demo,auth,key="after-upgrade")
    assert updated['draft_id']!=old['draft_id']
    assert updated['medication_plan_drafts'][0]['name']=='盐酸二甲双胍缓释片'
    with UnitOfWork(app.state.sessions) as u:
        assert upgrade(u.session,clock.now())['drafts']==0


def test_upgrade_preserves_modified_community_source_and_draft(env):
    app,client,clock,_=env
    with UnitOfWork(app.state.sessions) as u:
        record=u.session.get(CommunityRecord,'community_sample_001')
        custom=deepcopy(LEGACY_SAMPLE_PROFILES['community_sample_001']);custom['profile']['medical_notes']='用户已核对的备注';record.sample_json=custom;u.commit()
    demo,auth=family(env,'community_sample_001');old=match(client,demo,auth)
    with UnitOfWork(app.state.sessions) as u:
        upgrade(u.session,clock.now());u.commit()
    updated=match(client,demo,auth,key="after-upgrade")
    assert updated['draft_id']==old['draft_id'] and updated['profile_draft']['medical_notes']=='用户已核对的备注'


def test_upgrade_changes_only_untouched_seed_plan_and_keeps_custom_plan(env):
    from datetime import date
    from app.models.health import DailyTask,Checkin
    app,_,clock,_=env;demo,_=family(env,'community_sample_001')
    old=LEGACY_SAMPLE_PROFILES['community_sample_001']['medication_templates'][0]['plan']
    with UnitOfWork(app.state.sessions) as u:
        plan=MedicationPlan(elder_id=demo['elder_id'],name=old['name'],dose_display=old['dose_display'],schedule=old['schedule'],notes=old['notes'],start_date=date(2026,10,16),updated_at=clock.now())
        custom=MedicationPlan(elder_id=demo['elder_id'],name=old['name'],dose_display='本人调整后的用量',schedule=old['schedule'],notes=old['notes'],start_date=date(2026,10,30),updated_at=clock.now())
        u.session.add_all([plan,custom]);u.session.flush();pid,cid=plan.id,custom.id
        task=DailyTask(elder_id=demo['elder_id'],local_date=date(2026,10,29),category='medication',slot_key=pid+':morning',plan_id=pid,plan_version=1,title=old['name'],dose_display=old['dose_display'],plan_snapshot={'name':old['name'],'dose_display':old['dose_display'],'schedule':old['schedule'],'version':1,'start_date':'2026-10-16','end_date':None},source_key=f"demo:{demo['demo_id']}:{demo['elder_id']}:history:legacy-medication",due_at=clock.now())
        u.session.add(task);u.session.flush();tid=task.id;u.commit()
    with UnitOfWork(app.state.sessions) as u:
        result=upgrade(u.session,clock.now());assert result['plans']==1;u.commit()
    with app.state.sessions() as tx:
        assert tx.get(MedicationPlan,pid).name=='盐酸二甲双胍缓释片'
        assert tx.get(MedicationPlan,cid).dose_display=='本人调整后的用量'
        assert tx.get(DailyTask,tid).title=='盐酸二甲双胍缓释片'
        assert tx.get(DailyTask,tid).due_at.astimezone(__import__('app.core.clock',fromlist=['HK']).HK).hour==18
    with UnitOfWork(app.state.sessions) as u:assert upgrade(u.session,clock.now())['plans']==0


@pytest.mark.parametrize('changed_date', ['start_date', 'end_date'])
def test_upgrade_keeps_dates_customized_before_first_confirmation(env, changed_date):
    app,client,clock,_=env
    with UnitOfWork(app.state.sessions) as u:
        u.session.get(CommunityRecord,'community_sample_001').sample_json=deepcopy(LEGACY_SAMPLE_PROFILES['community_sample_001'])
        u.commit()
    demo,auth=family(env,'community_sample_001')
    draft=match(client,demo,auth)
    plans=deepcopy(draft['medication_plan_drafts'])
    plans[0][changed_date]='2026-10-29'
    response=confirm(client,demo,auth,draft,plans)
    assert response.status_code==200,response.text
    with UnitOfWork(app.state.sessions) as u:
        assert upgrade(u.session,clock.now())['plans']==0
        u.commit()
    with app.state.sessions() as tx:
        plan=tx.scalar(select(MedicationPlan).where(MedicationPlan.elder_id==demo['elder_id']))
        assert plan.name=='演示药品A' and plan.version==1


@pytest.mark.parametrize('record_change', [None, 'source', 'version', 'cancelled'])
def test_confirmed_seed_origin_and_user_record_changes_are_respected(env, record_change):
    from app.models.health import Checkin
    app,client,clock,_=env
    with UnitOfWork(app.state.sessions) as u:
        u.session.get(CommunityRecord,'community_sample_001').sample_json=deepcopy(LEGACY_SAMPLE_PROFILES['community_sample_001'])
        u.commit()
    demo,auth=family(env,'community_sample_001')
    draft=match(client,demo,auth)
    assert confirm(client,demo,auth,draft).status_code==200
    if record_change:
        with UnitOfWork(app.state.sessions) as u:
            record=u.session.scalar(select(Checkin).where(Checkin.elder_id==demo['elder_id'],Checkin.type=='medication'))
            assert record is not None
            if record_change=='source':record.source='agent_confirmed'
            elif record_change=='version':record.version+=1
            else:record.cancelled_at=clock.now()
            u.commit()
    with UnitOfWork(app.state.sessions) as u:
        assert upgrade(u.session,clock.now())['plans']==(0 if record_change else 1)
        u.commit()
    with app.state.sessions() as tx:
        plan=tx.scalar(select(MedicationPlan).where(MedicationPlan.elder_id==demo['elder_id']))
        assert plan.name==('演示药品A' if record_change else '盐酸二甲双胍缓释片')
