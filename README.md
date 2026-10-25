# Urja Meter Ops → REST API

A small, read-only REST API that sits in front of Flock Energy's legacy web
portal **"Urja Meter Ops"** (`https://urja-ops.flockenergy.tech`), normalises
its data, and fails safely when the portal misbehaves.

The portal is a SvelteKit single-page app with no public API. This service
logs in with a portal operator account (from environment variables — never
hardcoded), calls the portal's own JSON endpoints, and exposes them as a clean,
documented API:

| Our endpoint | What it does | Portal call behind it |
|---|---|---|
| `GET /api/v1/meters` | list/search meters (`q`, `page`, 20/page) | `GET /portal/meters/search` |
| `GET /api/v1/meters/{id}` | nameplate, hierarchy, location | `GET /meters/{id}/__data.json` + `GET /portal/meters/{id}/geo` |
| `GET /api/v1/meters/{id}/consumption` | 30-min energy history (`from`, `to`) | `GET /portal/meters/{id}/energy` |
| `GET /api/v1/transformers` | distribution transformers (40 total) | `GET /portal/dts` |
| `GET /healthz` | liveness (never touches the portal) | — |
| `GET /docs`, `GET /openapi.json` | interactive docs / schema | — |

The portal protocol (auth flow, endpoints, quirks) is documented separately in
**[PROTOCOL.md](PROTOCOL.md)** — built entirely from verified observations.

---

## Project structure

```
app/
  main.py      routes only: parameters, HTTP status codes, error handlers
  client.py    portal adapter: login, cookie session, single-flight re-login,
               retries/timeouts, parsing + normalisation (pure functions)
  models.py    Pydantic response models + date-parameter parsing
  config.py    settings from environment variables (pydantic-settings)
tests/
  conftest.py          dummy env vars so tests run offline
  fixtures/*.json      REAL portal responses captured by scripts/capture_fixtures.py
  test_config.py       settings load, no secrets in repo
  test_models.py       response shapes, explicit nulls, warnings
  test_client_reauth.py  re-login logic against httpx.MockTransport
  test_parsing.py      parsing/normalisation on the real fixtures
  test_routes.py       status codes, validation, no-leak assertions
scripts/
  export_openapi.py      writes openapi.json from app.openapi()
  capture_fixtures.py    re-captures the test fixtures from the portal (read-only)
PROTOCOL.md   verified portal protocol
README.md     this file
REFLECTION.md interview reflection (headings only)
```

## Install / configure / run

Requires Python 3.10+ (developed on 3.14).

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt

copy .env.example .env          # then edit: set your portal password
# .env is gitignored; alternatively export env vars:
#   URJA_USER, URJA_PASSWORD, (optional) URJA_PORTAL_BASE_URL,
#   URJA_TIMEOUT_SECONDS, URJA_LOGIN_TIMEOUT_SECONDS, URJA_MAX_RETRIES

