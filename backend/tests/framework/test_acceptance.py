import asyncio, hashlib, json, re
from datetime import date, timedelta
from pathlib import Path
from dataclasses import replace
import pytest
from pydantic import ValidationError, TypeAdapter
from sqlalchemy import select, text, func
from sqlalchemy.exc import IntegrityError
from app.core.uow import UnitOfWork
from app.core.idempotency import Idempotency, StoredResult
from app.core.errors import AppError
from app.core.auth import require_elder_access
from app.core.clock import local_date
from app.contracts.context import Actor
from app.schemas.enums import Role
from app.schemas.health import MedicationPlanWrite, CheckinWrite
from app.schemas.identity import ChangeProposalWrite
from app.models.identity import User, ElderProfile, FamilyBinding, BindingCode, AuthSession, AuthChallenge, IdempotencyRecord
from app.models.health import MedicationPlan, DailyTask, Checkin, Notification, NotificationEvent, Presence
from app.models.agent import AgentTurn, AgentAction, MemoryDocument
from app.seed import framework_seed
from app.scheduler import Scanner
from app.main import create_app
from app.composition import compose
from app.tools.export_contract import check_contract, export_bytes, DEFAULT_PATH
from app.tools.check_architecture import violations

def test_fg01_startup_health_runtime(env, tokens):
    app, client, clock, seed = env
    r = client.get('/api/v1/health')
    assert r.status_code == 200
    assert r.json()['data'] == {'status':'ok', 'database':'ok', 'scheduler':'disabled'}
    assert r.headers['X-Request-ID'] == r.json()['meta']['request_id']
    assert client.get('/api/v1/runtime').status_code == 401
    r = client.get('/api/v1/runtime', headers=tokens['elder'])
    assert r.status_code == 200
    data = r.json()['data']
    # Providers report the real per-modality status; "not_implemented" is only for a
    # modality with no provider. The F0 "all not_implemented" snapshot lives in
    # test_stage_f0.py.
    assert set(data['providers']) == {'chat', 'asr', 'tts'}
    assert set(data['providers'].values()) <= {'mock', 'real', 'not_implemented'}
    # Capability truth is owned by the per-domain declaration files; the runtime
    # must render exactly those, and the five F0 operations stay implemented.
    declared = app.state.capabilities_declared
    assert {k for k,v in data['capabilities'].items() if v} == set(declared)
    assert {'SYS01','SYS02','AUTH01','AUTH02','AUTH04'} <= set(declared)
    assert app.state.scanner.task is None

def test_fg02_p0_inventory_and_schemas(env):
    app, client, *_ = env
    expected = set(re.findall(r'\| ([A-Z]+\d+) \| P0 \|', (Path(__file__).resolve().parents[3]/'docs'/'后端接口说明.md').read_text(encoding='utf-8')))
    operations = [op for item in app.openapi()['paths'].values() for method,op in item.items() if method in {'get','post','put','delete'}]
    ids = [op['operationId'] for op in operations]
    assert set(ids) == expected
    assert len(ids) == len(set(ids)) == 45
    for op in operations:
        success = next(v for k,v in op['responses'].items() if k.startswith('2'))
        assert success['content']
        for status in ['401','403','404','409','422','500','501']:
            assert op['responses'][status]['content']['application/json']['schema']['$ref'].endswith('/ErrorEnvelope')
    invalid = client.post('/api/v1/auth/code',json={'phone':'bad','role':'unknown'})
    assert invalid.status_code == 422
    assert invalid.json()['error']['code'] == 'VALIDATION_ERROR'
    assert invalid.headers['X-Request-ID'] == invalid.json()['meta']['request_id']
    assert client.get('/not-present').json()['error']['code'] == 'NOT_FOUND'

