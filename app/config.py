from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="FAQ_", extra="ignore")

    environment: Literal["development", "test", "production"] = "development"
    database_url: str = "postgresql+psycopg://faq:faq@localhost:55433/faq"
    database_pool_size: int = Field(default=4, ge=1, le=50)
    database_max_overflow: int = Field(default=1, ge=0, le=50)
    database_pool_timeout: float = Field(default=5, gt=0, le=60)
    database_pool_recycle: int = Field(default=1800, ge=30, le=86400)
    organization_name: str = "FAQ Development"
    bootstrap_admin_email: str | None = None
    session_secret: SecretStr = Field(
        default=SecretStr("development-only-session-secret-key"), min_length=32
    )
    session_lifetime_hours: int = Field(default=12, ge=1, le=168)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    assistant_model: str = "google-vertex:gemini-2.5-flash"
    public_base_url: str = "http://localhost:8000"
    firebase_api_key: str | None = None
    firebase_auth_domain: str | None = None
    firebase_project_id: str | None = None
    firebase_app_id: str | None = None
    all_responded_grace_minutes: int = Field(default=15, ge=0, le=1440)
    jobs_audience: str | None = None
    jobs_caller_email: str | None = None
    jobs_batch_size: int = Field(default=100, ge=1, le=1000)
    jobs_max_batches: int = Field(default=10, ge=1, le=100)
    operator_audience: str | None = None
    operator_allowed_emails: frozenset[str] = Field(default_factory=frozenset)

    def database_engine_args(self) -> dict[str, object]:
        return {
            "pool_pre_ping": True,
            "pool_size": self.database_pool_size,
            "max_overflow": self.database_max_overflow,
            "pool_timeout": self.database_pool_timeout,
            "pool_recycle": self.database_pool_recycle,
            "connect_args": {"connect_timeout": max(1, min(5, int(self.database_pool_timeout)))},
        }

    def _validate_database(self, errors: list[str]) -> None:
        if "localhost" in self.database_url or self.database_url == Settings.model_fields[
            "database_url"
        ].default:
            errors.append("database_url must not use localhost or the development default")

    def validate_public_startup(self) -> None:
        if self.environment != "production":
            return
        errors: list[str] = []
        self._validate_database(errors)
        if self.session_secret.get_secret_value() == "development-only-session-secret-key":
            errors.append("session_secret must not use the development default")
        if not self.public_base_url.startswith("https://"):
            errors.append("public_base_url must use HTTPS")
        required_firebase = {
            "firebase_api_key": self.firebase_api_key,
            "firebase_auth_domain": self.firebase_auth_domain,
            "firebase_project_id": self.firebase_project_id,
            "firebase_app_id": self.firebase_app_id,
        }
        missing = [name for name, value in required_firebase.items() if not value]
        if missing:
            errors.append(f"missing Firebase configuration: {', '.join(missing)}")
        if errors:
            raise ValueError("; ".join(errors))

    def validate_operator_startup(self) -> None:
        if self.environment != "production":
            return
        errors: list[str] = []
        self._validate_database(errors)
        required_identity = {
            "operator_audience": self.operator_audience,
            "operator_allowed_emails": self.operator_allowed_emails,
        }
        missing_identity = [name for name, value in required_identity.items() if not value]
        if missing_identity:
            errors.append(f"missing Google identity configuration: {', '.join(missing_identity)}")
        if errors:
            raise ValueError("; ".join(errors))

    def validate_jobs_startup(self) -> None:
        if self.environment != "production":
            return
        errors: list[str] = []
        self._validate_database(errors)
        required_identity = {
            "jobs_audience": self.jobs_audience,
            "jobs_caller_email": self.jobs_caller_email,
        }
        missing_identity = [name for name, value in required_identity.items() if not value]
        if missing_identity:
            errors.append(f"missing Google identity configuration: {', '.join(missing_identity)}")
        if errors:
            raise ValueError("; ".join(errors))

    def validate_migration_startup(self) -> None:
        if self.environment != "production":
            return
        errors: list[str] = []
        self._validate_database(errors)
        if errors:
            raise ValueError("; ".join(errors))


@lru_cache
def get_settings() -> Settings:
    return Settings()
