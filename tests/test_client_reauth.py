"""Re-auth and transport tests for app/client.py, using httpx.MockTransport.

The fake portal below behaves exactly like the real one as verified in recon:
  * POST /login  -> 200 + Set-Cookie + {"type":"redirect","location":"/meters"}
                    (and 403 if the Origin header is missing)
  * expired/missing session on /portal/* -> 401 {"error":"unauthorized"...}
  * data routes without session -> 200 {"type":"redirect","location":"/login"}
  * unknown meter -> 404 {"error":"not_found","message":"Meter not found"}
No network access happens anywhere in this file.
"""

import asyncio
from urllib.parse import parse_qs

import httpx
import pytest

from app.client import (
    SESSION_COOKIE,
    PortalAuthError,
    PortalClient,
    PortalError,
    PortalNotFoundError,
    PortalTimeoutError,
)
from app.config import Settings


def make_settings(**overrides) -> Settings:
    defaults = dict(
        urja_user="operator@urja.local",
        urja_password="test-password",
        urja_portal_base_url="https://portal.test.invalid",
        urja_max_retries=2,
    )
    defaults.update(overrides)
    return Settings(**defaults)


class FakePortal:
    """Stateful mock of the portal's verified behaviour."""

    def __init__(self):
        self.login_calls = 0
        self.request_log: list[str] = []
        self.valid_token: str | None = None  # None = every session is dead
        self.always_unauthorized = False  # for credential-failure tests
        self.fail_with: Exception | None = None  # transport failures
        self.fail_times = 0  # how many requests fail before succeeding

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.request_log.append(path)

        if self.fail_with is not None and self.fail_times > 0:
            self.fail_times -= 1
            raise self.fail_with

        if path == "/login":
            return self._login(request)

        # Auth check, mirroring the portal's 401 body exactly.
        cookie = request.headers.get("cookie", "")
        authorized = (
            self.valid_token is not None
            and f"{SESSION_COOKIE}=" in cookie
            and self.valid_token in cookie
        )

        # Data routes are verified to answer HTTP 200 + login redirect when
        # the session is dead (NOT 401 like /portal/*).
        if path == "/data/needs-login":
            if authorized and not self.always_unauthorized:
                return httpx.Response(200, json={"type": "data", "nodes": []})
            return httpx.Response(200, json={"type": "redirect", "location": "/login"})

        if not authorized or self.always_unauthorized:
            return httpx.Response(
                401,
                json={"error": "unauthorized", "message": "A valid session is required."},
            )

        if path == "/portal/meters/search":
            return httpx.Response(
                200,
                json={"data": [], "total": 0, "page": 1, "pageSize": 20},
            )
        if path.startswith("/portal/meters/") and path.endswith("/missing"):
            return httpx.Response(
                404, json={"error": "not_found", "message": "Meter not found"}
            )
        if path == "/portal/boom":
            return httpx.Response(500, text="internal portal error")
        return httpx.Response(404, json={"error": "not_found", "message": "no route"})

    def _login(self, request: httpx.Request) -> httpx.Response:
        form = parse_qs(request.content.decode())
        # SvelteKit CSRF: Origin must be present (verified 403 otherwise).
        if not request.headers.get("origin"):
            return httpx.Response(403, text="Cross-site POST form submissions are forbidden")
        if form.get("email") != ["operator@urja.local"] or form.get("password") != [
            "test-password"
        ]:
            return httpx.Response(
                200, json={"error": "invalid credentials"}  # portal returns 200 + no cookie
            )
        self.login_calls += 1
        self.valid_token = f"token-{self.login_calls}"
        return httpx.Response(
            200,
            json={"type": "redirect", "status": 303, "location": "/meters"},
            headers={
                "set-cookie": (
                    f"{SESSION_COOKIE}={self.valid_token}; Max-Age=3600; "
                    "Path=/; HttpOnly; Secure; SameSite=Lax"
                )
            },
        )


def run(coro):
    return asyncio.run(coro)


def test_login_uses_verified_form_and_origin():
    portal = FakePortal()

    async def scenario():
        client = PortalClient(make_settings(), transport=httpx.MockTransport(portal))
        try:
            return await client.get_json("/portal/meters/search", {"q": "", "page": 1})
        finally:
            await client.aclose()

    payload = run(scenario())
    assert payload["total"] == 0
    assert portal.login_calls == 1


def test_concurrent_401s_trigger_exactly_one_relogin():
    """Ten parallel requests on a dead session must produce ONE login."""
    portal = FakePortal()  # valid_token None -> all requests 401 at first

    async def scenario():
        client = PortalClient(make_settings(), transport=httpx.MockTransport(portal))
        try:
            return await asyncio.gather(
                *[client.get_json("/portal/meters/search", {"page": 1}) for _ in range(10)]
            )
        finally:
            await client.aclose()

    results = run(scenario())
    assert len(results) == 10
    assert portal.login_calls == 1  # single-flight re-login


