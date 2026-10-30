from app.contracts.bundle import ServiceBundle
from app.core.errors import unimplemented
from app.core.idempotency import StoredResult
from app.core.uow import UnitOfWork
from app.routers.dependencies import check_access, check_resource, RESOURCE_MODELS
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse


def perform(auth, *, service_name, operation, elder_id=None, resource=None,
            scope="read", body=None, key=None, status=200, snapshot=False):
    """Short transaction coordinating frozen ports and shared idempotency.

    Read endpoints that materialize goals deliberately use BEGIN IMMEDIATE so
    concurrent TASK/report requests cannot race the daily unique constraint.
    Until A connects the application clock in composition, fail explicitly.
    """
    request = auth.request
    services = request.app.state.services
    target = getattr(services, service_name)
    write = key is not None or snapshot or request.method not in {"GET", "HEAD"}
    with UnitOfWork(request.app.state.sessions, write=write) as uow:
        tx = uow.session
        if resource:
            kind, resource_id = resource
            check_resource(request, tx, auth.actor, kind, resource_id, scope)
            elder_id = tx.get(RESOURCE_MODELS[kind], resource_id).elder_id
        else:
            check_access(request, tx, auth.actor, elder_id, scope)
        operation_id = request.scope["route"].operation_id
        if operation_id not in request.app.state.capabilities_declared:
            unimplemented()
        if getattr(target, "clock", None) is not request.app.state.clock:
            unimplemented()

        def execute():
            result = operation(services, tx, auth.actor, elder_id)
            actual_status = 200 if status == 201 and service_name == "checkins" and result.version > 1 else status
            return StoredResult(actual_status, result.model_dump(mode="json", exclude_unset=True))

        if key is not None:
            result = request.app.state.idempotency.execute(tx, actor_id=auth.actor.user_id,
                method=request.method, path=request.url.path, key=key, body=body, operation=execute)
        else:
            result = execute()
        uow.commit()
    response = request.app.state.respond(request, result.data)
    if status == 201 and service_name == "checkins" and result.status_code == 200:
        response["meta"].replaced = True
    return JSONResponse(status_code=result.status_code, content=jsonable_encoder(response))

def unavailable(services: ServiceBundle) -> None:
    """F2 replaces this entry with named flows coordinating typed ports and UoW."""
    unimplemented()
