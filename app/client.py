"""Portal adapter: talks to the legacy Urja Meter Ops portal on our behalf.

What this module guarantees (all based on PROTOCOL.md's verified findings):

  * Only GET requests are ever sent, plus the single login POST.
  * Login = POST /login with form fields {email, password} AND an Origin header
    (SvelteKit rejects cross-site POSTs with 403 otherwise; no CSRF token
    exists). Success is signalled by a Set-Cookie session token plus a JSON
    redirect body - NOT by an HTTP redirect.
  * Session lives in the httpx client's cookie jar (in-memory; a restart simply
    logs in again). The portal's session cookie lasts 1 hour (Max-Age=3600).
  * Session expiry is detected by the portal's three real behaviours:
      - /portal/* JSON endpoints answer 401 {"error":"unauthorized", ...}
      - SvelteKit HTML routes answer 302 -> /login
      - SvelteKit data routes (/meters/{id}/__data.json) answer HTTP 200 with
        {"type":"redirect","location":"/login"}
    Any of these triggers exactly ONE re-login even under concurrent requests:
    waiters queue on an asyncio.Lock and, once inside, skip logging in if
    another task already refreshed the token (they compare tokens).
  * Idempotent GETs are retried on transient transport errors/timeouts with a
    short exponential backoff (portal 5xx is NOT retried - reported as 502).
  * Nothing from the portal is passed through unexamined: parsing/normalisation
    happens in this file (see part 2), and messy values become null + warnings.

Upstream failures surface as PortalError subclasses carrying an HTTP status
for our routes to map (404 / 502 / 504). They never contain credentials.
"""

import asyncio
import json
import logging
from datetime import datetime

import httpx

from .config import Settings
from .models import (
    ConsumptionResponse,
    GeoPoint,
    MeterDetailResponse,
    MeterListResponse,
    MeterSummary,
    NameplateEntry,
    Transformer,
    TransformerListResponse,
)

logger = logging.getLogger(__name__)

# The exact session cookie better-auth sets (verified in recon).
SESSION_COOKIE = "__Secure-better-auth.session_token"

# Portal timestamp format, verified: "23/06/2026 23:30" (DD/MM/YYYY HH:MM,
# 24h clock, no timezone).
PORTAL_DATETIME_FORMAT = "%d/%m/%Y %H:%M"


# --------------------------------------------------------------------------
# Upstream error types - each maps to an HTTP status our API returns.
# --------------------------------------------------------------------------


class PortalError(Exception):
    """Base class for upstream portal failures (HTTP 502 for our callers)."""

    status_code = 502

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message  # safe for responses; never contains credentials


class PortalNotFoundError(PortalError):
    """Portal said 404 (or SvelteKit's data route signalled 'not found')."""

    status_code = 404


class PortalAuthError(PortalError):
    """Portal rejected our login / could not refresh the session (502)."""


class PortalTimeoutError(PortalError):
    """Portal did not answer in time (504)."""

    status_code = 504


class PortalProtocolError(PortalError):
    """Portal answered, but not with the shape we know how to read (502)."""


# --------------------------------------------------------------------------
# Part 1 - transport: login, session, retries, single-flight re-login
# --------------------------------------------------------------------------


