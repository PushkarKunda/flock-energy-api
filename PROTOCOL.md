# PROTOCOL.md — Urja Meter Ops portal, as verified

Everything below was observed with read-only requests (GET + one login POST)
on **2026-10-25** against `https://urja-ops.flockenergy.tech`, or read directly
from the portal's own JavaScript bundles (marked *UNVERIFIED*). Nothing here is
copied from "how portals usually work".

**Legend**

- **VERIFIED** — observed live, exact status/headers/body recorded below.
- **UNVERIFIED** — read from the portal's own JS source, not exercised.
- **NOT EXERCISED** — deliberately not touched (see §8).

---

## 1. Overview

| Property | Value |
|---|---|
| Base URL | `https://urja-ops.flockenergy.tech` |
| Frontend | SvelteKit (server-rendered HTML shell + client JS) |
| Session library | **better-auth** (cookie name reveals it) |
| Data format | JSON for everything we consume; no HTML scraping needed |
| Rate limiting | None observed (no `Retry-After`, no 429 in any probe) |

The portal's pages (`/meters`, `/meters/{id}`, `/transformers`) are only HTML
shells. The real data comes from JSON endpoints under `/portal/*` plus
SvelteKit's internal data route — both discovered by reading the portal's own
script chunks, not by guessing URLs.

## 2. Authentication

### 2.1 Login (VERIFIED)

```
GET  /            -> 302 Location: /login
GET  /login       -> 200 text/html  (Svelte form, no data embedded)
```

Login form (parsed from the HTML):

| Property | Value |
|---|---|
| Method / URL | `POST /login` (form `action=""`, posts back to the page) |
| Content-Type | `application/x-www-form-urlencoded` |
| Fields | `email`, `password` |
| CSRF token | **None exists** — no hidden input, no meta tag, no cookie |

**CSRF quirk (VERIFIED):** SvelteKit rejects the POST without a matching
`Origin` header:

```
HTTP/1.1 403
Cross-site POST form submissions are forbidden
```

With `Origin: https://urja-ops.flockenergy.tech`:

```
HTTP/1.1 200
Content-Type: application/json
Set-Cookie: __Secure-better-auth.session_token=…; Max-Age=3600; Path=/;
            HttpOnly; Secure; SameSite=Lax

{"type":"redirect","status":303,"location":"/meters"}
```

Success is therefore **not** an HTTP redirect: it is `200` + a JSON redirect
descriptor + the session cookie.

**Failure with wrong password: NOT EXERCISED** (we never test credentials
beyond the one real login). Our client treats *"200 but no session cookie"* as
a rejected login, which is the only signal the contract needs.

### 2.2 Session

| Property | Value |
|---|---|
| Cookie | `__Secure-better-auth.session_token` |
| Lifetime | `Max-Age=3600` → **1 hour** |
| Flags | `HttpOnly`, `Secure`, `SameSite=Lax`, `Path=/` |
| Refresh/rotation on activity | **UNVERIFIED** — none observed during short probes; our client re-logins on any expiry signal instead of assuming refresh |

Session lives in our process's cookie jar only; a restart re-logins lazily.

### 2.3 Expiry signals — three distinct behaviours (all VERIFIED)

An expired, missing, or **garbage** session token behaves identically:

| Route kind | Response |
|---|---|
| `/portal/*` JSON | `401` `{"error":"unauthorized","message":"A valid session is required."}` |
| HTML routes (`/meters`, …) | `302` `Location: /login` |
| SvelteKit data routes (`/meters/{id}/__data.json`) | **`200`** `{"type":"redirect","location":"/login"}` |

The third one is easy to miss: HTTP 200 with a redirect *body*. Our client
treats all three as "session dead → re-login once → retry once".

## 3. Data endpoints (all `application/json`)

### 3.1 `GET /portal/meters/search` (VERIFIED)

| Param | Behaviour |
|---|---|
| `q` | Free text; **matches meter number AND serial** (verified with `q=SE33962` and `q=J100042`, each returning exactly 1 row) |
| `page` | 1-based. `page=0` and `page=abc` **silently return page 1**; an out-of-range page (`999`) returns `"data":[]` with the true `"total"` |
| Page size | Fixed at **20**; no other paging params referenced in portal JS |