def test_mid_session_expiry_relogins_once():
    """Session dies while the client is running (1h Max-Age elapsed)."""
    portal = FakePortal()

    async def scenario():
        client = PortalClient(make_settings(), transport=httpx.MockTransport(portal))
        try:
            first = await client.get_json("/portal/meters/search", {"page": 1})
            portal.valid_token = "expired-token"  # simulate the 1h cookie dying
            second = await client.get_json("/portal/meters/search", {"page": 1})
            return first, second
        finally:
            await client.aclose()

    run(scenario())
    assert portal.login_calls == 2  # initial login + exactly one re-login


def test_data_route_login_redirect_is_treated_as_expiry():
    """HTTP 200 {'type':'redirect','location':'/login'} = session expired."""
    portal = FakePortal()

    async def scenario():
        client = PortalClient(make_settings(), transport=httpx.MockTransport(portal))
        try:
            # Call 1: dead session -> data route says "login" (HTTP 200) ->
            # re-login -> retry returns real data.
            first = await client.get_json("/data/needs-login")
            # Call 2: even a fresh cookie is rejected by the portal, so the
            # retry lands on the login redirect again -> auth error.
            portal.always_unauthorized = True
            second = await client.get_json("/data/needs-login")
            return first, second
        finally:
            await client.aclose()

    with pytest.raises(PortalAuthError):
        run(scenario())
    # One login for the normal expiry, one for the unrefreshable session.
    assert portal.login_calls == 2


def test_bad_credentials_raise_generic_auth_error_without_secrets():
    portal = FakePortal()
    portal.always_unauthorized = False

    # Make login return 200 but set no cookie (portal's real failure mode).
    def broken_login(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/login":
            portal.request_log.append("/login")
            return httpx.Response(200, json={"error": "invalid credentials"})
        return portal(request)

    async def scenario():
        client = PortalClient(
            make_settings(urja_password="super-secret-pw"),
            transport=httpx.MockTransport(broken_login),
        )
        try:
            await client.get_json("/portal/meters/search", {"page": 1})
        finally:
            await client.aclose()

    with pytest.raises(PortalAuthError) as exc:
        run(scenario())
    assert "super-secret-pw" not in str(exc.value)  # never leak credentials


def test_missing_session_that_cannot_be_refreshed_is_auth_error():
    portal = FakePortal()
    portal.valid_token = None
    portal.always_unauthorized = True  # even a fresh cookie is rejected

    async def scenario():
        client = PortalClient(make_settings(), transport=httpx.MockTransport(portal))
        try:
            await client.get_json("/portal/meters/search", {"page": 1})
        finally:
            await client.aclose()

    with pytest.raises(PortalAuthError):
        run(scenario())


def test_unknown_meter_maps_to_not_found_with_portal_message():
    portal = FakePortal()

    async def scenario():
        client = PortalClient(make_settings(), transport=httpx.MockTransport(portal))
        try:
            await client.get_json("/portal/meters/J000000/missing")
        finally:
            await client.aclose()

    with pytest.raises(PortalNotFoundError) as exc:
        run(scenario())
    assert exc.value.message == "Meter not found"
    assert exc.value.status_code == 404


def test_portal_500_is_reported_without_retry():
    portal = FakePortal()

    async def scenario():
        client = PortalClient(make_settings(), transport=httpx.MockTransport(portal))
        try:
            await client.get_json("/portal/meters/search", {"page": 1})  # establish session
            portal.request_log.clear()
            await client.get_json("/portal/boom")
        finally:
            await client.aclose()

    with pytest.raises(PortalError) as exc:
        run(scenario())
    assert exc.value.status_code == 502
    # Portal 5xx must not be retried (only transient transport errors are).
    assert portal.request_log.count("/portal/boom") == 1


def test_transport_failures_are_retried_then_succeed():
    portal = FakePortal()
    portal.fail_with = httpx.ConnectError("boom")
    portal.fail_times = 2  # fails twice, third attempt works

    async def scenario():
        client = PortalClient(make_settings(), transport=httpx.MockTransport(portal))
        try:
            return await client.get_json("/portal/meters/search", {"page": 1})
        finally:
            await client.aclose()

    payload = run(scenario())
    assert payload["page"] == 1
    # Exactly 3 sends for the transport budget (2 failed + 1 that returned 401
    # because there was no session yet), then the post-re-login attempt.
    first_login = portal.request_log.index("/login")
    assert portal.request_log.count("/portal/meters/search") == first_login + 1
    assert first_login == 3  # fail, fail, 401 - then login


def test_persistent_timeout_maps_to_504():
    portal = FakePortal()
    portal.fail_with = httpx.ReadTimeout("slow")
    portal.fail_times = 99  # every attempt times out

    async def scenario():
        client = PortalClient(make_settings(), transport=httpx.MockTransport(portal))
        try:
            await client.get_json("/portal/meters/search", {"page": 1})
        finally:
            await client.aclose()

    with pytest.raises(PortalTimeoutError) as exc:
        run(scenario())
    assert exc.value.status_code == 504
