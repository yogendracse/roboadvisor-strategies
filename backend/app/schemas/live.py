from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, Field


class LiveInstrument(BaseModel):
    id: str
    label: str
    n_rows: int
    min_date: date
    max_date: date


class LiveInstrumentList(BaseModel):
    instruments: list[LiveInstrument]


class AddLiveYfinanceRequest(BaseModel):
    ticker: str = Field(min_length=1, max_length=20)


class LiveComputeRequest(BaseModel):
    instrument_id: str
    date_start: date | None = None
    date_end: date | None = None
    strategies: list[str] = Field(
        default=["volatility", "trend"],
        description="Which strategies to compute: 'volatility' and/or 'trend'",
    )
    active_trend_system: str = Field(
        default="30/100 MA",
        description="Which trend system's MA lines to overlay on the price chart",
    )


class LiveComputeResult(BaseModel):
    instrument_id: str
    label: str
    warnings: list[str] = Field(default_factory=list)
    # Price
    price_figure: dict[str, Any]
    # Volatility signals
    vol_figure: dict[str, Any] | None = None
    current_vol_quintile: int | None = None
    current_vol_label: str | None = None
    # Trend signals — one figure per system
    trend_figures: dict[str, dict[str, Any]] = Field(default_factory=dict)
    current_trend_signals: dict[str, float] = Field(default_factory=dict)
    current_trend_labels: dict[str, str] = Field(default_factory=dict)
