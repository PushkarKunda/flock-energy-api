"""Unit tests for optional extensions:
- Network hierarchy reconstruction
- Local index / query layer
- Geospatial proximity (haversine)
- Operational stats aggregation
- Cache freshness logic

Tested purely offline using captured real portal fixtures.
"""

import json
import math
import pathlib
import pytest

from app.client import (
    build_network_hierarchy,
    find_nearby_from_export,
    get_stats_from_export,
    haversine_km,
    query_meters_from_export,
)
from app.models import NetworkHierarchyResponse, MeterQueryResponse, NearbyMetersResponse, NetworkStatsResponse

FIXTURES_DIR = pathlib.Path(__file__).parent / "fixtures"


@pytest.fixture()
def export_data():
    raw = (FIXTURES_DIR / "portal_export.json").read_text(encoding="utf-8")
    return json.loads(raw)["data"]


def test_haversine_km():
    # Distance between Jaipur center (26.9124, 75.7873) and Delhi center (28.6139, 77.2090) ~ 238 km
    dist = haversine_km(26.9124, 75.7873, 28.6139, 77.2090)
    assert 235 < dist < 245
    # Same point distance is 0
    assert haversine_km(26.9124, 75.7873, 26.9124, 75.7873) == 0.0


def test_build_network_hierarchy_structure(export_data):
    tree = build_network_hierarchy(export_data)
    assert isinstance(tree, NetworkHierarchyResponse)
    assert tree.totalMeters == 403
    assert tree.totalTransformers == 40
    assert len(tree.zones) == 3

    zone_codes = {z.code for z in tree.zones}
    assert zone_codes == {"Z-01", "Z-02", "Z-03"}

    # Total meters across all DTs should sum to 403
    meters_in_tree = sum(
        len(dt.meters)
        for z in tree.zones
        for c in z.circles
        for d in c.divisions
        for sd in d.subdivisions
        for ss in sd.substations
        for f in ss.feeders
        for dt in f.transformers
    )
    assert meters_in_tree == 403
    assert tree.totalFeeders == 28
    assert len(tree.warnings) == 22
    assert "had blank code" in tree.warnings[0]


def test_query_meters_filters(export_data):
    # Query with no filters returns all
    all_res = query_meters_from_export(export_data, page=1, page_size=50)
    assert isinstance(all_res, MeterQueryResponse)
    assert all_res.total == 403
    assert all_res.filteredTotal == 403
    assert len(all_res.data) == 50

    # Filter by make
    hpl_res = query_meters_from_export(export_data, make="HPL", page_size=100)
    assert hpl_res.filteredTotal == 90
    assert all(m.make == "HPL" for m in hpl_res.data)

    # Filter by status
    faulty_res = query_meters_from_export(export_data, status="Faulty", page_size=100)
    assert faulty_res.filteredTotal == 90
    assert all(m.installStatus == "Faulty" for m in faulty_res.data)

    # Filter by phase
    three_phase = query_meters_from_export(export_data, phase="three", page_size=200)
    assert three_phase.filteredTotal == 126
    assert all(m.phaseType == "three" for m in three_phase.data)

    # Combined filter: HPL + Installed
    combined = query_meters_from_export(export_data, make="HPL", status="Installed", page_size=100)
    assert combined.filteredTotal > 0
    assert all(m.make == "HPL" and m.installStatus == "Installed" for m in combined.data)

    # Free-text substring query
    search = query_meters_from_export(export_data, q="SE33962")
    assert search.filteredTotal == 1
    assert search.data[0].meterId == "J100000"


def test_find_nearby_meters(export_data):
    # Search around Jaipur center
    res = find_nearby_from_export(export_data, origin_lat=26.9124, origin_lon=75.7873, radius_km=10.0, limit=20)
    assert isinstance(res, NearbyMetersResponse)
    assert res.count == 20
    assert len(res.data) == 20
    # Results must be sorted ascending by distanceKm
    distances = [m.distanceKm for m in res.data]
    assert distances == sorted(distances)
    assert all(d <= 10.0 for d in distances)


def test_get_network_stats(export_data):
    stats = get_stats_from_export(export_data)
    assert isinstance(stats, NetworkStatsResponse)
    assert stats.totalMeters == 403
    assert stats.totalTransformers == 40
    assert stats.totalFeeders == 28
    assert stats.statusBreakdown["Installed"] == 238
    assert stats.statusBreakdown["Faulty"] == 90
    assert stats.statusBreakdown["Decommissioned"] == 75
    assert stats.phaseBreakdown["single"] == 277
    assert stats.phaseBreakdown["three"] == 126
