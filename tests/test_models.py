"""Step-2 tests: response models accept the shapes verified in recon and
surface warnings / explicit nulls as designed."""

from datetime import datetime

from app.models import (
    ConsumptionResponse,
    EnergyReading,
    MeterDetailResponse,
    MeterListResponse,
    MeterSummary,
    NameplateEntry,
    Transformer,
    TransformerListResponse,
)


def test_meter_list_mirrors_portal_shape():
    resp = MeterListResponse(
        data=[MeterSummary(meterId="J100000", serialNo="SE33962", make="HPL",
                           phaseType="single", installStatus="Decommissioned",
                           dtCode="DT-001")],
        total=403,
        page=1,
        pageSize=20,
    )
    assert resp.total == 403
    assert resp.warnings == []  # default, no anomalies


def test_blank_portal_values_become_explicit_nulls():
    meter = MeterSummary(meterId="J100099", serialNo=None, make=None)
    assert meter.serialNo is None  # not dropped, not ""
    assert meter.model_dump()["serialNo"] is None


def test_meter_detail_carries_hierarchy_and_warnings():
    detail = MeterDetailResponse(
        meterId="J100000",
        nameplate=[NameplateEntry(parameterName="Meter ID", parameterValue="J100000")],
        hierarchy={"Zone": "Jaipur Zone 1 (Z-01)", "Feeder": None},
        warnings=["hierarchy key 'Feeder' was blank in portal response"],
    )
    assert detail.hierarchy["Feeder"] is None
    assert detail.warnings


def test_energy_reading_is_normalised_types():
    reading = EnergyReading(
        timestamp=datetime(2026, 6, 24, 0, 0),
        kwh=48439.16,
        kvah=52314.29,
        voltR=229.0,
    )
    dumped = reading.model_dump()
    assert isinstance(dumped["kwh"], float)
    assert dumped["timestamp"] == datetime(2026, 6, 24, 0, 0)


def test_consumption_timezone_is_explicit_null():
    resp = ConsumptionResponse(data=[])
    assert resp.timezone is None  # unknown, stated - not guessed


def test_transformer_capacity_is_int():
    t = Transformer(code="DT-001", name="Malviya Nagar DT 1",
                    feederCode="F-001", capacityKva=100)
    assert isinstance(t.capacityKva, int)
    assert TransformerListResponse(data=[t], total=40, page=1, pageSize=20).total == 40