def test_fg03_sessions_and_real_access(env, tokens):
    app, client, clock, seed = env
    own = seed['elder']['elder_id']
    foreign = seed['stranger_elder']['elder_id']
    path = f'/api/v1/elders/{own}/profile'
    implemented = 200 if 'PROF01' in app.state.capabilities_declared else 501
    for headers, code in [({},401),(tokens['unbound_child'],403),(tokens['stranger_elder'],403),(tokens['bound_child'],implemented),(tokens['elder'],implemented)]:
        assert client.get(path,headers=headers).status_code == code
    assert client.get(f'/api/v1/elders/{foreign}/profile',headers=tokens['bound_child']).status_code == 403
    assert client.get('/api/v1/elders/nonexistent/profile',headers=tokens['bound_child']).status_code == 403
    me = client.get('/api/v1/me', headers=tokens['bound_child']).json()['data']
    assert me['elder_id'] is None
    assert me['bound_elders'][0]['elder_id'] == own
    assert client.get('/api/v1/me',headers=tokens['elder']).json()['data']['elder_id'] == own
    with app.state.sessions() as tx:
        sessions = tx.scalars(select(AuthSession)).all()
        assert len(sessions) == 4
        assert all(len(s.token_hash) == 64 for s in sessions)
        assert all(s.token_hash not in tokens['elder']['Authorization'] for s in sessions)
    # New app reuses persisted sessions; no fresh seed or fake auth dependency.
    from fastapi.testclient import TestClient
    with TestClient(create_app(app.state.settings, clock=clock)) as restarted:
        assert restarted.get('/api/v1/me',headers=tokens['elder']).status_code == 200
    # Revoking the actual DB relationship affects subsequent requests.
    with UnitOfWork(app.state.sessions) as u:
        b = u.session.scalar(select(FamilyBinding))
        b.status = 'revoked'
        u.commit()
    assert client.get(path, headers=tokens['bound_child']).status_code == 403
    clock.advance(seconds=48*3600)
    r=client.get('/api/v1/me',headers=tokens['elder'])
    assert r.status_code == 401 and r.json()['error']['code'] == 'SESSION_EXPIRED'

def test_fg03_challenge_ownership_expiry_and_limits(env):
    app, client, clock, seed = env
    account={k:seed['elder'][k] for k in ['phone','role']}
    assert client.post('/api/v1/auth/code',json={'phone':'13800000000','role':'elder'}).status_code==401
    challenge=client.post('/api/v1/auth/code',json=account).json()['data']['challenge_id']
    body={**account,'challenge_id':challenge,'code':'000000'}
    assert client.post('/api/v1/auth/login',json=body).status_code==401
    body['phone']=seed['stranger_elder']['phone']
    body['code']='123456'
    assert client.post('/api/v1/auth/login',json=body).status_code==401
    body['phone']=account['phone']
    clock.advance(seconds=301)
    response=client.post('/api/v1/auth/login',json=body)
    assert response.status_code==401 and response.json()['error']['code']=='CHALLENGE_EXPIRED'
    for _ in range(5):
        assert client.post('/api/v1/auth/code',json=account).status_code==200
    r=client.post('/api/v1/auth/code',json=account)
    assert r.status_code==429 and r.headers['Retry-After']=='300'
    with app.state.sessions() as tx:
        assert tx.scalar(select(func.count()).select_from(AuthSession))==0