```json
{
  "data": [
    {"meterId":"J100000","serialNo":"SE33962","make":"HPL",
     "phaseType":"single","installStatus":"Decommissioned","dtCode":"DT-001"}
  ],
  "total": 403, "page": 1, "pageSize": 20
}
```

Observed value domains: `phaseType` ∈ {`single`, `three`},
`installStatus` ∈ {`Installed`, `Faulty`, `Decommissioned`},
`meterId` like `J100000`, `serialNo` like `SE33962`, `dtCode` like `DT-001`.
403 meters total.

### 3.2 `GET /portal/dts` (VERIFIED)

Same envelope (`data/total/page/pageSize`, `pageSize` 20, `total` 40):

```json
{"data":[{"code":"DT-001","name":"Malviya Nagar DT 1",
          "feederCode":"F-001","capacityKva":100}],
 "total":40,"page":1,"pageSize":20}
```

`capacityKva` is a real JSON number (no conversion needed).

### 3.3 `GET /portal/meters/{id}/energy` (VERIFIED)

| Param | Behaviour |
|---|---|
| `from`, `to` | **ISO `YYYY-MM-DD` only**, inclusive of the whole `to` day. `from=2026-06-24&to=2026-06-25` → 96 rows (2 × 48) |
| `from=24/06/2026` style | **Silently ignored** — returns the full default window (VERIFIED: identical 337 rows with and without DD/MM/YYYY params) |
| none | Default window: **7 days** (337 rows: `23/06/2026 23:30` → `30/06/2026 23:30`), **30-minute cadence** |

```json
{"data":[{"timestamp":"23/06/2026 23:30","kwh":"48438.74",
          "kvah":"52313.84","voltR":"226"}]}
```

Quirks:

- `timestamp` is **`DD/MM/YYYY HH:MM`**, 24h clock.
- **Every value is a string** (`kwh`, `kvah`, `voltR`).
- **No timezone anywhere.** (Hierarchies are Jaipur-based, so Asia/Kolkata is
  plausible — but that is an *assumption*, so our API reports `timezone: null`.)
- Only a `data` key at top level — no total/page metadata.
- Unknown meter → `404 {"error":"not_found","message":"Meter not found"}`.
- The dataset looks **static**: on 2026-10-25 the window was still June 2026.

### 3.4 `GET /portal/meters/{id}/geo` (VERIFIED)

```json
{"data":{"latitude":"26.938961002479868","longitude":"75.83095696146852"}}
```

Lat/long are **strings** → our API converts to numbers. Unknown meter → same
404 JSON as above. (Only `J100000`'s geo was verified live; whether a known
meter can *lack* geo is UNVERIFIED — our client would surface that as
`location: null` + a warning.)

### 3.5 `GET /meters/{id}/__data.json` — meter detail (VERIFIED, but internal)

There is **no** `GET /portal/meters/{id}` (checked: 404 HTML). Meter detail
(nameplate + hierarchy) exists only in SvelteKit's server-side page data.

- **Success:** HTTP 200, a *devalue*-serialised tree (object values and array
  items are indices into one flat array; decoded by `_devalue_instantiate` in
  `app/client.py`), containing:

  ```json
  {
    "meterId": "J100000",
    "detail": {"data": [
      {"parameterName":"Meter ID","parameterValue":"J100000"},
      {"parameterName":"Serial No","parameterValue":"SE33962"},
      {"parameterName":"Make","parameterValue":"HPL"},
      {"parameterName":"Phase Type","parameterValue":"single"},
      {"parameterName":"Installation Status","parameterValue":"Decommissioned"},
      {"parameterName":"Installation Type","parameterValue":"Whole Current"}
    ]},
    "hierarchy": {
      "Meter ID":"J100000", "Installation Status":"Decommissioned",
      "Installation Type":"Whole Current",
      "Zone":"Jaipur Zone 1 (Z-01)", "Circle":"Circle 1 (C-01)",
      "Division":"Division 1 (D-01)", "Subdivision":"Subdivision 1 (SD-01)",
      "Sub Station":"Substation 1 (SS-01)", "Feeder":"Feeder 1 (F-001)",
      "DT":"Malviya Nagar DT 1 (DT-001)"
    }
  }
  ```

