"""Offline, realistic stand-in for PortalClient — used by Playwright E2E tests
and by scripts/capture_screenshots.py.

Every response is derived from tests/fixtures/*.json (real captured portal
payloads, see scripts/capture_fixtures.py), so the dashboard under test shows
TRUE data — 403 real meters, real hierarchy, real energy curve for J100000 —
without any network access or credentials.
"""

from __future__ import annotations

import json
import pathlib

from app.client import (
    build_network_hierarchy,
    find_nearby_from_export,
    get_stats_from_export,
    parse_energy,
    parse_geo,
    parse_meter_detail,
    parse_meter_list,
    parse_transformers,
    query_meters_from_export,
)
from app.client import PortalNotFoundError
from app.models import (
    ConsumptionResponse,
    GeoPoint,
    MeterDetailResponse,
    MeterListResponse,
    NameplateEntry,
    Transformer,
    TransformerListResponse,
)

FIXTURES = pathlib.Path(__file__).resolve().parents[1] / "tests" / "fixtures"


def _load(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _fmt(node) -> str | None:
    return f"{node['name']} ({node['code']})" if node else None


class E2EFakePortal:
    """Same async interface as PortalClient; backs everything with fixtures."""

    def __init__(self):
        export = _load("portal_export.json")
        self.export_rows = export["data"]
        self.rows_by_id = {
            r["meterId"]: r for r in self.export_rows if isinstance(r, dict) and r.get("meterId")
        }
        self._tree = build_network_hierarchy(self.export_rows)

    # -- meters ----------------------------------------------------------

    async def list_meters(self, q: str = "", page: int = 1) -> MeterListResponse:
        resp = parse_meter_list(_load("meters_search_page1.json"))
        if page == 1:
            return resp
        return MeterListResponse(data=[], total=resp.total, page=page, pageSize=resp.pageSize)

    async def get_meter(self, meter_id: str) -> MeterDetailResponse:
        if meter_id == "J100000":
            resp = parse_meter_detail(_load("detail_dataraw_j100000.json"), "J100000")
            geo, geo_warnings = parse_geo(_load("geo_j100000.json"))
            return MeterDetailResponse(
                meterId=resp.meterId,
                nameplate=resp.nameplate,
                hierarchy=resp.hierarchy,
                location=geo,
                warnings=[*resp.warnings, *geo_warnings],
            )

        # Any other meter: rebuild the portal's detail view from the real
        # captured export row (same fields the detail page renders).
        row = self.rows_by_id.get(meter_id)
        if row is None:
            raise PortalNotFoundError("Meter not found")

        h = row.get("hierarchy") or {}
        nameplate = [
            NameplateEntry(parameterName="Meter ID", parameterValue=row.get("meterId")),
            NameplateEntry(parameterName="Serial No", parameterValue=row.get("serialNo")),
            NameplateEntry(parameterName="Make", parameterValue=row.get("make")),
            NameplateEntry(
                parameterName="Phase",
                parameterValue=str(row["phaseType"]) if row.get("phaseType") else None,
            ),
            NameplateEntry(parameterName="Install Status", parameterValue=row.get("installStatus")),
            NameplateEntry(parameterName="Install Type", parameterValue=row.get("installType")),
            NameplateEntry(parameterName="Build", parameterValue=row.get("build")),
        ]
        hierarchy = {
            "Zone": _fmt(h.get("zone")),
            "Circle": _fmt(h.get("circle")),
            "Division": _fmt(h.get("division")),
            "Sub Division": _fmt(h.get("subdivision")),
            "Sub Station": _fmt(h.get("substation")),
            "Feeder": _fmt(h.get("feeder")),
            "DT": _fmt(h.get("dt")),
        }
        g = row.get("geo") or {}
        location = GeoPoint(latitude=g.get("lat"), longitude=g.get("lng")) if g else None
        return MeterDetailResponse(
            meterId=meter_id, nameplate=nameplate, hierarchy=hierarchy, location=location
        )

    async def get_consumption(self, meter_id, from_date=None, to_date=None) -> ConsumptionResponse:
        if meter_id == "J100000":
            return parse_energy(_load("energy_one_day.json"))
        # Offline honesty: fixtures captured one day of one meter only.
        return ConsumptionResponse(
            data=[],
            warnings=[f"offline fixtures: only J100000 has captured energy data; no readings returned for {meter_id}"],
        )

    async def query_meters(self, q="", make=None, phase=None, status=None, dt=None,
                           page=1, page_size=20):
        return query_meters_from_export(
            self.export_rows, q=q, make=make, phase=phase, status=status,
            dt=dt, page=page, page_size=page_size,
        )

    async def find_nearby_meters(self, lat, lon, radius_km=5.0, limit=50):
        return find_nearby_from_export(
            self.export_rows, origin_lat=lat, origin_lon=lon,
            radius_km=radius_km, limit=limit,
        )

    # -- transformers ------------------------------------------------------

    async def list_transformers(self, page: int = 1) -> TransformerListResponse:
        # The captured dts fixture holds page 1 only (20 of 40). Page 2 is
        # reconstructed from the same real export data (hierarchy tree), so all
        # 40 DTs shown are genuine portal assets; capacity is null where the
        # capture did not include it.
        resp = parse_transformers(_load("dts_page1.json"))
        if page == 1:
            return resp
        capacity_by_code = {t.code: t.capacityKva for t in resp.data}
        seen = set(capacity_by_code)
        extra: list[Transformer] = []
        for z in self._tree.zones:
            for c in z.circles:
                for d in c.divisions:
                    for sd in d.subdivisions:
                        for ss in sd.substations:
                            for f in ss.feeders:
                                for dt in f.transformers:
                                    if dt.code not in seen:
                                        extra.append(Transformer(
                                            code=dt.code,
                                            name=dt.name,
                                            feederCode=f.code,
                                            capacityKva=capacity_by_code.get(dt.code),
                                        ))
        return TransformerListResponse(data=extra, total=resp.total, page=page, pageSize=resp.pageSize)

    # -- stats / hierarchy -------------------------------------------------

    async def get_hierarchy(self, force_refresh=False):
        return self._tree

    async def get_network_stats(self):
        return get_stats_from_export(self.export_rows)
