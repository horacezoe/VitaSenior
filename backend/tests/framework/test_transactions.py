from concurrent.futures import ThreadPoolExecutor
from sqlalchemy import select, func
from fastapi import Header
from app.core.uow import UnitOfWork
from app.core.idempotency import StoredResult
from app.models.identity import User, IdempotencyRecord
from app.routers.dependencies import Context
from app.schemas.common import Envelope
from app.schemas.identity import Account

def test_idempotent_writes_serialize_concurrently(env):
    app,client,clock,seed=env
    def write():
        with UnitOfWork(app.state.sessions) as u:
            def operation():
                user=User(phone='19900000007',role='child',demo_id='concurrent')
                u.session.add(user)
                u.session.flush()
                return StoredResult(201,{'id':user.id})
            result=app.state.idempotency.execute(u.session,actor_id=seed['elder']['user_id'],method='POST',path='/concurrent',key='same',body={},operation=operation)
            u.commit()
            return result
    with ThreadPoolExecutor(max_workers=2) as pool:
        a,b=list(pool.map(lambda _:write(),[1,2]))
    assert a==b
    with app.state.sessions() as tx:
        assert tx.scalar(select(func.count()).select_from(User).where(User.demo_id=='concurrent'))==1
        assert tx.scalar(select(func.count()).select_from(IdempotencyRecord))==1

def test_http_idempotency_and_failure_envelope(env,tokens):
    app,client,clock,seed=env
    # Test-only application flow: validates error handling + actual same-tx storage.
    @app.post('/_framework/write',response_model=Envelope[Account])
    def flow(body: Account,ctx: Context, idempotency_key: str=Header(alias='Idempotency-Key')):
        def operation():
            ctx.tx.add(User(phone=body.phone,role=body.role.value,demo_id='http-test'))
            ctx.tx.flush()
            return StoredResult(201,body.model_dump(mode='json'))
        result=app.state.idempotency.execute(ctx.tx,actor_id=ctx.actor.user_id,method='POST',path='/_framework/write',key=idempotency_key,body=body.model_dump(mode='json'),operation=operation)
        ctx.uow.commit()
        from fastapi.responses import JSONResponse
        from fastapi.encoders import jsonable_encoder
        return JSONResponse(status_code=result.status_code,content=jsonable_encoder(app.state.respond(ctx.request,result.data)))
    body={'phone':'19900000006','role':'child'}
    first=client.post('/_framework/write',headers=tokens['elder'],json=body)
    second=client.post('/_framework/write',headers=tokens['elder'],json=body)
    assert first.status_code==second.status_code==201
    assert first.json()['data']==second.json()['data']
    assert first.json()['meta']['request_id']!=second.json()['meta']['request_id']
    conflict=client.post('/_framework/write',headers=tokens['elder'],json={**body,'phone':'19900000005'})
    assert conflict.status_code==409 and conflict.json()['error']['code']=='IDEMPOTENCY_CONFLICT'
    @app.post('/_framework/fail')
    def fail(ctx: Context):
        ctx.tx.add(User(phone='19900000008',role='child',demo_id='rollback'))
        ctx.tx.flush()
        raise RuntimeError('injected application failure')
    failed=client.post('/_framework/fail',headers=tokens['elder'])
    assert failed.status_code==500 and failed.json()['error']['code']=='INTERNAL_ERROR'
    assert failed.headers['X-Request-ID']==failed.json()['meta']['request_id']
    with app.state.sessions() as tx:
        assert tx.scalar(select(User).where(User.phone=='19900000008')) is None
