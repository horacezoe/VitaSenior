from dataclasses import dataclass
from typing import Protocol, runtime_checkable
from app.schemas.health import DailyReport, DailyInsights, SafetySource, SafetyReview, Checkin
from app.schemas.identity import Profile
from app.schemas.agent import MemoryDocument

@dataclass(frozen=True)
class ReportInput:
    profile: Profile
    memory: MemoryDocument
    report: DailyReport
    safety_sources: tuple[SafetySource,...] = ()
    history: tuple[Checkin,...] = ()
    def __post_init__(self):
        # Versioned, server-read profile evidence. No inferred medical facts.
        profile=self.profile
        if not getattr(profile,'elder_id',None) or not getattr(profile,'version',None):return
        source=SafetySource(evidence=dict(type='profile',id=profile.elder_id,version=profile.version),
            category='profile',basis='recorded',label='已确认健康档案',
            facts=profile.model_dump(mode='json',include={'birth_date','conditions','allergies','medical_notes'}))
        existing=tuple(s for s in self.safety_sources if s.evidence.type!='profile')
        object.__setattr__(self,'safety_sources',(*existing,source))

class ReportWriter(Protocol):
    """Pure snapshot input; caller closes/commits the UoW before this slow call."""
    def generate(self, snapshot: ReportInput) -> DailyInsights: ...

@runtime_checkable
class MedicationRiskReviewer(Protocol):
    def review_plan(self, snapshot: ReportInput) -> SafetyReview: ...

def report_payload(snapshot):
    report=snapshot.report.model_dump(mode='json',exclude={'updated_at','insights','ai_status','person','anomalies','safety_review_status','reward_summary'})
    if 'completion' in report:report['completion'].pop('anomalies',None)
    return dict(profile=snapshot.profile.model_dump(mode='json',exclude={'updated_at'}),
        memory=snapshot.memory.model_dump(mode='json',exclude={'updated_at'}),report=report,
        safety_sources=[s.model_dump(mode='json') for s in getattr(snapshot,'safety_sources',())],
        history=[r.model_dump(mode='json',include={'checkin_id','type','local_date','payload','version','source'})
                 for r in getattr(snapshot,'history',())])

def report_digest(snapshot):
    import hashlib,json
    return hashlib.sha256(json.dumps(report_payload(snapshot),ensure_ascii=False,sort_keys=True).encode()).hexdigest()
