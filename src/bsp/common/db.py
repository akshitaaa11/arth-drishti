from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine as sa_create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .config import get_env_var, get_project_root


def _resolve_database_url() -> str:
    url = get_env_var("DATABASE_URL")
    if url:
        return url

    project_root = get_project_root()
    local_dir = project_root / ".local"
    local_dir.mkdir(parents=True, exist_ok=True)
    sqlite_path = local_dir / "bsp.db"
    return f"sqlite:///{sqlite_path.as_posix()}"


def create_engine(*, database_url: str | None = None) -> Engine:
    url = database_url or _resolve_database_url()
    engine_kwargs: dict[str, object] = {"future": True}
    if url.startswith("sqlite"):
        engine_kwargs["connect_args"] = {"check_same_thread": False}
    return sa_create_engine(url, **engine_kwargs)


def get_session_factory(*, database_url: str | None = None) -> sessionmaker[Session]:
    engine = create_engine(database_url=database_url)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_session(*, database_url: str | None = None) -> Generator[Session, None, None]:
    factory = get_session_factory(database_url=database_url)
    session = factory()
    try:
        yield session
    finally:
        session.close()