def test_fg04_tables_foreign_keys_and_uniqueness(env):
    app,client,clock,seed=env
    from app.core.db import Base
    assert set(Base.metadata.tables) == {'users','auth_sessions','auth_challenges','elder_profiles','family_bindings','binding_codes','media_assets','change_proposals','idempotency_records','medication_plans','daily_tasks','daily_goal_batches','checkins','notifications','notification_events','presence','agent_turns','agent_actions','memory_documents'}
    with app.state.engine.connect() as conn:
        assert conn.execute(text('PRAGMA foreign_keys')).scalar()==1
        assert conn.execute(text('PRAGMA journal_mode')).scalar()=='wal'
        assert conn.execute(text('PRAGMA busy_timeout')).scalar()==5000
    def fails(obj):
        with pytest.raises(IntegrityError):
            with UnitOfWork(app.state.sessions) as u:
                u.session.add(obj)
                u.session.flush()
                u.commit()
    fails(AuthSession(user_id='absent', token_hash='x',expires_at=clock.now()))
    fails(User(phone=seed['elder']['phone'],role='elder',demo_id='collision'))
    fails(User(phone='19900000008',role='admin',demo_id='invalid'))
    fails(FamilyBinding(elder_id=seed['elder']['elder_id'],child_user_id=seed['bound_child']['user_id'],relationship='duplicate'))
    elder_id=seed['elder']['elder_id']
    with UnitOfWork(app.state.sessions) as u:
        u.session.add(BindingCode(code='0012',elder_id=elder_id,expires_at=clock.now()+timedelta(seconds=300)))
        u.session.add(DailyTask(id='task',elder_id=elder_id,local_date=date(2026,10,30),category='diet',slot_key='lunch',title='午餐'))
        u.session.add(Checkin(elder_id=elder_id,type='diet',local_date=date(2026,10,30),slot_key='lunch',payload_json={},occurred_at=clock.now(),created_at=clock.now(),updated_at=clock.now()))
        u.commit()
    fails(BindingCode(code='0012',elder_id=seed['stranger_elder']['elder_id'],expires_at=clock.now()))
    fails(BindingCode(code='12345',elder_id=seed['stranger_elder']['elder_id'],expires_at=clock.now()))
    fails(DailyTask(elder_id=elder_id,local_date=date(2026,10,30),category='diet',slot_key='lunch',title='duplicate'))
    fails(Checkin(elder_id=elder_id,type='diet',local_date=date(2026,10,30),slot_key='lunch',payload_json={},occurred_at=clock.now(),created_at=clock.now(),updated_at=clock.now()))
    with UnitOfWork(app.state.sessions) as u:
        u.session.add(Checkin(elder_id=elder_id,type='medication',task_id='task',local_date=date(2026,10,30),payload_json={},occurred_at=clock.now(),created_at=clock.now(),updated_at=clock.now()))
        u.commit()
    fails(Checkin(elder_id=elder_id,type='medication',task_id='task',local_date=date(2026,10,30),payload_json={},occurred_at=clock.now(),created_at=clock.now(),updated_at=clock.now()))

def test_fg05_atomic_rollback_and_idempotency(env):
    app,client,clock,seed=env
    idem=app.state.idempotency
    identity=dict(actor_id=seed['elder']['user_id'],method='POST',path='/test',key='one',body={'value':1})
    calls=[]
    def operation(tx):
        calls.append(True)
        user=User(phone='19900000009',role='child',demo_id='atomic-test')
        tx.add(user)
        tx.flush()
        return StoredResult(201,{'user_id':user.id})
    with pytest.raises(RuntimeError):
        with UnitOfWork(app.state.sessions) as u:
            idem.execute(u.session,**identity,operation=lambda:operation(u.session))
            raise RuntimeError('after business AND idempotency writes')
    with app.state.sessions() as tx:
        assert tx.scalar(select(User).where(User.phone=='19900000009')) is None
        assert tx.scalar(select(IdempotencyRecord)) is None
    with UnitOfWork(app.state.sessions) as u:
        first=idem.execute(u.session,**identity,operation=lambda:operation(u.session))
        u.commit()
    with UnitOfWork(app.state.sessions) as u:
        again=idem.execute(u.session,**identity,operation=lambda:pytest.fail('replay executed business operation'))
        u.commit()
    assert again==first and len(calls)==2
    with pytest.raises(AppError, match='different request') as exc:
        with UnitOfWork(app.state.sessions) as u:
            idem.execute(u.session,**{**identity,'body':{'value':2}},operation=lambda:pytest.fail('conflict ran'))
    assert exc.value.status==409 and exc.value.code=='IDEMPOTENCY_CONFLICT'
    # Read access must still be checked before replay (sample application flow).
    actor=Actor(seed['unbound_child']['user_id'],Role.child)
    with pytest.raises(AppError) as exc:
        with UnitOfWork(app.state.sessions) as u:
            require_elder_access(u.session,actor,seed['elder']['elder_id'])
            idem.execute(u.session,**identity,operation=lambda:first)
    assert exc.value.status==403
    clock.advance(seconds=48*3600+1)
    with UnitOfWork(app.state.sessions) as u:
        fresh=idem.execute(u.session,**{**identity,'body':{'value':2}},operation=lambda:StoredResult(200,{'expired':True}))
        u.commit()
    assert fresh.status_code==200

