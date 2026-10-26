# REFLECTION — Flock Energy Take-Home Submission

## 1. Assumptions I made

1. **Credentials and Security Boundary**:
   Assumed operator credentials (`operator@urja.local`) are strictly read-only and must never be hardcoded in application logic or checked into version control. All configuration is loaded from environment variables (`.env`). Our API acts as an automated gateway proxy and never modifies upstream portal state.
2. **Timestamps and Timezone Agnosticism**:
   Energy readings arrive from the legacy portal in `DD/MM/YYYY HH:MM` (24-hour clock) without any UTC offset or timezone designation. While the geographic location of the transformers and meters strongly indicates Indian Standard Time (`Asia/Kolkata`, UTC+5:30), assuming this in data models without explicit upstream confirmation would be dishonest. We emit naive ISO 8601 datetimes (`YYYY-MM-DDTHH:MM:SS`) with an explicit `timezone: null` property and document this contract clearly.
3. **Date Parameter Conventions**:
   Because the portal originates from an Indian utility adopting day-first conventions (`DD/MM/YYYY`), `03/04/2026` is parsed as April 3rd rather than March 4th. Our API accepts both ISO (`YYYY-MM-DD`) and day-first (`DD/MM/YYYY`) dates at the perimeter, but **always** normalizes to ISO when dispatching upstream, as the legacy portal silently ignores non-ISO parameters.
4. **SvelteKit Internal Route Stability**:
   We assumed that SvelteKit's `__data.json` route and client chunk structure remain relatively stable for this deployment. Although `__data.json` is a framework-internal artifact rather than a published public API, it is the sole endpoint in the portal that exposes full meter nameplate parameters and hierarchy breadcrumbs.
5. **Static/Historical Dataset**:
   Observed consumption time-series data terminates at the end of June 2026 across all meters, confirming that the legacy portal hosts a fixed operational audit dataset rather than live streaming telemetry.

---

## 2. What was the hardest part?

The most challenging aspect was reverse-engineering the portal's non-standard internal data exchange patterns without breaking the read-only operational mandate:

1. **Decoding SvelteKit Devalue Serialization**:
   The `/meters/{id}/__data.json` route does not return standard nested JSON. Instead, it returns a flattened `devalue` payload where dictionary values and list elements are integer indices pointing into a root object pool (`nodes[1].data`). Constructing a pure, recursive index-dereferencing parser (`_devalue_instantiate`) that safely reconstructs arbitrary nested objects without unbounded recursion or depth overflows required careful trace analysis against real captured fixtures.
2. **Tri-State Session Expiry & Single-Flight Re-Authentication**:
   The portal indicates session expiry in three completely different ways depending on which route is called:
   - An HTTP 401 JSON body on `/portal/*` endpoints;
   - An HTTP 302 redirect to `/login` on page HTML routes;
   - An HTTP 200 with `{"type":"redirect","location":"/login"}` on `__data.json` data routes.
   Unifying all three into a resilient single-flight re-authentication pipeline using `asyncio.Lock`—where the first coroutine refreshes the cookie jar while concurrent waiters queue and skip redundant logins by comparing token signatures—was the most intricate concurrency puzzle in the project.
3. **Uncovering the HMAC-SHA256 Bulk Export Mechanism**:
   Discovering the bulk export endpoint required analyzing minified Vite JavaScript bundles (`nodes/4.2Bgc2kUI.js`). Unraveling the cryptographic signing protocol (`GET /portal/keys` → secret → `HMAC-SHA256("GET\n/portal/export\npage=1\n{timestamp}")` → headers `x-timestamp` + `x-signature`) allowed us to unlock the full 403-meter dataset in a single network round-trip.

---

## 3. What would I improve with another day?

1. **Persistent Distributed Cache (Redis / SQLite)**:
   The current cache for the network hierarchy and query index lives in process memory with a configurable TTL (default 300s). In a multi-worker production environment (e.g., Gunicorn/Uvicorn with 4+ workers), each worker maintains its own independent cache. Replacing in-memory caching with Redis or an embedded SQLite/DuckDB cache would provide cross-worker sharing, persistence across restarts, and atomic cache locking.
2. **Automated Upstream Contract & Drift Monitoring**:
   Because our adapter relies on internal portal routes (`__data.json` and HMAC keys), upstream frontend redeployments could silently alter chunk names or devalue formats. I would implement a daily synthetic canary test suite that executes lightweight non-destructive probes against the live portal to alert the team immediately if the legacy schema drifts.
3. **Circuit Breakers & Adaptive Rate Limiting**:
   If the upstream portal experiences intermittent database lockups or latency degradation, client requests currently retry with short exponential backoffs. Adding an upstream circuit breaker pattern (using `tenacity` or a token bucket) would fail fast and protect the legacy utility server from cascading stampedes.
4. **Streaming SSE / WebSockets for Live Telemetry**:
   Expose Server-Sent Events (`/api/v1/meters/{id}/stream`) so frontend dashboards and downstream SCADA services receive push notifications on meter status alerts or load fluctuations without polling.

---

## 4. A mistake I made

During early inspection of the consumption endpoint (`/portal/meters/{id}/energy`), I noticed the portal UI displayed all dates as `DD/MM/YYYY` and formatted response timestamps as `"24/06/2026 00:00"`. Naturally, I assumed passing `?from=24/06/2026&to=24/06/2026` would filter the query to a single day.

When I ran the request, the portal returned 337 rows. I initially thought the meter simply had extensive historical readings for that day. It was only when I queried a completely different date range (`01/01/2026`) and observed the exact same 337 rows that I realized the portal backend was silently ignoring the `DD/MM/YYYY` parameters and defaulting to its 7-day window.

The mistake was trusting the UI's display format as an API contract. Digging into the network tab confirmed the portal backend strictly required ISO `YYYY-MM-DD`. This reinforced a core principle of this project: **Never assume legacy API conventions mirror UI display formats.** Our wrapper now accepts both formats from callers for ergonomics, but always normalizes to strict ISO before forwarding upstream.

---

## 5. What would I criticise in my own submission?

1. **Coupling to Unofficial SvelteKit Endpoints**:
   The cleanest architecture for a wrapper is to sit exclusively on top of published REST contracts. In our solution, `GET /meters/{id}` depends on SvelteKit's `__data.json` route, and the bulk query layer depends on `/portal/export`. If the utility upgrades their SvelteKit framework or changes build hashing, those routes could vanish without warning. We flagged this as the primary structural risk in `README.md`.
2. **Linear Memory Scaling for the Query Layer**:
   The local query and proximity index loads all 403 meters into memory (~400 KB) and executes in-memory filtering and Haversine distance calculations. While this achieves sub-millisecond response times (<1ms) and zero external database dependencies for 403 meters, it does not scale to real-world utility networks managing 1,000,000+ smart meters. At that scale:
   - Memory footprint would exceed hundreds of megabytes;
   - Sequential $O(N)$ Haversine scans would cause CPU throttling;
   - A dedicated spatial datastore (e.g. PostgreSQL with PostGIS or an R-Tree index) would be mandatory.
3. **Single Shared Session Architecture**:
   All downstream API requests funnel through a single authenticated session token. If the utility portal introduces per-user request throttling or concurrency limits on operator accounts, high concurrent downstream load could trigger upstream rate limits or session invalidation across all callers simultaneously.
