import pytest
from pydantic import ValidationError

from boat_analysis.config import Settings


def test_source_and_application_database_must_differ() -> None:
    url = "postgresql+psycopg://user:password@localhost/database"
    with pytest.raises(ValidationError):
        Settings(database_url=url, source_database_url=url)


def test_cors_origins_are_parsed_from_csv() -> None:
    settings = Settings(
        database_url="postgresql+psycopg://user:password@localhost/application",
        api_cors_origins="http://localhost:3000,http://127.0.0.1:3000",
    )
    assert settings.api_cors_origins == [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]


def test_cors_origins_are_parsed_from_environment(monkeypatch) -> None:
    monkeypatch.setenv(
        "API_CORS_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000",
    )
    settings = Settings(database_url="postgresql+psycopg://user:password@localhost/application")
    assert settings.api_cors_origins == [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]
