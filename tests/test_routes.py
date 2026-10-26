"""Route tests: parameter validation, error mapping, and the shapes our API
guarantees. The portal is a stub here - no network, no real credentials."""

import pytest
from datetime import date

from fastapi.testclient import TestClient

from app.client import (
    PortalAuthError,
    PortalError,
    PortalNotFoundError,
    PortalProtocolError,
    PortalTimeoutError,
)
from app.main import app
from app.models import (
    ConsumptionResponse,
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


class StubPortal:
    """Stands in for PortalClient; records how routes call it."""

    def __init__(self):
        self.calls: list[tuple] = []
        self.fail_with: Exception | None = None

    def _maybe_fail(self):
        if self.fail_with is not None:
            raise self.fail_with

    async def list_meters(self, q: str = "", page: int = 1) -> MeterListResponse:
        self.calls.append(("list_meters", q, page))
        self._maybe_fail()
        return MeterListResponse(
            data=[MeterSummary(meterId="J100000", serialNo="SE33962")],
            total=403, page=page, pageSize=20,
        )

    async def get_meter(self, meter_id: str) -> MeterDetailResponse:
        self.calls.append(("get_meter", meter_id))
        self._maybe_fail()
        if meter_id == "NOPE999":
            raise PortalNotFoundError("Meter not found")
        return MeterDetailResponse(
            meterId=meter_id,
            nameplate=[NameplateEntry(parameterName="Meter ID", parameterValue=meter_id)],
            hierarchy={"Zone": "Jaipur Zone 1 (Z-01)"},
        )

    async def get_consumption(self, meter_id, from_date=None, to_date=None) -> ConsumptionResponse:
        self.calls.append(("get_consumption", meter_id, from_date, to_date))
        self._maybe_fail()
        return ConsumptionResponse(data=[])

    async def list_transformers(self, page: int = 1) -> TransformerListResponse:
        self.calls.append(("list_transformers", page))
        self._maybe_fail()
        return TransformerListResponse(
            data=[Transformer(code="DT-001", capacityKva=100)],
            total=40, page=page, pageSize=20,
        )

    async def query_meters(
        self, q="", make=None, phase=None, status=None, dt=None, page=1, page_size=20
    ) -> MeterQueryResponse:
        self.calls.append(("query_meters", q, make, phase, status, dt, page, page_size))
        self._maybe_fail()
        return MeterQueryResponse(
            total=403, filteredTotal=1, page=page, pageSize=page_size,
            data=[MeterSummary(meterId="J100000", serialNo="SE33962", make=make, phaseType=phase, installStatus=status, dtCode=dt)],
        )

    async def find_nearby_meters(self, lat, lon, radius_km=5.0, limit=50) -> NearbyMetersResponse:
        self.calls.append(("find_nearby_meters", lat, lon, radius_km, limit))
        self._maybe_fail()
        return NearbyMetersResponse(
            originLatitude=lat, originLongitude=lon, radiusKm=radius_km, count=1,
            data=[NearbyMeter(meterId="J100000", serialNo="SE33962", latitude=lat, longitude=lon, distanceKm=0.5)],
        )

    async def get_hierarchy(self, force_refresh=False) -> NetworkHierarchyResponse:
        self.calls.append(("get_hierarchy", force_refresh))
        self._maybe_fail()
        return NetworkHierarchyResponse(
            totalMeters=403, totalTransformers=40, totalFeeders=29,
            zones=[HierarchyZone(code="Z-01", name="Jaipur Zone 1", circles=[])],
        )

    async def get_network_stats(self) -> NetworkStatsResponse:
        self.calls.append(("get_network_stats",))
        self._maybe_fail()
        return NetworkStatsResponse(
            totalMeters=403, totalTransformers=40, totalFeeders=29,
            statusBreakdown={"Installed": 238, "Faulty": 90, "Decommissioned": 75},
            makeBreakdown={"HPL": 90}, phaseBreakdown={"single": 277},
        )


@pytest.fixture()
def client():
    # raise_server_exceptions=False: our own 500 handler must answer, not re-raise.
    with TestClient(app, raise_server_exceptions=False) as test_client:
        stub = StubPortal()
        test_client.app.state.portal = stub  # replace the real client for this test
        test_client.stub = stub
        yield test_client


# -- happy paths -----------------------------------------------------------


def test_healthz(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
    alias_resp = client.get("/health")
    assert alias_resp.status_code == 200
    assert alias_resp.json() == {"status": "ok"}


def test_list_meters_passes_query_params_through(client):
    resp = client.get("/api/v1/meters", params={"q": "SE33962", "page": 2})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 403
    assert body["pageSize"] == 20
    assert body["warnings"] == []
    assert client.stub.calls == [("list_meters", "SE33962", 2)]


def test_meter_detail_route(client):
    resp = client.get("/api/v1/meters/J100000")
    assert resp.status_code == 200
    body = resp.json()
    assert body["meterId"] == "J100000"
    assert body["hierarchy"]["Zone"] == "Jaipur Zone 1 (Z-01)"
    assert body["location"] is None  # stub did not set one -> explicit null


def test_consumption_accepts_both_date_formats(client):
    resp = client.get(
        "/api/v1/meters/J100000/consumption",
        params={"from": "24/06/2026", "to": "2026-06-25"},
    )
    assert resp.status_code == 200
    # Both parsed to real dates; the portal will receive ISO (see client.py).
    assert client.stub.calls == [
        ("get_consumption", "J100000", date(2026, 6, 24), date(2026, 6, 25))
    ]


def test_transformers_route(client):
    resp = client.get("/api/v1/transformers", params={"page": 1})
    assert resp.status_code == 200
    assert resp.json()["data"][0]["capacityKva"] == 100


# -- our own validation (422) ---------------------------------------------


def test_page_below_one_is_rejected_not_silently_fixed(client):
    # The portal itself would silently return page 1 - we refuse instead.
    assert client.get("/api/v1/meters", params={"page": 0}).status_code == 422
    assert client.get("/api/v1/transformers", params={"page": 0}).status_code == 422


def test_invalid_date_is_rejected_with_hint(client):
    resp = client.get(
        "/api/v1/meters/J1/consumption", params={"from": "June 24 2026"}
    )
    assert resp.status_code == 422
    assert "YYYY-MM-DD" in resp.json()["detail"]


def test_reversed_date_range_is_rejected(client):
    resp = client.get(
        "/api/v1/meters/J1/consumption",
        params={"from": "2026-06-25", "to": "2026-06-24"},
    )
    assert resp.status_code == 422
    assert "from" in resp.json()["detail"]


# -- portal failure mapping ------------------------------------------------


def test_unknown_meter_is_404_with_safe_detail(client):
    resp = client.get("/api/v1/meters/NOPE999")
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Meter not found"}
    # and the same for consumption on an unknown meter
    client.stub.fail_with = PortalNotFoundError("Meter not found")
    resp = client.get("/api/v1/meters/NOPE999/consumption")
    assert resp.status_code == 404


@pytest.mark.parametrize(
    "error,status",
    [
        (PortalError("portal returned HTTP 500"), 502),
        (PortalAuthError("portal session could not be refreshed"), 502),
        (PortalProtocolError("portal returned malformed JSON"), 502),
        (PortalTimeoutError("portal did not respond in time"), 504),
    ],
)
def test_portal_failures_map_to_502_504(client, error, status):
    client.stub.fail_with = error
    resp = client.get("/api/v1/meters")
    assert resp.status_code == status
    body = resp.json()
    assert set(body) == {"detail"}
    # No credentials, no HTML, no traceback in any failure body.
    assert "test-password" not in resp.text
    assert "Traceback" not in resp.text


def test_unexpected_exception_is_generic_500(client):
    client.stub.fail_with = ValueError("secret internal detail")
    resp = client.get("/api/v1/meters")
    assert resp.status_code == 500
    assert resp.json() == {"detail": "internal server error"}
    assert "secret internal detail" not in resp.text  # logged, not returned


# -- docs / schema ---------------------------------------------------------


def test_docs_and_openapi_are_served(client):
    assert client.get("/openapi.json").status_code == 200
    spec = client.get("/openapi.json").json()
    assert "/api/v1/meters" in spec["paths"]
    assert "/api/v1/meters/{meter_id}/consumption" in spec["paths"]
    assert "/api/v1/meters/query" in spec["paths"]
    assert "/api/v1/meters/nearby" in spec["paths"]
    assert "/api/v1/hierarchy" in spec["paths"]
    assert "/api/v1/stats" in spec["paths"]
    assert "/api/v1/transformers" in spec["paths"]
    assert "/healthz" in spec["paths"]
    assert client.get("/docs").status_code == 200


def test_dashboard_served(client):
    resp = client.get("/dashboard")
    assert resp.status_code == 200
    assert "Urja Meter Ops" in resp.text
    assert "<!DOCTYPE html>" in resp.text
    root_resp = client.get("/")
    assert root_resp.status_code == 200


def test_query_meters_route(client):
    resp = client.get("/api/v1/meters/query", params={"make": "HPL", "status": "Installed", "page": 1, "page_size": 20})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 403
    assert data["filteredTotal"] == 1
    assert client.stub.calls[-1] == ("query_meters", "", "HPL", None, "Installed", None, 1, 20)


def test_nearby_meters_route(client):
    resp = client.get("/api/v1/meters/nearby", params={"lat": 26.9124, "lon": 75.7873, "radius_km": 10.0})
    assert resp.status_code == 200
    data = resp.json()
    assert data["originLatitude"] == 26.9124
    assert data["radiusKm"] == 10.0
    assert len(data["data"]) == 1
    assert data["data"][0]["meterId"] == "J100000"


def test_hierarchy_route(client):
    resp = client.get("/api/v1/hierarchy")
    assert resp.status_code == 200
    data = resp.json()
    assert data["totalMeters"] == 403
    assert data["totalTransformers"] == 40
    assert len(data["zones"]) == 1
    assert data["zones"][0]["code"] == "Z-01"


def test_stats_route(client):
    resp = client.get("/api/v1/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["totalMeters"] == 403
    assert data["statusBreakdown"]["Installed"] == 238