uvicorn app.main:app --reload
```

- Docs: <http://127.0.0.1:8000/docs>
- Schema: <http://127.0.0.1:8000/openapi.json>
- Export a static schema: `python scripts/export_openapi.py`

Run tests (fully offline — fixtures + mocked transport, no portal contact):

```bash
python -m pytest -q     # 51 tests
```

## Sample request + response

```bash
curl "http://127.0.0.1:8000/api/v1/meters/J100000/consumption?from=24/06/2026&to=24/06/2026"
```

```json
{
  "warnings": [],
  "data": [
    {"timestamp": "2026-06-24T00:00:00", "kwh": 48439.16, "kvah": 52314.29, "voltR": 229.0},
    {"timestamp": "2026-06-24T00:30:00", "kwh": 48439.58, "kvah": 52314.75, "voltR": 220.0}
  ],
  "timezone": null
}
```

What happened there, in order: our API accepted the date as `DD/MM/YYYY`
(we also accept `YYYY-MM-DD`), converted it to ISO, the portal only honours ISO
date params (verified — it silently ignores `DD/MM/YYYY`), and the readings
came back as strings like `"23/06/2026 23:30"` / `"48439.16"` which we
normalised to ISO timestamps and floats. `timezone` is an explicit `null`
because the portal provides none and we refuse to invent one.

Another example — an unknown meter never leaks anything:

```bash
curl -i "http://127.0.0.1:8000/api/v1/meters/NOPE999"
# HTTP/1.1 404  … {"detail":"Meter not found"}
```

## Assumptions

1. **Credentials** come from env vars / `.env`; the account is read-only and
   we only ever send GETs plus the login POST.
2. **Energy timestamps have no timezone** (portal gives none). We emit naive
   ISO 8601 and say `timezone: null` instead of guessing Asia/Kolkata.
3. **Date ambiguity**: we define `DD/MM/YYYY` as day-first (the portal's own
   format), so `03/04/2026` is 3 April. Callers wanting zero ambiguity should
   send ISO.
4. **`/meters/{id}/__data.json`** is a SvelteKit internal route. It is the
   only source of meter detail (no `/portal/meters/{id}` exists — verified),
   but it is not a published contract and may change if the portal is rebuilt.
5. Meter ids look like `J100000` (`[A-Za-z0-9_-]+`); anything else is rejected
   with 404 before it can reach a URL.

## Design decisions and trade-offs

- **Async (`httpx.AsyncClient` + `asyncio.Lock`), not sync.** The requirement
  "one re-login at a time under concurrent requests" is exactly a lock: waiters
  queue, the first logs in, the rest compare cookie tokens and skip. A test
  fires 10 parallel requests at a dead session and asserts **one** login.
  Trade-off: slightly more machinery than sync code; chosen because the
  concurrency story is the interesting part of this assignment.
- **Three expiry signals, one code path.** The portal signals a dead session
  three different ways (401 JSON, 302→`/login`, and HTTP 200 with a
  `{"type":"redirect","location":"/login"}` body — found only because we
  probed). All three funnel into "re-login once, retry once".
- **Retry only what is safe.** Transient transport errors/timeouts get a short
  exponential backoff (0.25 s, 0.5 s, … configurable). Portal `5xx` is *not*
  retried — it is reported as 502 immediately, because retrying a broken
  upstream just hides the problem.
- **Field names mirror the portal** (`meterId`, `pageSize`, camelCase) so any
  response field is traceable to PROTOCOL.md with zero translation. Thin and
  honest; the cost is non-idiomatic Python naming.
- **Anomalies are surfaced, never "fixed".** Every response can carry
  `warnings`: blank fields → explicit `null` + note, non-numeric readings →
  `null` + count, unparseable timestamps → row omitted **and counted** (a
  timestamp-less row cannot exist in a time series, but silently dropping it
  would be dishonest).
- **`page ≥ 1` is a 422 from us.** The portal silently treats `page=0` /
  `page=abc` as page 1 (verified); we refuse instead, so callers learn about
  their bug rather than receiving plausible-looking wrong data.
- **No cache, no DB, no queue.** The portal is the source of truth and the
  assignment is a thin wrapper; every answer reflects live portal state. The
  only "state" is the session cookie in memory (re-login on restart).
- **BeautifulSoup4 ended up unused**: the portal's data is JSON, so HTML
  scraping was never needed (it was on the probe shortlist, then dropped from
  `requirements.txt` when §3 of PROTOCOL.md showed JSON everywhere).

## Intentionally skipped

- **Bulk export** (`/portal/export`): needs an HMAC signing secret fetched
  from `/portal/keys` (UNVERIFIED, never exercised). Real scope, more moving
  parts, and a secret we chose not to touch.
- **Global hierarchy endpoint**: the portal has none — hierarchy is per-meter
  only (verified), so it lives inside `GET /meters/{id}`.
- **Wrong-password login probing, `/api/auth/sign-out`, rate-limit testing**:
  out of scope for a read-only recon (PROTOCOL.md §8).
- **Token refresh/rotation handling**: unverified behaviour; we re-login on
  any expiry signal instead of guessing.
- **Pagination beyond page/q**: the portal fixed `pageSize=20` and exposes no
  cursor/limit params.

## What I'd improve with more time

1. Contract tests that hit the real portal nightly (a handful of GETs) to catch
   portal drift, especially around the internal `__data.json` route.
2. A `Retry-After`-aware circuit breaker if the portal shows slow degradation.
3. OpenAPI examples per endpoint from the real fixtures.
4. Structured logging of `warnings` counts for observability.

## Links

- [PROTOCOL.md](PROTOCOL.md) — verified portal protocol (auth, endpoints, quirks)
- [openapi.json](openapi.json) — generated schema (`python scripts/export_openapi.py`)
- [REFLECTION.md](REFLECTION.md) — interview reflection notes
