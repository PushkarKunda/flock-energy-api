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
import hashlib
import hmac
import json
import logging
import math
import re
import time
from datetime import date, datetime

import httpx

from .config import Settings
from .models import (
    ConsumptionResponse,
    EnergyReading,
    GeoPoint,
    HierarchyCircle,
    HierarchyDT,
    HierarchyDivision,
    HierarchyFeeder,
    HierarchyMeter,
    HierarchySubdivision,
    HierarchySubstation,
    HierarchyZone,
    MeterDetailResponse,
    MeterListResponse,
    MeterQueryResponse,
    MeterSummary,
    NameplateEntry,
    NearbyMeter,
    NearbyMetersResponse,
    NetworkHierarchyResponse,
    NetworkStatsResponse,
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
        self._cache: list[dict] | None = None
        self._cache_expires_at: float = 0.0
        self._cache_lock = asyncio.Lock()

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

    async def get_json(self, path: str, params: dict | None = None, headers: dict | None = None):
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
                resp = await self._http.get(path, params=params, headers=headers)
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

    # ------------------------------------------------------------------
    # Public data methods (one per portal capability we expose)
    # ------------------------------------------------------------------

    async def list_meters(self, q: str = "", page: int = 1) -> MeterListResponse:
        """Portal /portal/meters/search?q=...&page=... (20 rows per page)."""
        payload = await self.get_json("/portal/meters/search", {"q": q, "page": page})
        return parse_meter_list(payload)

    async def list_transformers(self, page: int = 1) -> TransformerListResponse:
        """Portal /portal/dts?page=... (20 rows per page)."""
        payload = await self.get_json("/portal/dts", {"page": page})
        return parse_transformers(payload)

    async def get_meter(self, meter_id: str) -> MeterDetailResponse:
        """Meter detail: nameplate + hierarchy from SvelteKit's data route,
        plus location from /geo - the same two sources the portal's own detail
        page uses (it fetches geo in parallel with the page data)."""
        _validate_meter_id(meter_id)

        async def fetch_geo():
            # A missing location is an anomaly of the RECORD (surface it),
            # while other portal failures remain hard errors (502/504).
            try:
                payload = await self.get_json(f"/portal/meters/{meter_id}/geo")
                point, geo_warnings = parse_geo(payload)
                return point, geo_warnings
            except PortalNotFoundError:
                return None, [f"meter {meter_id}: portal has no location record -> null"]

        (detail_payload, (location, geo_warnings)) = await asyncio.gather(
            self.get_json(f"/meters/{meter_id}/__data.json"),
            fetch_geo(),
        )
        detail = parse_meter_detail(detail_payload, meter_id)
        detail.location = location
        detail.warnings.extend(geo_warnings)
        return detail

    async def get_consumption(
        self,
        meter_id: str,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> ConsumptionResponse:
        """Portal /portal/meters/{id}/energy with optional ISO date window
        (verified: the portal ignores DD/MM/YYYY params, so we always forward
        ISO YYYY-MM-DD - see parse_api_date in models.py)."""
        _validate_meter_id(meter_id)
        params: dict[str, str] = {}
        if from_date is not None:
            params["from"] = from_date.isoformat()
        if to_date is not None:
            params["to"] = to_date.isoformat()
        payload = await self.get_json(
            f"/portal/meters/{meter_id}/energy", params or None
        )
        return parse_energy(payload)

    # -- extensions: bulk export, hierarchy, query layer, proximity, stats ---

    async def get_export(self) -> list[dict]:
        """Bulk export of all meters with full hierarchy & geo coordinates.

        Discovered in portal JS bundle (nodes/4.2Bgc2kUI.js) and verified live:
        1. GET /portal/keys -> signingSecret
        2. HMAC-SHA256(secret, "GET\\n/portal/export\\npage=1\\n{ts}")
        3. GET /portal/export?page=1 with headers x-timestamp + x-signature
        """
        keys_payload = await self.get_json("/portal/keys")
        if not isinstance(keys_payload, dict) or not isinstance(keys_payload.get("data"), dict):
            raise PortalProtocolError("portal keys response has no data object")
        secret = keys_payload["data"].get("signingSecret")
        if not secret or not isinstance(secret, str):
            raise PortalProtocolError("portal keys response has no signingSecret")

        ts = str(int(time.time()))
        method = "GET"
        path = "/portal/export"
        query = "page=1"
        msg = f"{method}\n{path}\n{query}\n{ts}".encode("utf-8")
        sig = hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()

        headers = {"x-timestamp": ts, "x-signature": sig}
        payload = await self.get_json("/portal/export", params={"page": 1}, headers=headers)
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise PortalProtocolError("portal export payload is missing data array")
        return payload["data"]

    async def get_cached_export(self, force_refresh: bool = False) -> list[dict]:
        """Fetch all meters via export, caching in memory for TTL seconds."""
        async with self._cache_lock:
            now = time.time()
            if not force_refresh and self._cache is not None and now < self._cache_expires_at:
                return self._cache
            data = await self.get_export()
            self._cache = data
            self._cache_expires_at = now + self._settings.urja_cache_ttl_seconds
            return data

    async def get_hierarchy(self, force_refresh: bool = False) -> NetworkHierarchyResponse:
        """Reconstruct network hierarchy tree: Zone -> Circle -> Division -> Subdivision -> Substation -> Feeder -> DT -> Meters."""
        export_data = await self.get_cached_export(force_refresh=force_refresh)
        return build_network_hierarchy(export_data)

    async def query_meters(
        self,
        q: str = "",
        make: str | None = None,
        phase: str | None = None,
        status: str | None = None,
        dt: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> MeterQueryResponse:
        """Local index/query layer across attributes that the portal cannot filter."""
        export_data = await self.get_cached_export()
        return query_meters_from_export(
            export_data, q=q, make=make, phase=phase, status=status, dt=dt, page=page, page_size=page_size
        )

    async def find_nearby_meters(
        self,
        lat: float,
        lon: float,
        radius_km: float = 5.0,
        limit: int = 50,
    ) -> NearbyMetersResponse:
        """Geospatial proximity search: find meters within radius_km of coordinates."""
        export_data = await self.get_cached_export()
        return find_nearby_from_export(
            export_data, origin_lat=lat, origin_lon=lon, radius_km=radius_km, limit=limit
        )

    async def get_network_stats(self) -> NetworkStatsResponse:
        """Aggregate counts for operational metrics and dashboard KPI cards."""
        export_data = await self.get_cached_export()
        return get_stats_from_export(export_data)


# --------------------------------------------------------------------------
# Part 2 - parsing & normalisation (pure functions, tested on saved fixtures)
#
# Rules applied here, per the assignment:
#   * trim whitespace on every string;
#   * numeric strings -> numbers;
#   * portal "DD/MM/YYYY HH:MM" -> naive datetime (rendered ISO 8601 by
#     Pydantic). The portal provides NO timezone - we do not invent one;
#   * blank/missing -> explicit null;
#   * messy records are NEVER silently dropped: anything skipped is counted in
#     `warnings` so the caller sees exactly what happened.
# --------------------------------------------------------------------------

# Meter ids look like "J100000" (verified). Anything else is not a resource
# we can ask the portal about, and must never reach an f-string URL unchecked.
METER_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]+")


def _validate_meter_id(meter_id: str) -> None:
    if not METER_ID_PATTERN.fullmatch(meter_id):
        raise PortalNotFoundError("Meter not found")


def _norm_str(value) -> str | None:
    """Trim a string; blank -> None. Non-strings become their str() form."""
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    stripped = value.strip()
    return stripped or None


def _to_float(value) -> tuple[float | None, str | None]:
    """(number, offending_value). Absent -> (None, None); unparsable ->
    (None, repr of what we got) so the caller can warn."""
    if value is None:
        return None, None
    if isinstance(value, bool):
        return None, str(value)
    if isinstance(value, (int, float)):
        return float(value), None
    if isinstance(value, str):
        try:
            return float(value.strip()), None
        except ValueError:
            return None, value
    return None, str(value)


def _to_int(value) -> tuple[int | None, str | None]:
    if value is None:
        return None, None
    if isinstance(value, bool):
        return None, str(value)
    if isinstance(value, int):
        return value, None
    if isinstance(value, float):
        return int(value), None
    if isinstance(value, str):
        try:
            return int(value.strip()), None
        except ValueError:
            return None, value
    return None, str(value)


def parse_meter_list(payload) -> MeterListResponse:
    """Portal search payload -> MeterListResponse (with anomaly warnings)."""
    if not isinstance(payload, dict):
        raise PortalProtocolError("portal meter list is not an object")
    for key in ("data", "total", "page", "pageSize"):
        if key not in payload:
            raise PortalProtocolError(f"portal meter list is missing '{key}'")
    rows = payload["data"]
    if not isinstance(rows, list):
        raise PortalProtocolError("portal meter list 'data' is not an array")

    warnings: list[str] = []
    meters: list[MeterSummary] = []
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            warnings.append(f"row {i}: not an object - omitted")
            continue
        meter_id = _norm_str(row.get("meterId"))
        if meter_id is None:
            warnings.append(f"row {i}: missing meterId - omitted")
            continue
        fields: dict[str, str | None] = {"meterId": meter_id}
        for field in ("serialNo", "make", "phaseType", "installStatus", "dtCode"):
            raw = row.get(field)
            fields[field] = _norm_str(raw)
            if raw is not None and fields[field] is None:
                warnings.append(f"meter {meter_id}: {field} was blank -> null")
        meters.append(MeterSummary(**fields))

    total, bad_total = _to_int(payload["total"])
    page, bad_page = _to_int(payload["page"])
    page_size, bad_page_size = _to_int(payload["pageSize"])
    if bad_total is not None or total is None:
        raise PortalProtocolError("portal meter list has an unusable 'total'")
    if bad_page is not None or page is None:
        raise PortalProtocolError("portal meter list has an unusable 'page'")
    if bad_page_size is not None or page_size is None:
        raise PortalProtocolError("portal meter list has an unusable 'pageSize'")

    return MeterListResponse(
        data=meters, total=total, page=page, pageSize=page_size, warnings=warnings
    )


def parse_transformers(payload) -> TransformerListResponse:
    """Portal /portal/dts payload -> TransformerListResponse."""
    if not isinstance(payload, dict):
        raise PortalProtocolError("portal transformer list is not an object")
    for key in ("data", "total", "page", "pageSize"):
        if key not in payload:
            raise PortalProtocolError(f"portal transformer list is missing '{key}'")
    rows = payload["data"]
    if not isinstance(rows, list):
        raise PortalProtocolError("portal transformer list 'data' is not an array")

    warnings: list[str] = []
    transformers: list[Transformer] = []
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            warnings.append(f"row {i}: not an object - omitted")
            continue
        code = _norm_str(row.get("code"))
        if code is None:
            warnings.append(f"row {i}: missing code - omitted")
            continue
        capacity, bad_capacity = _to_int(row.get("capacityKva"))
        if bad_capacity is not None:
            warnings.append(
                f"transformer {code}: capacityKva {bad_capacity!r} is not numeric -> null"
            )
        transformers.append(
            Transformer(
                code=code,
                name=_norm_str(row.get("name")),
                feederCode=_norm_str(row.get("feederCode")),
                capacityKva=capacity,
            )
        )

    total, bad_total = _to_int(payload["total"])
    page, bad_page = _to_int(payload["page"])
    page_size, bad_page_size = _to_int(payload["pageSize"])
    if bad_total is not None or total is None:
        raise PortalProtocolError("portal transformer list has an unusable 'total'")
    if bad_page is not None or page is None:
        raise PortalProtocolError("portal transformer list has an unusable 'page'")
    if bad_page_size is not None or page_size is None:
        raise PortalProtocolError("portal transformer list has an unusable 'pageSize'")

    return TransformerListResponse(
        data=transformers, total=total, page=page, pageSize=page_size, warnings=warnings
    )


def parse_geo(payload) -> tuple[GeoPoint | None, list[str]]:
    """Portal /geo payload -> (GeoPoint, warnings). Lat/long arrive as strings."""
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
        raise PortalProtocolError("portal location payload is not an object")
    raw = payload["data"]
    warnings: list[str] = []
    latitude, bad_lat = _to_float(raw.get("latitude"))
    longitude, bad_lon = _to_float(raw.get("longitude"))
    if bad_lat is not None:
        warnings.append(f"latitude {bad_lat!r} is not numeric -> null")
    if bad_lon is not None:
        warnings.append(f"longitude {bad_lon!r} is not numeric -> null")
    if latitude is None and longitude is None and bad_lat is None and bad_lon is None:
        # Portal answered with no coordinates at all (both absent).
        return None, ["portal returned an empty location -> null"]
    return GeoPoint(latitude=latitude, longitude=longitude), warnings


def parse_energy(payload) -> ConsumptionResponse:
    """Portal /energy payload -> ConsumptionResponse.

    Rows whose timestamp cannot be parsed are omitted BUT counted in
    warnings - a reading without a time is meaningless in a time series, and
    silently keeping it (or silently dropping it) would both be dishonest.
    """
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise PortalProtocolError("portal energy payload is not an array")

    warnings: list[str] = []
    readings: list[EnergyReading] = []
    bad_timestamps: list[str] = []
    bad_numbers: dict[str, int] = {}

    for row in payload["data"]:
        if not isinstance(row, dict):
            bad_timestamps.append("non-object row")
            continue
        raw_ts = _norm_str(row.get("timestamp"))
        try:
            timestamp = datetime.strptime(raw_ts or "", PORTAL_DATETIME_FORMAT)
        except ValueError:
            bad_timestamps.append(repr(raw_ts))
            continue

        values: dict[str, float | None] = {}
        for field in ("kwh", "kvah", "voltR"):
            number, bad = _to_float(row.get(field))
            if bad is not None:
                bad_numbers[field] = bad_numbers.get(field, 0) + 1
            values[field] = number

        readings.append(
            EnergyReading(timestamp=timestamp, kwh=values["kwh"],
                          kvah=values["kvah"], voltR=values["voltR"])
        )

    if bad_timestamps:
        warnings.append(
            f"{len(bad_timestamps)} energy row(s) omitted: unparseable timestamp "
            f"(e.g. {bad_timestamps[0]})"
        )
    for field, count in bad_numbers.items():
        warnings.append(f"{count} energy row(s): {field} was non-numeric -> null")

    return ConsumptionResponse(data=readings, timezone=None, warnings=warnings)


# -- SvelteKit devalue format (detail page data) --------------------------
#
# /meters/{id}/__data.json is NOT plain JSON: it is a devalue-serialised tree
# where object values and array items are INDICES into one flat array
# (verified against the real payload - see fixtures/detail_dataraw_j100000.json).


def _devalue_instantiate(values: list, item, depth: int = 0):
    if depth > 50:
        raise PortalProtocolError("portal detail payload nested too deeply")
    if isinstance(item, dict):
        out = {}
        for key, ref in item.items():
            if isinstance(ref, int) and not isinstance(ref, bool) and 0 <= ref < len(values):
                out[key] = _devalue_instantiate(values, values[ref], depth + 1)
            else:
                out[key] = ref  # literal (defensive; portal data uses indices)
        return out
    if isinstance(item, list):
        return [
            _devalue_instantiate(
                values, values[ref], depth + 1
            ) if isinstance(ref, int) and not isinstance(ref, bool) and 0 <= ref < len(values)
            else ref
            for ref in item
        ]
    return item


def parse_meter_detail(payload, meter_id: str) -> MeterDetailResponse:
    """SvelteKit __data.json payload -> MeterDetailResponse.

    Handles the verified error node (HTTP 200 + {"type":"error", status:404})
    and both nameplate shapes the portal's own JS knows about: `data` rows
    (observed live) and the `classData` JSON string (present in portal code,
    not observed in responses - see PROTOCOL.md).
    """
    if not isinstance(payload, dict) or not isinstance(payload.get("nodes"), list):
        raise PortalProtocolError("portal detail payload has no nodes array")
    nodes = payload["nodes"]

    for node in nodes:
        if isinstance(node, dict) and node.get("type") == "error":
            error = node.get("error")
            message = error.get("message") if isinstance(error, dict) else None
            raise PortalNotFoundError(
                message if isinstance(message, str) else "Meter not found"
            )

    root = None
    for node in nodes:
        if (
            isinstance(node, dict)
            and node.get("type") == "data"
            and isinstance(node.get("data"), list)
            and node["data"]  # skip empty nodes (e.g. the layout node)
        ):
            resolved = _devalue_instantiate(node["data"], node["data"][0])
            if isinstance(resolved, dict) and "detail" in resolved:
                root = resolved
                break
    if root is None:
        raise PortalProtocolError("portal detail payload has no meter node")

    warnings: list[str] = []
    found_id = _norm_str(root.get("meterId")) or meter_id

    # --- nameplate -------------------------------------------------------
    nameplate: list[NameplateEntry] = []
    detail = root.get("detail")
    if not isinstance(detail, dict):
        warnings.append("meter detail node missing -> nameplate empty")
    else:
        rows = detail.get("data")
        class_data = detail.get("classData")
        if isinstance(rows, list):
            for i, row in enumerate(rows):
                if not isinstance(row, dict):
                    warnings.append(f"nameplate row {i}: not an object -> omitted")
                    continue
                name = _norm_str(row.get("parameterName"))
                if name is None:
                    warnings.append(f"nameplate row {i}: no parameterName -> omitted")
                    continue
                raw_value = row.get("parameterValue")
                value = _norm_str(raw_value)
                if raw_value is not None and value is None:
                    warnings.append(f"nameplate '{name}': blank value -> null")
                nameplate.append(
                    NameplateEntry(parameterName=name, parameterValue=value)
                )
        elif isinstance(class_data, str):
            # Alternate shape seen in the portal's JS (unverified live):
            # classData is a JSON string holding an installed_meter object.
            try:
                parsed = json.loads(class_data)
                installed = parsed.get("installed_meter") if isinstance(parsed, dict) else None
                if isinstance(installed, dict):
                    for key, val in installed.items():
                        nameplate.append(
                            NameplateEntry(
                                parameterName=str(key),
                                parameterValue=None if val is None else str(val),
                            )
                        )
                    warnings.append(
                        "nameplate arrived as 'classData' JSON (alternate portal shape)"
                    )
                else:
                    warnings.append("classData had no installed_meter object -> nameplate empty")
            except json.JSONDecodeError:
                warnings.append("classData was not valid JSON -> nameplate empty")
        else:
            warnings.append("detail node has neither 'data' nor 'classData' -> nameplate empty")

    # --- hierarchy -------------------------------------------------------
    hierarchy: dict[str, str | None] = {}
    raw_hierarchy = root.get("hierarchy")
    if isinstance(raw_hierarchy, dict):
        for key, value in raw_hierarchy.items():
            name = str(key)
            if value is None:
                hierarchy[name] = None
            elif isinstance(value, str):
                trimmed = value.strip()
                hierarchy[name] = trimmed or None
                if value and not trimmed:
                    warnings.append(f"hierarchy '{name}': whitespace-only -> null")
            else:
                hierarchy[name] = str(value)
                warnings.append(
                    f"hierarchy '{name}': unexpected {type(value).__name__} -> stringified"
                )
    elif raw_hierarchy is None:
        warnings.append("hierarchy missing from portal detail -> empty")
    else:
        warnings.append("hierarchy was not an object -> empty")

    return MeterDetailResponse(
        meterId=found_id,
        nameplate=nameplate,
        hierarchy=hierarchy,
        warnings=warnings,
    )


# --------------------------------------------------------------------------
# Part 3 - Hierarchy, Query Layer & Geospatial (pure functions)
# --------------------------------------------------------------------------


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two decimal coordinates in kilometers."""
    r = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2.0) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return r * c


def build_network_hierarchy(export_data: list[dict]) -> NetworkHierarchyResponse:
    """Transform flat bulk export records into an organized distribution network tree:
    Zone -> Circle -> Division -> Subdivision -> Substation -> Feeder -> DT -> Meters.

    Reconciles messy portal records where names or codes were intermittently left blank.
    """
    warnings: list[str] = []
    zones: dict[str, dict] = {}
    total_transformers_set = set()
    total_feeders_set = set()

    # Pre-build canonical name <-> code dictionaries for levels that suffer portal data gaps
    name_to_code: dict[str, dict[str, str]] = {"feeder": {}, "circle": {}, "substation": {}}
    code_to_name: dict[str, dict[str, str]] = {"feeder": {}, "circle": {}, "substation": {}}
    for m in export_data:
        if isinstance(m, dict) and isinstance(m.get("hierarchy"), dict):
            h = m["hierarchy"]
            for lvl in ("feeder", "circle", "substation"):
                obj = h.get(lvl)
                if isinstance(obj, dict):
                    n = _norm_str(obj.get("name"))
                    c = _norm_str(obj.get("code"))
                    if n and c:
                        name_to_code[lvl][n] = c
                        code_to_name[lvl][c] = n

    def resolve_level(lvl: str, obj: dict | None, default_code: str, meter_id: str) -> tuple[str, str]:
        if not isinstance(obj, dict):
            warnings.append(f"meter {meter_id}: {lvl} missing object -> {default_code}")
            return default_code, default_code
        c = _norm_str(obj.get("code"))
        n = _norm_str(obj.get("name"))
        if not c and n and lvl in name_to_code and n in name_to_code[lvl]:
            c = name_to_code[lvl][n]
            warnings.append(f"meter {meter_id}: {lvl} '{n}' had blank code -> reconciled {c}")
        elif not n and c and lvl in code_to_name and c in code_to_name[lvl]:
            n = code_to_name[lvl][c]
            warnings.append(f"meter {meter_id}: {lvl} '{c}' had blank name -> reconciled {n}")
        elif not c and not n:
            warnings.append(f"meter {meter_id}: {lvl} missing code and name -> {default_code}")
        return c or default_code, n or c or default_code

    for idx, m in enumerate(export_data):
        if not isinstance(m, dict):
            warnings.append(f"export item {idx}: not a dict -> skipped")
            continue
        meter_id = _norm_str(m.get("meterId"))
        if not meter_id:
            warnings.append(f"export item {idx}: missing meterId -> skipped")
            continue

        h = m.get("hierarchy")
        if not isinstance(h, dict):
            warnings.append(f"meter {meter_id}: missing hierarchy object")
            continue

        z = h.get("zone") or {}
        c = h.get("circle") or {}
        d = h.get("division") or {}
        sd = h.get("subdivision") or {}
        ss = h.get("substation") or {}
        f = h.get("feeder") or {}
        dt = h.get("dt") or {}

        zc = _norm_str(z.get("code")) or "Z-UNKNOWN"
        zn = _norm_str(z.get("name")) or zc
        if zc not in zones:
            zones[zc] = {"code": zc, "name": zn, "circles": {}}

        cc, cn = resolve_level("circle", c, "C-UNKNOWN", meter_id)
        if cc not in zones[zc]["circles"]:
            zones[zc]["circles"][cc] = {"code": cc, "name": cn, "divisions": {}}

        dc = _norm_str(d.get("code")) or "D-UNKNOWN"
        dn = _norm_str(d.get("name")) or dc
        if dc not in zones[zc]["circles"][cc]["divisions"]:
            zones[zc]["circles"][cc]["divisions"][dc] = {"code": dc, "name": dn, "subdivisions": {}}

        sdc = _norm_str(sd.get("code")) or "SD-UNKNOWN"
        sdn = _norm_str(sd.get("name")) or sdc
        if sdc not in zones[zc]["circles"][cc]["divisions"][dc]["subdivisions"]:
            zones[zc]["circles"][cc]["divisions"][dc]["subdivisions"][sdc] = {
                "code": sdc,
                "name": sdn,
                "substations": {},
            }

        ssc, ssn = resolve_level("substation", ss, "SS-UNKNOWN", meter_id)
        if ssc not in zones[zc]["circles"][cc]["divisions"][dc]["subdivisions"][sdc]["substations"]:
            zones[zc]["circles"][cc]["divisions"][dc]["subdivisions"][sdc]["substations"][ssc] = {
                "code": ssc,
                "name": ssn,
                "feeders": {},
            }

        fc, fn = resolve_level("feeder", f, "F-UNKNOWN", meter_id)
        total_feeders_set.add(fc)
        if fc not in zones[zc]["circles"][cc]["divisions"][dc]["subdivisions"][sdc]["substations"][ssc]["feeders"]:
            zones[zc]["circles"][cc]["divisions"][dc]["subdivisions"][sdc]["substations"][ssc]["feeders"][fc] = {
                "code": fc,
                "name": fn,
                "transformers": {},
            }

        dtc = _norm_str(dt.get("code")) or "DT-UNKNOWN"
        dtn = _norm_str(dt.get("name")) or dtc
        total_transformers_set.add(dtc)
        feeder_entry = zones[zc]["circles"][cc]["divisions"][dc]["subdivisions"][sdc]["substations"][ssc]["feeders"][fc]
        if dtc not in feeder_entry["transformers"]:
            feeder_entry["transformers"][dtc] = {
                "code": dtc,
                "name": dtn,
                "capacityKva": None,
                "meters": [],
            }

        feeder_entry["transformers"][dtc]["meters"].append(
            HierarchyMeter(
                meterId=meter_id,
                serialNo=_norm_str(m.get("serialNo")),
                make=_norm_str(m.get("make")),
                phaseType=_norm_str(m.get("phaseType")),
                installStatus=_norm_str(m.get("installStatus")),
            )
        )

    # Convert nested dicts into Pydantic models
    zone_list: list[HierarchyZone] = []
    for z_dict in zones.values():
        circle_list: list[HierarchyCircle] = []
        for c_dict in z_dict["circles"].values():
            division_list: list[HierarchyDivision] = []
            for d_dict in c_dict["divisions"].values():
                subdiv_list: list[HierarchySubdivision] = []
                for sd_dict in d_dict["subdivisions"].values():
                    substation_list: list[HierarchySubstation] = []
                    for ss_dict in sd_dict["substations"].values():
                        feeder_list: list[HierarchyFeeder] = []
                        for f_dict in ss_dict["feeders"].values():
                            dt_list: list[HierarchyDT] = []
                            for dt_dict in f_dict["transformers"].values():
                                dt_list.append(
                                    HierarchyDT(
                                        code=dt_dict["code"],
                                        name=dt_dict["name"],
                                        capacityKva=dt_dict.get("capacityKva"),
                                        metersCount=len(dt_dict["meters"]),
                                        meters=dt_dict["meters"],
                                    )
                                )
                            feeder_list.append(
                                HierarchyFeeder(
                                    code=f_dict["code"],
                                    name=f_dict["name"],
                                    transformersCount=len(dt_list),
                                    transformers=dt_list,
                                )
                            )
                        substation_list.append(
                            HierarchySubstation(
                                code=ss_dict["code"],
                                name=ss_dict["name"],
                                feeders=feeder_list,
                            )
                        )
                    subdiv_list.append(
                        HierarchySubdivision(
                            code=sd_dict["code"],
                            name=sd_dict["name"],
                            substations=substation_list,
                        )
                    )
                division_list.append(
                    HierarchyDivision(
                        code=d_dict["code"],
                        name=d_dict["name"],
                        subdivisions=subdiv_list,
                    )
                )
            circle_list.append(
                HierarchyCircle(
                    code=c_dict["code"],
                    name=c_dict["name"],
                    divisions=division_list,
                )
            )
        zone_list.append(
            HierarchyZone(
                code=z_dict["code"],
                name=z_dict["name"],
                circles=circle_list,
            )
        )

    return NetworkHierarchyResponse(
        totalMeters=len(export_data),
        totalTransformers=len(total_transformers_set),
        totalFeeders=len(total_feeders_set),
        zones=zone_list,
        warnings=warnings,
    )


def query_meters_from_export(
    export_data: list[dict],
    q: str = "",
    make: str | None = None,
    phase: str | None = None,
    status: str | None = None,
    dt: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> MeterQueryResponse:
    """Filter meters across multiple attributes with pagination."""
    warnings: list[str] = []
    filtered: list[MeterSummary] = []
    q_lower = q.strip().lower()

    for idx, m in enumerate(export_data):
        if not isinstance(m, dict):
            warnings.append(f"row {idx}: not a dict -> skipped")
            continue
        mid = _norm_str(m.get("meterId"))
        if not mid:
            warnings.append(f"row {idx}: missing meterId -> skipped")
            continue

        serial = _norm_str(m.get("serialNo"))
        m_make = _norm_str(m.get("make"))
        m_phase = _norm_str(m.get("phaseType"))
        m_status = _norm_str(m.get("installStatus"))
        m_dt = _norm_str(m.get("dtCode"))

        if q_lower:
            mid_match = q_lower in mid.lower()
            serial_match = bool(serial and q_lower in serial.lower())
            if not (mid_match or serial_match):
                continue

        if make and (not m_make or m_make.lower() != make.strip().lower()):
            continue
        if phase and (not m_phase or m_phase.lower() != phase.strip().lower()):
            continue
        if status and (not m_status or m_status.lower() != status.strip().lower()):
            continue
        if dt and (not m_dt or m_dt.lower() != dt.strip().lower()):
            continue

        filtered.append(
            MeterSummary(
                meterId=mid,
                serialNo=serial,
                make=m_make,
                phaseType=m_phase,
                installStatus=m_status,
                dtCode=m_dt,
            )
        )

    filtered_total = len(filtered)
    start_idx = (page - 1) * page_size
    end_idx = start_idx + page_size
    sliced = filtered[start_idx:end_idx] if start_idx < filtered_total else []

    return MeterQueryResponse(
        total=len(export_data),
        filteredTotal=filtered_total,
        page=page,
        pageSize=page_size,
        data=sliced,
        warnings=warnings,
    )


def find_nearby_from_export(
    export_data: list[dict],
    origin_lat: float,
    origin_lon: float,
    radius_km: float = 5.0,
    limit: int = 50,
) -> NearbyMetersResponse:
    """Find meters within radius_km of coordinate, sorted by distance."""
    warnings: list[str] = []
    nearby: list[NearbyMeter] = []

    for idx, m in enumerate(export_data):
        if not isinstance(m, dict):
            continue
        mid = _norm_str(m.get("meterId"))
        if not mid:
            continue

        geo = m.get("geo")
        if not isinstance(geo, dict):
            warnings.append(f"meter {mid}: missing geo coordinates")
            continue

        lat_val = geo.get("lat") or geo.get("latitude")
        lon_val = geo.get("lng") or geo.get("longitude")
        lat, _ = _to_float(lat_val)
        lon, _ = _to_float(lon_val)

        if lat is None or lon is None:
            warnings.append(f"meter {mid}: invalid geo coordinates")
            continue

        dist = haversine_km(origin_lat, origin_lon, lat, lon)
        if dist <= radius_km:
            nearby.append(
                NearbyMeter(
                    meterId=mid,
                    serialNo=_norm_str(m.get("serialNo")),
                    make=_norm_str(m.get("make")),
                    phaseType=_norm_str(m.get("phaseType")),
                    installStatus=_norm_str(m.get("installStatus")),
                    dtCode=_norm_str(m.get("dtCode")),
                    latitude=lat,
                    longitude=lon,
                    distanceKm=round(dist, 3),
                )
            )

    nearby.sort(key=lambda x: x.distanceKm)
    sliced = nearby[:limit]

    return NearbyMetersResponse(
        originLatitude=origin_lat,
        originLongitude=origin_lon,
        radiusKm=radius_km,
        count=len(sliced),
        data=sliced,
        warnings=warnings,
    )


def get_stats_from_export(export_data: list[dict]) -> NetworkStatsResponse:
    """Compute aggregate counts for status, make, phase, transformers, feeders."""
    warnings: list[str] = []
    status_counts: dict[str, int] = {}
    make_counts: dict[str, int] = {}
    phase_counts: dict[str, int] = {}
    dt_set = set()
    feeder_set = set()

    feeder_name_to_code: dict[str, str] = {}
    for m in export_data:
        if isinstance(m, dict) and isinstance(m.get("hierarchy"), dict):
            f_obj = m["hierarchy"].get("feeder")
            if isinstance(f_obj, dict):
                n_str = _norm_str(f_obj.get("name"))
                c_str = _norm_str(f_obj.get("code"))
                if n_str and c_str:
                    feeder_name_to_code[n_str] = c_str

    for idx, m in enumerate(export_data):
        if not isinstance(m, dict):
            continue
        mid = _norm_str(m.get("meterId"))
        if not mid:
            continue

        status = _norm_str(m.get("installStatus")) or "Unknown"
        status_counts[status] = status_counts.get(status, 0) + 1

        make = _norm_str(m.get("make")) or "Unknown"
        make_counts[make] = make_counts.get(make, 0) + 1

        phase = _norm_str(m.get("phaseType")) or "Unknown"
        phase_counts[phase] = phase_counts.get(phase, 0) + 1

        dt = _norm_str(m.get("dtCode"))
        if dt:
            dt_set.add(dt)

        h = m.get("hierarchy")
        if isinstance(h, dict) and isinstance(h.get("feeder"), dict):
            f_code = _norm_str(h["feeder"].get("code"))
            f_name = _norm_str(h["feeder"].get("name"))
            if not f_code and f_name and f_name in feeder_name_to_code:
                f_code = feeder_name_to_code[f_name]
            if f_code:
                feeder_set.add(f_code)

    return NetworkStatsResponse(
        totalMeters=len(export_data),
        totalTransformers=len(dt_set),
        totalFeeders=len(feeder_set),
        statusBreakdown=status_counts,
        makeBreakdown=make_counts,
        phaseBreakdown=phase_counts,
        warnings=warnings,
    )
