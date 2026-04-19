from datetime import date
from enum import Enum

from pydantic import BaseModel, Field


class InstrumentKind(str, Enum):
    vol = "vol"
    trend = "trend"


class Instrument(BaseModel):
    id: str = Field(description="Stable identifier (filename stem or 'sp500-builtin')")
    label: str = Field(description="Display label")
    kind: InstrumentKind
    sector: str | None = None
    n_rows: int
    min_date: date
    max_date: date
    builtin: bool = False


class InstrumentList(BaseModel):
    instruments: list[Instrument]


class SeriesPoint(BaseModel):
    date: date
    close: float


class InstrumentSeries(BaseModel):
    id: str
    label: str
    kind: InstrumentKind
    points: list[SeriesPoint]


class AddYfinanceRequest(BaseModel):
    ticker: str = Field(min_length=1, max_length=20)
    kind: InstrumentKind
    sector: str | None = None


class UpdateSectorRequest(BaseModel):
    sector: str


class AddResponse(BaseModel):
    instrument: Instrument
