from collections.abc import Iterator

import logging

from sqlalchemy import inspect, text
from sqlmodel import Session, SQLModel, create_engine

from .config import BACKEND_DIR, get_settings

_settings = get_settings()
_connect_args = {"check_same_thread": False} if _settings.database_url.startswith("sqlite") else {}
_url = _settings.database_url
# A relative SQLite path ("sqlite:///./mandilink.db") always means backend/mandilink.db.
if _url.startswith("sqlite:///") and not _url.startswith("sqlite:////") and ":" not in _url[len("sqlite:///"):]:
    _rel = _url[len("sqlite:///"):]
    _url = "sqlite:///" + (BACKEND_DIR / _rel).resolve().as_posix()
# Render/Supabase give postgres:// or postgresql:// URLs; use the psycopg 3 driver.
for _prefix in ("postgres://", "postgresql://"):
    if _url.startswith(_prefix):
        _url = "postgresql+psycopg://" + _url[len(_prefix):]
        break

engine = create_engine(_url, connect_args=_connect_args, pool_pre_ping=True)


def init_db() -> None:
    from . import models  # noqa: F401  (register tables)

    SQLModel.metadata.create_all(engine)
    _add_missing_columns()


def _add_missing_columns() -> None:
    """Tiny forward-only migration: add nullable columns that newer versions of
    the models introduced, so an existing database keeps working after upgrade."""
    insp = inspect(engine)
    with engine.begin() as conn:
        for table in SQLModel.metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in have or not col.nullable:
                    continue
                ddl = col.type.compile(dialect=engine.dialect)
                conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {ddl}'))
                logging.getLogger("mandilink.db").info("Added column %s.%s", table.name, col.name)


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
