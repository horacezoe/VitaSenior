"""Persist model assessments and evidence; contains NO interaction rule database."""
import hashlib
import json
from sqlalchemy import select
from app.models.health import DailyTask, SafetySignal, SafetyAssessment
from app.schemas.health import HealthAnomaly, SafetySource
from app.services.health_service import authorize

class SafetyReviewService:
    def __init__(self,clock,access):self.clock,self.access=clock,access
    def sources(self,tx,actor,elder_id,day,report):
        authorize(tx,actor,elder_id,access=self.access)
        sources=[]
        for record in report.records.diet:
            if record.source=='demo_seed':continue
            sources.append(SafetySource(evidence=dict(type='checkin',id=record.checkin_id,version=record.version),category='diet',basis='recorded',label='当日已确认膳食',facts=record.payload.model_dump(mode='json')))
        for record in report.records.medication:
            if record.source=='demo_seed' or record.payload.intake_status!='taken':continue
            task=tx.get(DailyTask,record.task_id)
            snapshot=(task.plan_snapshot or {}) if task else {}
            sources.append(SafetySource(evidence=dict(type='checkin',id=record.checkin_id,version=record.version),category='medication',basis='recorded',medicine_id=record.payload.plan_id,label=snapshot.get('name','药品名称未明确'),facts={**record.payload.model_dump(mode='json'),'name':snapshot.get('name'),'dose_display':snapshot.get('dose_display')}))
        for plan in report.medication_plans:
            if not plan.active or plan.start_date>day or (plan.end_date and plan.end_date<day):continue
            sources.append(SafetySource(evidence=dict(type='medication_plan',id=plan.plan_id,version=plan.version),category='medication',basis='planned',medicine_id=plan.plan_id,label=plan.name,facts=plan.model_dump(mode='json')))
        return tuple(sources)
    def read(self,tx,actor,elder_id,day):
        authorize(tx,actor,elder_id,access=self.access)
        return [HealthAnomaly(anomaly_id=r.id,date=day,status=r.status,revision=r.revision,detected_at=r.detected_at,**r.payload) for r in tx.scalars(select(SafetySignal).where(SafetySignal.elder_id==elder_id,SafetySignal.local_date==day).order_by(SafetySignal.id))]
    def status(self,tx,actor,elder_id,day):
        authorize(tx,actor,elder_id,access=self.access);row=tx.get(SafetyAssessment,(elder_id,day))
        return row.status if row else 'not_reviewed'
    def reviewed(self,tx,actor,elder_id,day,digest,model):
        authorize(tx,actor,elder_id,access=self.access);row=tx.get(SafetyAssessment,(elder_id,day))
        return bool(row and row.input_digest==digest and row.model==model and row.status in {'reviewed','insufficient_data'})
    def save(self,tx,actor,elder_id,day,digest,model,review):
        authorize(tx,actor,elder_id,access=self.access)
        if self.reviewed(tx,actor,elder_id,day,digest,model):return
        now=self.clock.now();assessment=tx.get(SafetyAssessment,(elder_id,day))
        if assessment is None:
            assessment=SafetyAssessment(elder_id=elder_id,local_date=day);tx.add(assessment)
        assessment.input_digest,assessment.model=digest,model
        assessment.status=review.status if review else 'unavailable';assessment.reviewed_at=now
        # Failure/insufficient data never clears a previous warning.
        if review is None or review.status!='reviewed':return
        old={r.issue_key:r for r in tx.scalars(select(SafetySignal).where(SafetySignal.elder_id==elder_id,SafetySignal.local_date==day))};active=set()
        for finding in review.findings:
            identity=json.dumps([finding.kind,sorted((s.type,s.id) for s in finding.evidence)])
            key=hashlib.sha256(identity.encode()).hexdigest();active.add(key)
            data={**finding.model_dump(mode='json'),'assessment_model':model}
            fingerprint=hashlib.sha256((digest+identity).encode()).hexdigest()
            row=old.get(key)
            if row is None:
                row=SafetySignal(elder_id=elder_id,local_date=day,issue_key=key,payload=data,fingerprint=fingerprint,status='active',revision=1,detected_at=now,updated_at=now);tx.add(row)
            elif row.fingerprint!=fingerprint or row.status!='active':
                row.history=[*(row.history or []),dict(payload=row.payload,status=row.status,revision=row.revision)]
                row.payload,row.fingerprint,row.status=data,fingerprint,'active';row.revision+=1;row.updated_at=now
        for key,row in old.items():
            if key not in active and row.status=='active':
                row.history=[*(row.history or []),dict(payload=row.payload,status=row.status,revision=row.revision)]
                row.status='resolved';row.revision+=1;row.updated_at=now
        tx.flush()
