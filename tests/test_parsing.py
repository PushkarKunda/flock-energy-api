"""Parsing / normalisation tests, driven by REAL portal payloads saved in
tests/fixtures/ (captured by scripts/capture_fixtures.py - no network here).

Synthetic edge-case inputs are marked clearly: they test OUR defensive
handling, not a claim that the portal sent such values.
"""

import json
import pathlib
from datetime import date, datetime

import pytest

from app.client import (
    PortalNotFoundError,
    PortalProtocolError,
    _validate_meter_id,
    parse_energy,
    parse_geo,
    parse_meter_detail,
    parse_meter_list,
    parse_transformers,
)
from app.models import parse_api_date

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def load(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


# -- GET /api/v1/meters ---------------------------------------------------


def test_meter_list_from_real_fixture():
    resp = parse_meter_list(load("meters_search_page1.json"))
    assert resp.total == 403
    assert resp.page == 1
    assert resp.pageSize == 20
    assert len(resp.data) == 20
    first = resp.data[0]
    assert first.meterId == "J100000"
    assert first.serialNo == "SE33962"
    assert first.installStatus == "Decommissioned"
    assert resp.warnings == []  # clean portal payload -> no noise


def test_meter_list_rejects_missing_paging_metadata():
    with pytest.raises(PortalProtocolError):
        parse_meter_list({"data": [], "total": 403})  # synthetic: missing keys


def test_meter_list_omits_idless_row_with_warning():
    payload = {
        "data": [{"serialNo": "X1"}, {"meterId": "J1", "serialNo": " X2 "}],
        "total": 2, "page": 1, "pageSize": 20,
    }  # synthetic edge case
    resp = parse_meter_list(payload)
    assert len(resp.data) == 1
    assert resp.data[0].serialNo == "X2"  # whitespace trimmed
    assert any("missing meterId" in w for w in resp.warnings)


def test_meter_list_blank_field_becomes_null_with_warning():
    payload = {
        "data": [{"meterId": "J1", "serialNo": "   "}],
        "total": 1, "page": 1, "pageSize": 20,
    }  # synthetic edge case
    resp = parse_meter_list(payload)
    assert resp.data[0].serialNo is None  # explicit null, not ""
    assert any("serialNo was blank" in w for w in resp.warnings)


# -- GET /api/v1/transformers --------------------------------------------


def test_transformers_from_real_fixture():
    resp = parse_transformers(load("dts_page1.json"))
    assert resp.total == 40
    assert len(resp.data) == 20
    dt = resp.data[0]
    assert dt.code == "DT-001"
    assert dt.capacityKva == 100
    assert isinstance(dt.capacityKva, int)
    assert resp.warnings == []


def test_transformer_bad_capacity_is_null_with_warning():
    payload = {
        "data": [{"code": "DT-9", "name": "X", "feederCode": "F-9", "capacityKva": "n/a"}],
        "total": 1, "page": 1, "pageSize": 20,
    }  # synthetic edge case
    resp = parse_transformers(payload)
    assert resp.data[0].capacityKva is None
    assert any("not numeric" in w for w in resp.warnings)


# -- location -------------------------------------------------------------


def test_geo_strings_become_floats_from_real_fixture():
    point, warnings = parse_geo(load("geo_j100000.json"))
    assert isinstance(point.latitude, float)
    assert isinstance(point.longitude, float)
    assert point.latitude == pytest.approx(26.938961002479868)
    assert warnings == []


def test_geo_non_numeric_value_is_null_with_warning():
    point, warnings = parse_geo(
        {"data": {"latitude": "--", "longitude": "75.83"}}  # synthetic
    )
    assert point.latitude is None
    assert point.longitude == pytest.approx(75.83)
    assert any("not numeric" in w for w in warnings)


# -- GET /api/v1/meters/{id}/consumption ----------------------------------


def test_energy_from_real_fixture_is_normalised():
    resp = parse_energy(load("energy_one_day.json"))
    assert resp.timezone is None  # unknown - stated, not invented
    assert resp.warnings == []
    assert len(resp.data) == 48  # one day of 30-minute intervals
    first = resp.data[0]
    assert first.timestamp == datetime(2026, 6, 24, 0, 0)  # parsed from DD/MM/YYYY
    assert isinstance(first.kwh, float)
    assert first.kwh == pytest.approx(48439.16)
    assert isinstance(first.voltR, float)


def test_energy_messy_rows_are_surfaced_not_silently_dropped():
    payload = {"data": [
        {"timestamp": "24/06/2026 00:00", "kwh": "1.5", "kvah": "2.5", "voltR": "230"},
        {"timestamp": "not a date", "kwh": "9.9", "kvah": "9.9", "voltR": "230"},
        {"timestamp": "24/06/2026 00:30", "kwh": "\u2014", "kvah": None, "voltR": "bad"},
    ]}  # synthetic edge case: what our handling WOULD do with messy values
    resp = parse_energy(payload)
    assert len(resp.data) == 2  # the timestampless row cannot enter a time series
    assert resp.data[1].kwh is None  # em-dash -> null
    assert resp.data[1].kvah is None
    assert resp.data[1].voltR is None
    assert any("omitted: unparseable timestamp" in w for w in resp.warnings)
    assert any("kwh was non-numeric" in w for w in resp.warnings)
    assert any("voltR was non-numeric" in w for w in resp.warnings)


def test_energy_rejects_non_array_payload():
    with pytest.raises(PortalProtocolError):
        parse_energy({"data": {}})  # synthetic


# -- GET /api/v1/meters/{id} ----------------------------------------------


def test_meter_detail_from_real_fixture():
    resp = parse_meter_detail(load("detail_dataraw_j100000.json"), "J100000")
    assert resp.meterId == "J100000"
    assert len(resp.nameplate) == 6
    assert resp.nameplate[0].parameterName == "Meter ID"
    assert resp.nameplate[4].parameterValue == "Decommissioned"
    assert resp.hierarchy["Zone"] == "Jaipur Zone 1 (Z-01)"
    assert resp.hierarchy["Sub Station"] == "Substation 1 (SS-01)"
    assert resp.hierarchy["DT"] == "Malviya Nagar DT 1 (DT-001)"
    assert resp.warnings == []


def test_unknown_meter_data_payload_raises_not_found():
    """Portal answers HTTP 200 with an error node - we must still 404."""
    with pytest.raises(PortalNotFoundError) as exc:
        parse_meter_detail(load("detail_unknown_meter.json"), "NOPE999")
    assert exc.value.message == "Meter not found"


def test_classData_alternate_shape_is_supported_with_warning():
    payload = {
        "type": "data",
        "nodes": [
            None,
            {"type": "data", "data": []},
            {
                "type": "data",
                "data": [
                    {"meterId": 1, "detail": 2, "hierarchy": 3},  # 0: root
                    "J1",                                        # 1
                    {"classData": 5},                            # 2: detail
                    {"Zone": 4},                                 # 3: hierarchy
                    "Z1",                                        # 4
                    json.dumps({"installed_meter": {"Serial No": "S1"}}),  # 5
                ],
            },
        ],
    }  # synthetic shape, matching the portal's own client code
    resp = parse_meter_detail(payload, "J1")
    assert resp.meterId == "J1"
    assert resp.nameplate[0].parameterName == "Serial No"
    assert resp.nameplate[0].parameterValue == "S1"
    assert resp.hierarchy["Zone"] == "Z1"
    assert any("classData" in w for w in resp.warnings)  # alternate shape flagged


def test_malformed_detail_payload_is_protocol_error():
    with pytest.raises(PortalProtocolError):
        parse_meter_detail({"type": "data"}, "J1")  # synthetic: no nodes


# -- input validation -----------------------------------------------------


def test_parse_api_date_accepts_both_documented_formats():
    assert parse_api_date("2026-06-24") == date(2026, 6, 24)
    assert parse_api_date("24/06/2026") == date(2026, 6, 24)
    assert parse_api_date("03/04/2026") == date(2026, 4, 3)  # day-first


def test_parse_api_date_rejects_garbage_with_useful_message():
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        parse_api_date("June 24 2026")
    with pytest.raises(ValueError):
        parse_api_date("2026/06/24")  # wrong order is refused, not guessed


def test_meter_id_validation_blocks_url_tricks():
    _validate_meter_id("J100000")  # normal id passes
    _validate_meter_id("DT-001_A2")
    for bad in ("../etc", "J100000/x", "J 100", ""):
        with pytest.raises(PortalNotFoundError):
            _validate_meter_id(bad)  # never reaches an f-string URL
