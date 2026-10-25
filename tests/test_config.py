"""Step-1 smoke tests: settings load from environment, no secrets hardcoded."""

import pathlib

from app.config import Settings


def test_settings_load_from_env():
    settings = Settings(
        urja_user="u@example.invalid",
        urja_password="pw",
        urja_portal_base_url="https://portal.example.invalid",
    )
    assert settings.urja_user == "u@example.invalid"
    assert settings.urja_max_retries == 2  # default kicks in
    assert settings.urja_timeout_seconds == 15.0


def test_env_example_has_no_secrets():
    root = pathlib.Path(__file__).resolve().parent.parent
    example = (root / ".env.example").read_text(encoding="utf-8")
    assert "URJA_USER=" in example
    # Placeholder only - the real password must never appear in the repo.
    assert "urja-ops-2026" not in example
