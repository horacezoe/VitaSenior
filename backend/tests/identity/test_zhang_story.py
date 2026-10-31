from app.fixtures.identity import SAMPLE_PROFILES
from test_community_matching import family,match,confirm
from app.models.health import MedicationPlan,Checkin
from sqlalchemy import select,func


def test_zhang_story_is_independent_specific_and_does_not_assert_grapefruit_ingestion(env):
 sample=SAMPLE_PROFILES['community_sample_014'];profile=sample['profile']
 assert profile['display_name']=='张奶奶' and profile['conditions']==['高血压','2型糖尿病']
 assert '汽车厂' in profile['medical_notes'] and '女儿在广州' in profile['medical_notes'] and '尚未确认食用' in profile['medical_notes']
 assert [p['plan']['name'] for p in sample['medication_templates']]==['非洛地平缓释片','盐酸二甲双胍缓释片']
 app,client,clock,_=env;demo,auth=family(env,'community_sample_014');draft=match(client,demo,auth)
 response=confirm(client,demo,auth,draft,draft['medication_plan_drafts']);assert response.status_code==200,response.text
 with app.state.sessions() as tx:
  assert tx.scalar(select(func.count()).select_from(MedicationPlan).where(MedicationPlan.elder_id==demo['elder_id']))==2
  meals=tx.scalars(select(Checkin).where(Checkin.elder_id==demo['elder_id'],Checkin.type=='diet')).all()
  assert all('西柚' not in r.payload_json.get('foods',[]) for r in meals)