class PortalClient:
    """Async adapter around one portal session.

    Async is used deliberately: the 'one re-login at a time' requirement maps
    directly onto an asyncio.Lock, and FastAPI runs async routes concurrently
    (see README design decisions).
    """

    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self._settings = settings
        self._origin = settings.urja_portal_base_url.rstrip("/")
        self._http = httpx.AsyncClient(
            base_url=settings.urja_portal_base_url,
            timeout=settings.urja_timeout_seconds,
            follow_redirects=False,  # a redirect to /login is a signal, not a page
            transport=transport,  # tests inject httpx.MockTransport here
        )
        self._login_lock = asyncio.Lock()

    async def aclose(self) -> None:
        await self._http.aclose()

    # -- session ----------------------------------------------------------

    def _session_token(self) -> str | None:
        return self._http.cookies.get(SESSION_COOKIE)

    async def _login(self) -> None:
        """POST the portal's login form exactly as a browser would."""
        try:
            resp = await self._http.post(
                "/login",
                data={
                    "email": self._settings.urja_user,
                    "password": self._settings.urja_password,
                },
                # SvelteKit's CSRF check rejects POSTs without a matching
                # Origin header (verified: 403 "Cross-site POST ... forbidden").
                headers={"Origin": self._origin},
                timeout=self._settings.urja_login_timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise PortalTimeoutError("portal login timed out") from exc
        except httpx.TransportError as exc:
            raise PortalError("portal unreachable during login") from exc

        if resp.status_code == 200 and self._session_token():
            logger.info("portal login succeeded")
            return
        # Deliberately vague: do not echo portal bodies or credentials.
        logger.warning("portal login rejected (status=%s)", resp.status_code)
        raise PortalAuthError("portal rejected the configured credentials")

    async def _relogin_once(self, failed_token: str | None) -> None:
        """Re-login after expiry, but only ONE task across all concurrent ones.

        Every caller that saw a dead session enters the lock in turn; the
        first one logs in, the rest see a token that differs from the one
        their request failed with and skip straight through.
        """
        async with self._login_lock:
            current = self._session_token()
            if current and current != failed_token:
                logger.info("session was refreshed by another request; skipping login")
                return
            await self._login()

    # -- request pipeline --------------------------------------------------

    async def get_json(self, path: str, params: dict | None = None):
        """GET a portal endpoint and return parsed JSON, with retries and
        one automatic re-login if the session has expired.

        Two independent budgets:
          * transient transport errors get `urja_max_retries` retries;
          * an expired session costs exactly ONE extra attempt (first detection
            + retry after re-login), never consuming the transport budget.
        """
        max_retries = self._settings.urja_max_retries
        retries_used = 0
        relogged_in = False
        last_error: httpx.TransportError | None = None
        timed_out = False

        while True:
            token_used = self._session_token()
            try:
                resp = await self._http.get(path, params=params)
            except httpx.TimeoutException as exc:
                last_error, timed_out = exc, True
                if retries_used >= max_retries:
                    break
                retries_used += 1
                await self._backoff(retries_used - 1)
                continue
            except httpx.TransportError as exc:
                last_error, timed_out = exc, False
                if retries_used >= max_retries:
                    break
                retries_used += 1
                await self._backoff(retries_used - 1)
                continue

            # Expired session, as the portal really signals it.
            if resp.status_code in (401, 302) and not relogged_in:
                relogged_in = True
                await self._relogin_once(token_used)
                continue  # one extra attempt with the refreshed session

            if resp.status_code in (401, 302):
                raise PortalAuthError("portal session could not be refreshed")
            if resp.status_code == 404:
                raise PortalNotFoundError(self._safe_404_message(resp))
            if resp.status_code >= 500:
                # No retry: a portal 5xx is a reportable failure, not noise.
                raise PortalError(f"portal returned HTTP {resp.status_code}")

            payload = self._parse_json(resp)

            # Third verified expiry signal: SvelteKit's data routes answer
            # HTTP 200 with {"type":"redirect","location":"/login"}.
            if self._is_login_redirect(payload):
                if not relogged_in:
                    relogged_in = True
                    await self._relogin_once(token_used)
                    continue
                raise PortalAuthError("portal session could not be refreshed")

            return payload

        if timed_out or isinstance(last_error, httpx.TimeoutException):
            raise PortalTimeoutError("portal did not respond in time") from last_error
        raise PortalError("portal unreachable (network error)") from last_error

    async def _backoff(self, attempt: int) -> None:
        # Short exponential backoff (0.25s, 0.5s, ...) - polite by design.
        await asyncio.sleep(0.25 * (2**attempt))

    @staticmethod
    def _parse_json(resp: httpx.Response):
        content_type = resp.headers.get("content-type", "")
        if "json" not in content_type:
            logger.warning("portal returned non-JSON response (content-type=%s)", content_type)
            raise PortalProtocolError("portal returned an unexpected response format")
        try:
            return resp.json()
        except json.JSONDecodeError as exc:
            raise PortalProtocolError("portal returned malformed JSON") from exc

    @staticmethod
    def _is_login_redirect(payload) -> bool:
        """SvelteKit data-route session signal (verified): HTTP 200 with a
        redirect descriptor pointing at /login."""
        return (
            isinstance(payload, dict)
            and payload.get("type") == "redirect"
            and str(payload.get("location", "")).startswith("/login")
        )

    @staticmethod
    def _safe_404_message(resp: httpx.Response) -> str:
        """Use the portal's own message when it is a known JSON error body;
        otherwise a generic string. Never echo raw HTML."""
        try:
            body = resp.json()
            if isinstance(body, dict) and isinstance(body.get("message"), str):
                return body["message"]
        except json.JSONDecodeError:
            pass
        return "resource not found on portal"
