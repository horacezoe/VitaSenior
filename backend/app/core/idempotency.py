import hashlib, json
from datetime import timedelta
from dataclasses import dataclass
from typing import Callable
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.identity import IdempotencyRecord
from app.core.clock import Clock
from app.core.errors import AppError

@dataclass(frozen=True)
class StoredResult:
    status_code: int
    data: dict

class Idempotency:
    def __init__(self, clock: Clock):
        self.clock = clock
    def execute(self, tx: Session, *, actor_id: str, method: str, path: str, key: str, body: object, operation: Callable[[], StoredResult]) -> StoredResult:
        """Caller checks current resource access FIRST; caller commits everything once.

        Must run in UnitOfWork(write=True). Errors are not cached. Store business
        data/status only; response metadata/request_id belongs to current request.
        """
        if not key or len(key) > 200:
            raise AppError(422, "VALIDATION_ERROR", "Idempotency-Key must contain 1..200 characters")
        digest = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
        record = tx.scalar(select(IdempotencyRecord).where(IdempotencyRecord.actor_id == actor_id, IdempotencyRecord.method == method.upper(), IdempotencyRecord.path == path, IdempotencyRecord.key == key))
        if record and record.expires_at <= self.clock.now():
            tx.delete(record)
            tx.flush()
            record = None
        if record:
            if record.request_hash != digest:
                raise AppError(409, "IDEMPOTENCY_CONFLICT", "Same key used with a different request")
            return StoredResult(record.status_code, record.response_json)
        result = operation()
        tx.add(IdempotencyRecord(actor_id=actor_id, method=method.upper(), path=path, key=key, request_hash=digest, response_json=result.data, status_code=result.status_code, expires_at=self.clock.now() + timedelta(hours=48)))
        tx.flush()
        return result
