"""Capture dashboard screenshots for the README using the offline
fixture-backed fake portal (real captured data, zero network).

Usage:
    python scripts/capture_fixtures.py   # (already-run) capture API fixtures
    python scripts/capture_screenshots.py

Writes docs/screenshots/*.png. Requires: pip install -r requirements-dev.txt
then: python -m playwright install chromium
"""

from __future__ import annotations

import pathlib
import socket
import sys
import threading
import time
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests_e2e"))

import os  # noqa: E402

os.environ.setdefault("URJA_USER", "screenshot@example.invalid")
os.environ.setdefault("URJA_PASSWORD", "not-a-real-password")
os.environ.setdefault("URJA_PORTAL_BASE_URL", "https://portal.test.invalid")

from fake_portal import E2EFakePortal  # noqa: E402

OUT_DIR = ROOT / "docs" / "screenshots"


def start_server() -> str:
    import uvicorn

    from app.main import app

    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    threading.Thread(target=server.run, daemon=True).start()

    url = f"http://127.0.0.1:{port}"
    for _ in range(150):
        try:
            urllib.request.urlopen(url + "/healthz", timeout=1)
            break
        except OSError:
            time.sleep(0.1)
    else:
        raise RuntimeError("uvicorn did not come up in time")

    # Swap the portal AFTER the lifespan startup, which otherwise re-creates a
    # real PortalClient from settings over our assignment (same as E2E conftest).
    app.state.portal = E2EFakePortal()
    return url


def main() -> None:
    from playwright.sync_api import sync_playwright

    url = start_server()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 950}, device_scale_factor=2)
        page = context.new_page()
        page.set_default_timeout(15000)

        def settle(ms: int = 900):
            page.wait_for_timeout(ms)

        # 1 — Network Overview (wait until stats finish hydrating)
        page.goto(url + "/", wait_until="domcontentloaded")
        page.wait_for_function(
            "document.querySelector('#stats-updated') && document.querySelector('#stats-updated').textContent !== ''"
        )
        try:
            page.wait_for_function('document.fonts.status === "loaded"', timeout=8000)
        except Exception:
            pass  # font CDN hiccup shouldn't kill the capture run
        settle()
        page.screenshot(path=OUT_DIR / "01-overview.png", full_page=True)
        print("captured 01-overview.png")

        # 2 — Live Asset Map (wait for proximity markers to draw)
        page.click('[data-view="map"]')
        page.wait_for_selector("#map .leaflet-overlay-pane path")
        settle(1400)  # let map tiles paint
        page.screenshot(path=OUT_DIR / "02-live-map.png")
        print("captured 02-live-map.png")

        # 3 — Load Curve (real 48-interval chart for J100000)
        page.click('[data-view="consumption"]')
        page.wait_for_selector("#consumptionChart", state="visible")
        page.wait_for_function(
            "document.querySelector('#export-cons-btn') && !document.querySelector('#export-cons-btn').disabled"
        )
        settle(700)  # chart entrance animation
        page.screenshot(path=OUT_DIR / "03-load-curve.png")
        print("captured 03-load-curve.png")

        # 4 — Transformers browser (drill into DT-001)
        page.click('[data-view="transformers"]')
        page.wait_for_selector("#dt-list .dt-row")
        page.wait_for_selector("#dt-meters .meter-chip")
        settle()
        page.screenshot(path=OUT_DIR / "04-transformers.png")
        print("captured 04-transformers.png")

        # 5 — Hierarchy tree
        page.click('[data-view="hierarchy"]')
        page.wait_for_selector("#hierarchy-tree-container .tree-row")
        settle()
        page.screenshot(path=OUT_DIR / "05-hierarchy.png")
        print("captured 05-hierarchy.png")

        # 6 — Meter Index (filter to faulty for a story-telling shot)
        page.click('[data-view="meters"]')
        page.wait_for_selector("#meters-table-body tr td")
        settle()
        page.screenshot(path=OUT_DIR / "06-meter-index.png")
        print("captured 06-meter-index.png")

        # 7 — Detail slide-over (bonus shot)
        page.locator("#meters-table-body").get_by_role("button", name="Details").first.click()
        page.wait_for_selector("#slideover-body .kv-list")
        settle(400)
        page.screenshot(path=OUT_DIR / "07-meter-detail.png")
        print("captured 07-meter-detail.png")

        browser.close()

    print("done —", OUT_DIR)


if __name__ == "__main__":
    main()
