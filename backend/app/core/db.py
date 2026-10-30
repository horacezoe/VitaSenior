from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy import create_engine, event, DateTime
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.types import TypeDecorator

class Base(DeclarativeBase):
    pass
class UTCDateTime(TypeDecorator):
    impl = DateTime
    cache_ok = True
    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive timestamp is forbidden")
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    def process_result_value(self, value, dialect):
        return value.replace(tzinfo=timezone.utc) if value is not None else None

def build_engine(data_dir: Path, database_url: str | None = None):
    data_dir.mkdir(parents=True, exist_ok=True)
    url = make_url(database_url or ("sqlite:///" + str((data_dir / "vitasenior.sqlite3").resolve())))
    if url.drivername != "sqlite" or not url.database or url.database == ":memory:":
        raise ValueError("Use a file-backed sqlite:/// URL for F0")
    Path(url.database).resolve().parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 5})
    @event.listens_for(engine, "connect")
    def pragmas(conn, _):
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
    return engine

def create_tables(engine):
    from app.models import identity, health, agent  # register all tables
    Base.metadata.create_all(engine)

def sessions(engine):
    return sessionmaker(bind=engine, expire_on_commit=False)
