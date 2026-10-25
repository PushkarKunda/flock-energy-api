"""Pydantic response models for the REST API.

Design rules (kept deliberately simple):
  * Field names MIRROR the portal's JSON (camelCase) so every response field is
    trivially traceable to PROTOCOL.md - this is a thin, honest wrapper.
  * All values are normalised types: numbers are numbers, timestamps are ISO
    8601 datetimes - the raw portal strings are converted in client.py.
  * Missing values are explicit nulls, never silently dropped.
  * Every response can carry `warnings`: human-readable notes about messy or
    anomalous portal records that we surfaced instead of "fixing".
"""

from datetime import datetime

from pydantic import BaseModel, Field


class Warninged(BaseModel):
    """Mixin-style base: any response may carry anomaly notes."""

    warnings: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------
# GET /api/v1/meters
# --------------------------------------------------------------------------


class MeterSummary(BaseModel):
    """One row of the portal's /portal/meters/search result."""

    meterId: str
    serialNo: str | None = None  # explicit null if portal sent blank/missing
    make: str | None = None
    phaseType: str | None = None  # observed: "single" | "three"
    installStatus: str | None = None  # observed: Installed | Faulty | Decommissioned
    dtCode: str | None = None


class MeterListResponse(Warninged):
    """Portal payload {data, total, page, pageSize} plus our warnings."""

    data: list[MeterSummary]
    total: int
    page: int
    pageSize: int


# --------------------------------------------------------------------------
# GET /api/v1/meters/{id}
# --------------------------------------------------------------------------


class NameplateEntry(BaseModel):
    """Portal detail payload is an ordered list of name/value strings."""

    parameterName: str
    parameterValue: str | None = None


class GeoPoint(BaseModel):
    """Portal /geo sends lat/long as strings; client.py converts to float."""

    latitude: float | None = None
    longitude: float | None = None


class MeterDetailResponse(Warninged):
    """Everything the portal's meter detail page shows about one meter."""

    meterId: str
    nameplate: list[NameplateEntry]
    hierarchy: dict[str, str | None]
    location: GeoPoint | None = None


# --------------------------------------------------------------------------
# GET /api/v1/meters/{id}/consumption
# --------------------------------------------------------------------------


class EnergyReading(BaseModel):
    """One 30-minute reading. Portal sends everything as strings."""

    timestamp: datetime  # normalised to ISO 8601; portal gives no timezone
    kwh: float | None = None
    kvah: float | None = None
    voltR: float | None = None


class ConsumptionResponse(Warninged):
    """Energy history for a meter over the portal's window.

    `timezone` is explicit: the portal timestamps carry NO timezone info and we
    could not verify one, so it stays null (documented in PROTOCOL.md).
    """

    data: list[EnergyReading]
    timezone: str | None = None


# --------------------------------------------------------------------------
# GET /api/v1/transformers
# --------------------------------------------------------------------------


class Transformer(BaseModel):
    """One row of the portal's /portal/dts result."""

    code: str
    name: str | None = None
    feederCode: str | None = None
    capacityKva: int | None = None


class TransformerListResponse(Warninged):
    data: list[Transformer]
    total: int
    page: int
    pageSize: int


# --------------------------------------------------------------------------
# Errors - the shape our API returns on failure (never a stack trace)
# --------------------------------------------------------------------------


class ErrorResponse(BaseModel):
    detail: str
