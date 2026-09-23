from collections.abc import Generator
from typing import Annotated

from fastapi import Depends
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session

from .config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    connect_args={
        "connect_timeout": 5,
        "options": f"-c timezone={settings.app_timezone}",
    },
)


def get_db() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session


DbSession = Annotated[Session, Depends(get_db)]


def create_source_engine() -> Engine:
    source_url = get_settings().source_database_url
    if not source_url:
        raise RuntimeError("SOURCE_DATABASE_URL is not configured")
    return create_engine(
        source_url,
        pool_pre_ping=True,
        isolation_level="REPEATABLE READ",
        connect_args={
            "connect_timeout": 5,
            "options": "-c default_transaction_read_only=on "
            "-c statement_timeout=30000 -c lock_timeout=5000",
        },
    )
