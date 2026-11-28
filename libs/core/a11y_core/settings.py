from functools import lru_cache
from typing import Literal
from urllib.parse import quote

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEV_MASTER_KEY = "Q2OoEdjRtijEf6Bd8VUo4q6_2oBKlFXaQopiFpf0lgc="


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "a11y"
    a11y_owner_password: str = "owner-dev-only"
    a11y_app_password: str = "app-dev-only"
    a11y_admin_password: str = "admin-dev-only"

    redis_url: str = "redis://localhost:6379/0"

    env: str = "development"
    # Comma-separated Fernet keys. The FIRST encrypts; all decrypt, so rotation = prepend a new
    # key, re-save secrets, then drop the old one. Production must use KMS-managed keys
    # (ADR 0006); the default below is public and only valid in development.
    a11y_master_keys: str = "Q2OoEdjRtijEf6Bd8VUo4q6_2oBKlFXaQopiFpf0lgc="

    jwt_secret: str = Field(
        default="dev-only-change-me-dev-only-change-me-0123456789", min_length=32
    )
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 14
    cookie_secure: bool = False
    public_web_url: str = "http://localhost:3000"
    public_api_url: str = (
        ""  # shown as the server in the published API description; empty = relative
    )
    cors_origins: str = "http://localhost:3000"

    # Starting value of the platform-administrator MFA policy (admins can change it in /admin -> Settings -> auth.mfa).
    # "off" is for development only and is refused when ENV=production. Everything else asks for a code.
    mfa_super_admin_default: Literal["required", "optional", "off"] = "required"
    mfa_org_admin_default: Literal["required", "optional", "off"] = "optional"

    # DEV/TEST ONLY: comma-separated hosts the scanner may reach even though they are private
    # (e.g. "127.0.0.1" for a local fixture server). Refused when ENV=production.
    scan_dev_allow_hosts: str = ""
    # Where the pinned engine bundles live (packages/engine-bundles/dist).
    engine_bundles_dir: str = ""

    # Object storage for customer files (ADR 0020). Any S3-compatible store; RustFS locally.
    s3_endpoint_url: str = ""  # empty = the AWS default endpoint
    s3_access_key: str = "s3-dev-only"
    s3_secret_key: str = "s3-dev-only-secret"
    s3_bucket: str = "a11y-dev"
    s3_region: str = "us-east-1"
    # ClamAV daemon (clamd). Uploaded files are held back until it has passed them.
    clamd_host: str = "localhost"
    clamd_port: int = 3310

    smtp_host: str = "localhost"
    smtp_port: int = 1025
    mail_from: str = "no-reply@a11y.local"

    @model_validator(mode="after")
    def _no_dev_secrets_in_production(self) -> "Settings":
        if self.env == "production":
            if self.a11y_master_keys.startswith(_DEV_MASTER_KEY):
                raise ValueError("A11Y_MASTER_KEYS must be set to real keys in production")
            if self.jwt_secret.startswith("dev-only"):
                raise ValueError("JWT_SECRET must be set to a real secret in production")
            if self.mfa_super_admin_default == "off":
                raise ValueError("MFA_SUPER_ADMIN_DEFAULT=off is not allowed in production")
            if self.s3_access_key.startswith("s3-dev-only"):
                raise ValueError("S3_ACCESS_KEY / S3_SECRET_KEY must be set to real values in production")
            if self.scan_dev_allow_hosts:
                raise ValueError("SCAN_DEV_ALLOW_HOSTS is not allowed in production")
        return self

    def _url(self, user: str, password: str) -> str:
        return (
            f"postgresql+asyncpg://{user}:{quote(password, safe='')}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def app_database_url(self) -> str:
        return self._url("a11y_app", self.a11y_app_password)

    @property
    def owner_database_url(self) -> str:
        return self._url("a11y_owner", self.a11y_owner_password)

    @property
    def admin_database_url(self) -> str:
        return self._url("a11y_admin", self.a11y_admin_password)


@lru_cache
def get_settings() -> Settings:
    return Settings()