def test_fg06_clock_and_scanner_lifecycle(env):
    app,client,clock,seed=env
    assert local_date(clock.now()).isoformat()=='2026-10-30'
    clock.advance(seconds=20*3600)
    assert local_date(clock.now()).isoformat()=='2026-10-31'
    scanner=app.state.scanner
    assert scanner.task is None
    scanner.tick()
    assert scanner.last_tick_at==clock.now()
    async def check():
        enabled=Scanner(clock,enabled=True,interval=999)
        await enabled.start()
        original=enabled.task
        await enabled.start()
        assert enabled.task is original
        await asyncio.sleep(0)  # yield only; no wall-clock waiting
        assert enabled.last_tick_at==clock.now()
        await enabled.stop()
        assert enabled.task is None and original.done() and enabled.status=='stopped'
    asyncio.run(check())

def test_fg07_501_validation_and_scope(env,tokens):
    app,client,clock,seed=env
    path=f"/api/v1/elders/{seed['elder']['elder_id']}/profile"
    body={'expected_version':1,'patch':{'display_name':'更新'}}
    r=client.put(path,json=body,headers=tokens['elder'])
    if 'PROF02' in app.state.capabilities_declared:
        assert r.status_code==200, r.text
    else:
        assert r.status_code==501 and r.json()['error']['code']=='MODULE_NOT_IMPLEMENTED'
    assert client.put(path,json=body,headers=tokens['bound_child']).json()['error']['code']=='PROPOSAL_REQUIRED'
    assert client.put(path,json={'expected_version':0,'patch':{}},headers=tokens['elder']).status_code==422
    assert client.put(path,json=body,headers={'Authorization':tokens['elder']['Authorization']}).status_code==422
    assert client.get('/api/v1/checkins/absent',headers=tokens['elder']).status_code==405
    r=client.put('/api/v1/checkins/absent',json={'expected_version':1,'payload':{'activity':'walk','duration_minutes':20}},headers=tokens['elder'])
    assert r.status_code==404

def test_fg08_contract_difference_and_architecture(tmp_path):
    assert check_contract(DEFAULT_PATH)
    snapshot=tmp_path/'openapi.json'
    snapshot.write_bytes(export_bytes())
    assert check_contract(snapshot)
    doc=json.loads(snapshot.read_bytes())
    del doc['paths']['/api/v1/health']
    snapshot.write_text(json.dumps(doc),encoding='utf-8')
    assert not check_contract(snapshot)
    doc=json.loads(export_bytes())
    doc['components']['schemas']['CodeRequest']['properties']['phone']['type']='integer'
    snapshot.write_text(json.dumps(doc),encoding='utf-8')
    assert not check_contract(snapshot)
    root=Path(__file__).resolve().parents[2]/'app'
    assert violations(root)==[]
    for sub in ['services','routers','application']:
        (tmp_path/sub).mkdir()
    bad=tmp_path/'services'/'health_service.py'
    bad.write_text('from app.services.profile_service import ProfileService',encoding='utf-8')
    assert violations(tmp_path)
    bad.write_text('from .profile_service import ProfileService',encoding='utf-8')
    assert violations(tmp_path)
    bad.write_text('from app.contracts.ports import ProfilePort',encoding='utf-8')
    assert violations(tmp_path)==[]
    bad.write_text('from app.services import profile_service',encoding='utf-8')
    assert violations(tmp_path)

def test_fg09_seed_repeatable_preserves_data(env):
    app,client,clock,seed=env
    elder_id=seed['elder']['elder_id']
    with UnitOfWork(app.state.sessions) as u:
        elder=u.session.get(ElderProfile,elder_id)
        elder.profile_json={**elder.profile_json,'display_name':'用户已经修改'}
        elder.version=7
        u.session.add(User(phone='19900000005',role='child',demo_id='other-demo'))
        u.commit()
    assert framework_seed(app.state.sessions,clock)==seed
    with app.state.sessions() as tx:
        elder=tx.get(ElderProfile,elder_id)
        assert elder.version==7 and elder.profile_json['display_name']=='用户已经修改'
        assert tx.scalar(select(func.count()).select_from(User))==5
        assert tx.scalar(select(func.count()).select_from(FamilyBinding))==1
    assert app.state.settings.data_dir.name=='db'

