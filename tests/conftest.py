"""Pytest bootstrap: provide fake env credentials BEFORE any app import so that
app/config.py can construct Settings without a real .env file. The values are
dummies - unit tests never contact the portal (fixtures + mocks only)."""

import os

os.environ.setdefault("URJA_USER", "test-user@example.invalid")
os.environ.setdefault("URJA_PASSWORD", "not-a-real-password")
os.environ.setdefault("URJA_PORTAL_BASE_URL", "https://portal.test.invalid")
