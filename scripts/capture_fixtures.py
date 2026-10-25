"""Capture real portal responses as test fixtures (read-only GETs).

Run once with URJA_USER/URJA_PASS set; writes tests/fixtures/*.json.
The fixtures are exact portal bodies - unit tests never contact the portal.
"""

import json
import os
import pathlib
import sys
import time

import httpx

BASE = "https://urja-ops.flockenergy.tech"
USER = os.environ.get("URJA_USER")
PASSWORD = os.environ.get("URJA_PASS")
FIXTURES = pathlib.Path(__file__).resolve().parents[1] / "tests" / "fixtures"


def save(name: str, payload) -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    path = FIXTURES / name
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {path}")


def main() -> None:
    if not USER or not PASSWORD:
        sys.exit("URJA_USER / URJA_PASS env vars must be set")

    with httpx.Client(base_url=BASE, follow_redirects=False, timeout=25.0) as client:
        r = client.post(
            "/login",
            data={"email": USER, "password": PASSWORD},
            headers={"Origin": BASE},
        )
        assert r.status_code == 200 and r.cookies, (r.status_code, r.text)
        print("login ok")

        time.sleep(1.0)
        save("meters_search_page1.json", client.get(
            "/portal/meters/search", params={"q": "", "page": 1}).json())

        time.sleep(1.0)
        save("dts_page1.json", client.get(
            "/portal/dts", params={"page": 1}).json())

        time.sleep(1.0)
        # One full day of readings (~48 rows) keeps the fixture readable.
        save("energy_one_day.json", client.get(
            "/portal/meters/J100000/energy",
            params={"from": "2026-06-24", "to": "2026-06-24"}).json())

        time.sleep(1.0)
        save("geo_j100000.json", client.get("/portal/meters/J100000/geo").json())

        time.sleep(1.0)
        save("detail_dataraw_j100000.json",
             client.get("/meters/J100000/__data.json").json())

        time.sleep(1.0)
        save("detail_unknown_meter.json",
             client.get("/meters/NOPE999/__data.json").json())

        time.sleep(1.0)
        # Simulate expiry: a separate client with no cookies.
        anon = httpx.Client(base_url=BASE, follow_redirects=False, timeout=25.0)
        save("portal_unauthorized.json",
             anon.get("/portal/meters/search", params={"q": "", "page": 1}).json())
        anon.close()


if __name__ == "__main__":
    main()