def test_schema_semantics():
    good={'name':'demo','dose_display':'user-specified','start_date':'2026-10-30','schedule':{'mode':'after_meal','slots':[{'slot_id':'lunch','meal_slot':'lunch','delay_minutes':30}]}}
    MedicationPlanWrite.model_validate(good)
    with pytest.raises(ValidationError):
        MedicationPlanWrite.model_validate({**good,'schedule':{'mode':'fixed','slots':[{'slot_id':'x','local_time':'25:00'}]}})
    with pytest.raises(ValidationError):
        MedicationPlanWrite.model_validate({**good,'schedule':{'mode':'after_meal','slots':[good['schedule']['slots'][0]]*2}})
    with pytest.raises(ValidationError):
        TypeAdapter(CheckinWrite).validate_python({'type':'medication','occurred_at':'2026-10-30T04:00:00Z','payload':{'plan_id':'p','slot_id':'s','intake_status':'taken'}})
    with pytest.raises(ValidationError):
        TypeAdapter(ChangeProposalWrite).validate_python({'target_type':'profile','target_id':'e','operation':'create','base_version':1,'patch':{'display_name':'x'}})

def test_ports_are_replaceable(env):
    """The bundle stays a plain replaceable dataclass: any domain can be doubled
    in an isolated test without touching composition or the router layer."""
    app,client,clock,seed=env
    class FakeReport:
        def daily(self, tx, actor, elder_id, day):
            return 'injected'
    bundle=replace(compose(),reports=FakeReport())
    assert bundle.reports.daily(None,None,'e',date(2026,10,30))=='injected'
    assert bundle.checkins is not None and bundle.tasks is not None


def test_config_rejects_unimplemented_providers_and_push(tmp_path):
    from app.core.config import Settings
    # Real understanding is allowed in F2 but must be configured, never silent.
    with pytest.raises(ValueError, match='CHAT_PROVIDER=real requires'):
        Settings(data_dir=tmp_path, chat_provider='real')
    with pytest.raises(ValueError, match='Web Push'):
        Settings(data_dir=tmp_path, web_push_enabled=True)

def test_health_reports_real_database_failure(env):
    app,client,clock,seed=env
    from sqlalchemy.exc import OperationalError
    class BrokenEngine:
        def connect(self):
            raise OperationalError('SELECT 1',{},Exception('injected DB outage'))
    original=app.state.engine
    try:
        app.state.engine=BrokenEngine()
        r=client.get('/api/v1/health')
        assert r.status_code==200
        assert r.json()['data']['status']=='degraded'
        assert r.json()['data']['database']=='unavailable'
    finally:
        app.state.engine=original

def test_fg10_delivery_artifacts():
    import hashlib
    backend=Path(__file__).resolve().parents[2]
    handoff=(backend.parent/'docs'/'协作'/'框架交接记录.md').read_text(encoding='utf-8')
    assert any(s in handoff for s in ['状态：NOT_READY', '状态：F0_READY'])
    assert re.search(r'已验证代码 Git commit：`[0-9a-f]{40}`', handoff)
    # The live contract hash must be recorded by the current (F1) handoff; the F0
    # record keeps its own historical hash, so search the whole 协作 folder.
    recorded = "\n".join(p.read_text(encoding='utf-8') for p in (backend.parent/'docs'/'协作').rglob('*.md'))
    assert hashlib.sha256(DEFAULT_PATH.read_bytes()).hexdigest() in recorded
    assert (backend/'requirements.lock').is_file()
    readme=(backend/'README.md').read_text(encoding='utf-8')
    for command in ['app.seed','uvicorn','tests/framework','export_contract --check','check_architecture']:
        assert command in readme
