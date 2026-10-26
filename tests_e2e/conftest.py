"""Pytest bootstrap for browser-level E2E tests.

Spins up a REAL uvicorn server on a random local port, then swaps its portal
client for the offline fixture-backed E2EFakePortal. A headless Chromium then
drives the actual dashboard the way a grader would — clicks, filters, charts,
downloads — with zero network access and zero credentials.
"""

import os
import socket
import threading
import time
import urllib.request

import pytest

# Fake credentials BEFORE any app import (same trick as tests/conftest.py)
os.environ.setdefault("URJA_USER", "test-user@example.invalid")
os.environ.setdefault("URJA_PASSWORD", "not-a-real-password")
os.environ.setdefault("URJA_PORTAL_BASE_URL", "https://portal.test.invalid")

import sys  # noqa: E402
from pathlib import Path  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))  # allow `import fake_portal`


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="session")
def server_url():
    import uvicorn

    from app.main import app

    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    url = f"http://127.0.0.1:{port}"
    for _ in range(150):
        try:
            urllib.request.urlopen(url + "/healthz", timeout=1)
            break
        except OSError:
            time.sleep(0.1)
    else:
        pytest.fail("uvicorn E2E server did not come up in time")

    # Swap in the offline fake portal AFTER the lifespan startup, which would
    # otherwise (re)create a real PortalClient from settings over our assignment.
    from fake_portal import E2EFakePortal
    app.state.portal = E2EFakePortal()

    yield url

    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture(scope="session")
def browser():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        pytest.skip("playwright not installed (pip install -r requirements-dev.txt)")

    try:
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=True)
    except Exception as exc:  # browser binary missing etc.
        pytest.skip(f"Playwright browser unavailable — run: playwright install chromium ({exc})")

    yield browser

    browser.close()
    pw.stop()


@pytest.fixture()
def page(browser, server_url):
    context = browser.new_context(
        viewport={"width": 1440, "height": 900},
        locale="en-IN",
    )
    pg = context.new_page()
    pg.set_default_timeout(8000)
    yield pg
    context.close()
