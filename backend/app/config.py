import re
from pathlib import Path
from typing import Literal

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT / ".env", extra="ignore", hide_input_in_errors=True
    )

    database_url: SecretStr
    dev_mode: bool = False
    session_ttl_seconds: int = 3600
    database_schema: str = "public"
    business_clock_mode: Literal["system", "fixture"] = "system"
    deepseek_api_key: SecretStr | None = None
    deepseek_model: Literal["deepseek-flash"] = "deepseek-flash"

    @model_validator(mode="after")
    def validate_local(self):
        url = make_url(self.database_url.get_secret_value())
        if url.drivername != "postgresql+psycopg":
            raise ValueError("PostgreSQL with psycopg is required")
        if url.host not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("M0 only supports a loopback PostgreSQL server")
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", self.database_schema):
            raise ValueError("Invalid database schema")
        if not 60 <= self.session_ttl_seconds <= 86400:
            raise ValueError("Session TTL must be 60..86400 seconds")
        if self.business_clock_mode == "fixture" and not self.dev_mode:
            raise ValueError("Fixture business clock is only permitted in DEV_MODE")
        return self