- **Unknown meter:** **HTTP 200** with an error node —
  `{"type":"error","error":{"message":"Meter not found"},"status":404}`.
  Status code alone is not enough; the body must be inspected.
- **No session:** HTTP 200 `{"type":"redirect","location":"/login"}` (§2.3).
- **Alternate nameplate shape `classData` (UNVERIFIED):** the portal's JS also
  handles `detail.classData` as a JSON string with an `installed_meter`
  object. Never seen in a live response; supported defensively with a warning.

⚠️ `__data.json` is a SvelteKit **internal** route: it works today but is not a
published API contract and may change if the portal is rebuilt. Flagged as the
main structural risk in README.

## 4. Hierarchy (VERIFIED)

There is **no dedicated GET /portal/hierarchy endpoint** in the portal's UI.
Hierarchy was originally seen per-meter in the detail payload (§3.5) as a flat breadcrumb:

`Zone → Circle → Division → Subdivision → Sub Station → Feeder → DT`
(e.g. `"Feeder": "Feeder 1 (F-001)"`).

Furthermore, in the full bulk export payload (§5), each meter carries a structured
nested hierarchy dictionary: `zone`, `circle`, `division`, `subdivision`, `substation`,
`feeder`, `dt` (each containing `name` and `code`).

**Data Anomalies Observed (VERIFIED):**
- In 8 meter records (e.g. `J100044`, `J100078`, `J100134`), `feeder.code` was empty
  string `""` while `feeder.name` was valid (e.g. `"Feeder 5"`).
- In 6 meter records, `circle.code` or `circle.name` was blank.
- In 3 meter records, `substation.code` was blank.
- Our API reconciles these against canonical name↔code mappings discovered across
  the clean records, surfaces a descriptive warning for every gap, and organizes
  all 403 meters into a coherent tree: 3 Zones → 6 Circles → 18 Substations → 28 Feeders → 40 DTs.

## 5. Bulk export (VERIFIED)

The Transformers page includes an "Export all meters" function discovered in
SvelteKit client chunk `nodes/4.2Bgc2kUI.js`. Exercised and verified live:

1. `GET /portal/keys` → HTTP 200 `{"data":{"signingSecret":"..."}}`
2. Message format for signing:
   `method + "\n" + path + "\n" + query + "\n" + unix_timestamp`
   (e.g. `"GET\n/portal/export\npage=1\n1792997541"`)
3. Signature: `HMAC-SHA256(key=signingSecret, msg=message).hexdigest()`
4. Request: `GET /portal/export?page=1`
   Headers: `x-timestamp: <unix_ts>`, `x-signature: <hex_signature>`
5. Response: HTTP 200 `{"data": [... 403 items ...], "total": 403}`

Each record delivers full meter metadata, decimal coordinates (`lat`, `lng`), and
structured network hierarchy in a single network round-trip. Our client uses this
with an in-memory TTL cache to power the Network Hierarchy Tree, Multi-attribute
Index Layer, and Geospatial Proximity Search (`/api/v1/meters/nearby`).

## 6. Other portal JS endpoints seen (not used)

- `POST /api/auth/sign-out` — never called (we stay logged in).
- Page routes: `/(portal)/meters`, `/(portal)/meters/[id]`, `/(portal)/transformers`.

## 7. Error summary consumed by our API

| Portal response | Our API mapping |
|---|---|
| `404` `{"error":"not_found","message":"Meter not found"}` | `404` + portal's message |
| `200` + `{"type":"error",…,"status":404}` (data route) | `404` + portal's message |
| `401` / `302 → /login` / `200 + login redirect` | re-login once, retry once; if still dead → `502` |
| `5xx` | `502` (never retried) |
| Transport failure / timeout after retries | `502` / `504` |
| Non-JSON or missing keys in a 200 body | `502` (protocol error) |

## 8. What we deliberately did NOT do

- No fuzzing or aggressive scanning; polite 1s backoffs during recon.
- Wrong-password login brute forcing: skipped (§2.1).
- `/api/auth/sign-out`: never called (§6).
- Unbounded load testing: verified under normal concurrency, avoiding DOS on utility infrastructure.
