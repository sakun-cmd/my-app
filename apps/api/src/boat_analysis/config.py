from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    app_timezone: str = "Asia/Tokyo"
    database_url: str = "postgresql+psycopg://boat:boat@localhost:5432/boat_analysis"
    source_database_url: str | None = None
    source_schema: str = "public"
    source_mapping_path: Path = Path("../../config/source-mapping.json")
    api_cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:3000"]
    official_result_fetch_enabled: bool = True
    official_result_delay_minutes: int = 15
    official_result_retry_minutes: int = 5
    official_result_poll_seconds: int = 60
    official_result_timeout_seconds: float = 10
    official_result_max_requests_per_refresh: int = 12
    official_result_request_interval_seconds: float = 0.5
    official_result_max_response_bytes: int = 2_000_000
    official_exhibition_fetch_enabled: bool = True
    official_exhibition_lead_minutes: int = 5
    official_exhibition_retry_minutes: int = 1
    official_exhibition_timeout_seconds: float = 20
    official_exhibition_max_requests_per_refresh: int = 12
    official_exhibition_request_interval_seconds: float = 1.0
    official_win_odds_fetch_enabled: bool = True
    official_win_odds_lead_minutes: int = 3
    official_win_odds_retry_minutes: int = 1
    official_win_odds_timeout_seconds: float = 20
    official_win_odds_max_requests_per_refresh: int = 12
    official_win_odds_request_interval_seconds: float = 1.0
    boatcast_lap_fetch_enabled: bool = True
    boatcast_lap_timeout_seconds: float = 20
    boatcast_lap_max_requests_per_refresh: int = 12
    boatcast_lap_request_interval_seconds: float = 1.0
    daily_excel_enabled: bool = True
    daily_excel_hour_jst: int = 0
    daily_excel_minute_jst: int = 30
    daily_excel_output_dir: Path = Path("/app/exports")

    @field_validator("api_cors_origins", mode="before")
    @classmethod
    def parse_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("source_database_url")
    @classmethod
    def reject_shared_database(cls, value: str | None, info) -> str | None:
        if value and value == info.data.get("database_url"):
            raise ValueError("SOURCE_DATABASE_URL must not be the application DATABASE_URL")
        return value

    @field_validator("daily_excel_hour_jst")
    @classmethod
    def validate_daily_excel_hour(cls, value: int) -> int:
        if not 0 <= value <= 23:
            raise ValueError("DAILY_EXCEL_HOUR_JST must be between 0 and 23")
        return value

    @field_validator("daily_excel_minute_jst")
    @classmethod
    def validate_daily_excel_minute(cls, value: int) -> int:
        if not 0 <= value <= 59:
            raise ValueError("DAILY_EXCEL_MINUTE_JST must be between 0 and 59")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
