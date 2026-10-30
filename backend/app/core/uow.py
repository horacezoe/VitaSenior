from types import TracebackType
from sqlalchemy.orm import Session, sessionmaker

class UnitOfWork:
    """Caller owns commit. Exiting without commit (including exceptions) rolls back.

    SQLite BEGIN IMMEDIATE serializes short write flows, including idempotency
    read/compare/write and write-time resource checks. Never hold across I/O.
    """
    def __init__(self, factory: sessionmaker[Session], *, write: bool = True):
        self.factory, self.write = factory, write
    def __enter__(self) -> "UnitOfWork":
        self.session = self.factory()
        if self.write:
            self.session.connection().exec_driver_sql("BEGIN IMMEDIATE")
        return self
    def commit(self) -> None:
        self.session.commit()
    def __exit__(self, exc_type, exc, tb: TracebackType | None) -> None:
        try:
            self.session.rollback()
        finally:
            self.session.close()
