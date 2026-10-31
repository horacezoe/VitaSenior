"""Guarded, explicit upgrade of untouched fictional seed data only.
Run --data-dir PATH for dry-run; --apply commits. Back up before applying.
"""
import argparse
from copy import deepcopy
from datetime import datetime,time,timedelta,timezone
from pathlib import Path
from sqlalchemy import select,or_
from app.core.clock import HK,SystemClock
from app.core.db import build_engine,sessions
from app.core.uow import UnitOfWork
from app.core.ids import new_id
from app.fixtures.identity import SAMPLE_PROFILES,LEGACY_SAMPLE_PROFILES
from app.models.identity import CommunityRecord,DemoIdentity,ElderProfile
from app.models.health import MedicationPlan,DailyTask,Checkin,Notification

FIELDS=('name','dose_display','schedule','notes')
def same_plan(value,old):return all(value.get(k)==old.get(k) for k in FIELDS)

def upgrade(tx,now):
    counts=dict(sources=0,drafts=0,profiles=0,plans=0,tasks=0,skipped=0)
    for key,new in SAMPLE_PROFILES.items():
        old=LEGACY_SAMPLE_PROFILES.get(key);record=tx.get(CommunityRecord,key)
        if old is None:
            if record is None:
                tx.add(CommunityRecord(id=key,record_number=new['record_number'],community_name=new['community_name'],sample_json=deepcopy(new)));counts['sources']+=1
            continue
        if record and record.sample_json==old:
            record.sample_json=deepcopy(new);record.community_name=new['community_name'];counts['sources']+=1
        elif record and record.sample_json!=new:counts['skipped']+=1
    for elder,identity in tx.execute(select(ElderProfile,DemoIdentity).join(DemoIdentity,DemoIdentity.user_id==ElderProfile.owner_user_id)):
        key=identity.community_record_id
        if key not in SAMPLE_PROFILES or key not in LEGACY_SAMPLE_PROFILES:continue
        old,new=LEGACY_SAMPLE_PROFILES[key],SAMPLE_PROFILES[key]
        old_profile={k:v for k,v in old['profile'].items() if k!='source'}
        new_profile={k:v for k,v in new['profile'].items() if k!='source'}
        draft=deepcopy(elder.onboarding_draft or {})
        plans=draft.get('medication_plan_drafts',[])
        if draft.get('result') and draft.get('profile_draft')==old_profile and len(plans)==len(old['medication_templates']) and all(same_plan(p,t['plan']) for p,t in zip(plans,old['medication_templates'])):
            updated=[{**p,**{k:deepcopy(t['plan'][k]) for k in FIELDS}} for p,t in zip(plans,new['medication_templates'])]
            elder.version+=1;elder.updated_at=now
            draft.update(draft_id=new_id('draft'),profile_draft=new_profile,medication_plan_drafts=updated,profile_version=elder.version)
            draft['result'].update(draft_id=draft['draft_id'],profile_draft=new_profile,medication_plan_drafts=updated,community_name=new['community_name'])
            elder.onboarding_draft=draft;counts['drafts']+=1
        if {k:v for k,v in elder.profile_json.items() if k!='source'}==old_profile:
            elder.profile_json={**new_profile,'source':elder.profile_json.get('source','user_confirmed')}
            elder.version+=1;elder.updated_at=now;counts['profiles']+=1
        for plan in tx.scalars(select(MedicationPlan).where(MedicationPlan.elder_id==elder.id)):
            index=next((i for i,t in enumerate(old['medication_templates']) if same_plan({k:getattr(plan,k) for k in FIELDS},t['plan'])),None)
            if index is None:continue
            tasks=list(tx.scalars(select(DailyTask).where(DailyTask.plan_id==plan.id)))
            task_ids=[t.id for t in tasks]
            actual=tx.scalar(select(Checkin.id).where(Checkin.task_id.in_(task_ids),or_(
                Checkin.source!='demo_seed',Checkin.version!=1,Checkin.cancelled_at.is_not(None)))) if task_ids else None
            # Matching placeholder text and version=1 alone do not prove seed origin:
            # users may have changed dates before their first confirmation. Only
            # unchanged plans were authorized to receive this synthetic history.
            prefix=f'demo:{identity.demo_id}:{elder.id}:history'
            proven_seed=any(t.category=='medication' and (t.source_key or '').startswith(prefix+':')
                and t.local_date<now.astimezone(HK).date() and t.plan_version==plan.version
                and (t.plan_snapshot or {}).get('start_date')==plan.start_date.isoformat()
                and (t.plan_snapshot or {}).get('end_date')==(plan.end_date.isoformat() if plan.end_date else None)
                for t in tasks)
            if (plan.version!=1 or not plan.active or actual or plan.medicine_asset_id
                    or not proven_seed or any(t.cancelled_at is not None for t in tasks)):
                counts['skipped']+=1;continue
            replacement=new['medication_templates'][index]['plan']
            for field in FIELDS:setattr(plan,field,deepcopy(replacement[field]))
            plan.version+=1;plan.updated_at=now;counts['plans']+=1
            for task in tasks:
                task.title=plan.name;task.dose_display=plan.dose_display;task.plan_version=plan.version
                snapshot=deepcopy(task.plan_snapshot or {})
                snapshot.update(name=plan.name,dose_display=plan.dose_display,schedule=plan.schedule,version=plan.version)
                task.plan_snapshot=snapshot
                slot=next(s for s in plan.schedule['slots'] if task.slot_key==f"{plan.id}:{s['slot_id']}")
                if plan.schedule['mode']=='fixed':
                    task.due_at=datetime.combine(task.local_date,time.fromisoformat(slot['local_time']),HK).astimezone(timezone.utc);task.waiting_for_meal=False
                else:
                    meal=tx.scalar(select(Checkin).where(Checkin.elder_id==elder.id,Checkin.local_date==task.local_date,Checkin.type=='diet',Checkin.slot_key==slot['meal_slot'],Checkin.cancelled_at.is_(None)))
                    task.due_at=meal.occurred_at+timedelta(minutes=slot['delay_minutes']) if meal else None;task.waiting_for_meal=meal is None
                for record in tx.scalars(select(Checkin).where(Checkin.task_id==task.id,Checkin.source=='demo_seed')):
                    if task.due_at:record.occurred_at=task.due_at
                for notice in tx.scalars(select(Notification).where(Notification.related_task_id==task.id,Notification.delivery_state=='pending',Notification.played_at.is_(None),Notification.proposal_id.is_(None))):
                    notice.title=plan.name;notice.audio_asset_id=None
                    if task.due_at:notice.due_at=task.due_at
                counts['tasks']+=1
    tx.flush();return counts

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--data-dir',type=Path,required=True);parser.add_argument('--apply',action='store_true');args=parser.parse_args()
    if not (args.data_dir/'vitasenior.sqlite3').is_file():raise SystemExit('Existing SQLite database required')
    engine=build_engine(args.data_dir)
    try:
        with UnitOfWork(sessions(engine)) as unit:
            result=upgrade(unit.session,SystemClock().now())
            if args.apply:unit.commit()
            print(('APPLIED' if args.apply else 'DRY_RUN (rolled back)'),result)
    finally:engine.dispose()
if __name__=='__main__':main()
