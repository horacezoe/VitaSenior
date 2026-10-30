from app.core.uow import UnitOfWork


def transact(env, function, *args, **kwargs):
    with UnitOfWork(env.factory) as uow:
        result = function(uow.session, env.actor, env.elder, *args, **kwargs)
        uow.commit()
        return result
