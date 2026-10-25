"""Environment-based settings for the Urja Meter Ops REST wrapper.

All configuration comes from environment variables (optionally a gitignored
.env file, which pydantic-settings reads automatically). No secrets are ever
hardcoded; .env.example only shows variable *names*.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings, loaded from environment / .env."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Portal credentials (READ-ONLY account).
    urja_user: str
    urja_password: str

    # Where the legacy portal lives.
    urja_portal_base_url: str = "https://urja-ops.flockenergy.tech"

    # Outbound timeouts (seconds).
    urja_timeout_seconds: float = 15.0
    urja_login_timeout_seconds: float = 15.0

    # Retries for transient failures on idempotent GETs.
    urja_max_retries: int = 2


settings = Settings()
