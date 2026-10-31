from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy import create_engine, event, DateTime, inspect
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
    assert_schema_current(engine)

def assert_schema_current(engine) -> None:
    """Fail fast on an out-of-date DATA_DIR.

    `create_all` only creates missing tables; it never adds columns to an existing
    one. Without this check an old database surfaces as confusing SQL errors during
    a demo. The message says exactly what to do: use a fresh DATA_DIR (or re-export
    the demo data), because F1 has no migration tooling.
    """
    inspector = inspect(engine)
    existing = set(inspector.get_table_names())
    problems = []
    # Plain dict iteration on purpose: sorted_tables warns about the intentional
    # change_proposals <-> notifications cycle and the order is irrelevant here.
    for table in Base.metadata.tables.values():
        if table.name not in existing:
            continue
        actual = {column["name"] for column in inspector.get_columns(table.name)}
        missing = [column.name for column in table.columns if column.name not in actual]
        if missing:
            problems.append(f"{table.name}({', '.join(missing)})")
    if problems:
        raise RuntimeError(
            "DATABASE_SCHEMA_OUTDATED: this DATA_DIR predates the current models "
            f"({'; '.join(problems)}). F1 has no migrations - start from an empty "
            "DATA_DIR (or DATABASE_URL) and recreate the demo data.")

def sessions(engine):
    return sessionmaker(bind=engine, expire_on_commit=False)
