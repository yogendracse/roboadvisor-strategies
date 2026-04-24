"""
robo_advisor.py
---------------
FastAPI router for the Robo-Advisor data pipeline (M1).

Endpoints:
    GET /api/robo-advisor/prices/{ticker}
        Return cached OHLCV rows for a single ticker.
        Query params: start, end (YYYY-MM-DD)

    GET /api/robo-advisor/prices
        Return list of available tickers in cache.

    GET /api/robo-advisor/macro/{series_id}
        Return cached FRED macro series rows.
        Query params: start, end

    GET /api/robo-advisor/macro
        Return list of available FRED series in cache.

    GET /api/robo-advisor/signals
        Return harmonized prediction-market signals.
        Query params: signal_id, start, end

    POST /api/robo-advisor/refresh/prices
        Trigger a background yfinance download for given tickers.

    POST /api/robo-advisor/refresh/macro
        Trigger a background FRED download (requires FRED_API_KEY).
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel

from app.robo_advisor.data.loaders.fred_loader import MacroLoader
from app.robo_advisor.data.loaders.harmonizer import HarmonizedSignal, SignalHarmonizer
from app.robo_advisor.data.loaders.yfinance_loader import DEFAULT_UNIVERSE, PriceLoader

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/robo-advisor", tags=["robo-advisor"])

# Singletons — created once per process
_price_loader = PriceLoader()
_macro_loader = MacroLoader()
_harmonizer = SignalHarmonizer()


# ─── Response models ──────────────────────────────────────────────────────────

class OHLCVRow(BaseModel):
    date: date
    ticker: str
    open: float | None
    high: float | None
    low: float | None
    close: float
    volume: float | None
    adj_close: float | None


class MacroRow(BaseModel):
    date: date
    series_id: str
    value: float
    series_name: str


class RefreshResponse(BaseModel):
    status: str
    message: str


# ─── Price endpoints ──────────────────────────────────────────────────────────

@router.get("/prices", summary="List cached tickers")
def list_prices() -> list[str]:
    return _price_loader.available_tickers()


@router.get("/prices/{ticker}", summary="OHLCV for a single ticker")
def get_prices(
    ticker: str,
    start: Annotated[date | None, Query(description="Start date YYYY-MM-DD")] = None,
    end:   Annotated[date | None, Query(description="End date YYYY-MM-DD")]   = None,
) -> list[OHLCVRow]:
    try:
        df = _price_loader.load(ticker.upper())
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if start:
        df = df[df["date"] >= start]
    if end:
        df = df[df["date"] <= end]

    return [
        OHLCVRow(
            date=row["date"],
            ticker=row["ticker"],
            open=_float_or_none(row.get("open")),
            high=_float_or_none(row.get("high")),
            low=_float_or_none(row.get("low")),
            close=float(row["close"]),
            volume=_float_or_none(row.get("volume")),
            adj_close=_float_or_none(row.get("adj_close")),
        )
        for _, row in df.iterrows()
    ]


@router.post("/refresh/prices", summary="Download latest prices via yfinance")
def refresh_prices(
    background_tasks: BackgroundTasks,
    tickers: Annotated[list[str], Query()] = DEFAULT_UNIVERSE,
    start: str = "2000-01-01",
) -> RefreshResponse:
    background_tasks.add_task(_price_loader.refresh, tickers, start)
    return RefreshResponse(
        status="accepted",
        message=f"Downloading prices for {tickers} in background",
    )


# ─── Macro endpoints ──────────────────────────────────────────────────────────

@router.get("/macro", summary="List cached FRED series")
def list_macro() -> list[str]:
    return _macro_loader.available_series()


@router.get("/macro/{series_id}", summary="FRED macro series values")
def get_macro(
    series_id: str,
    start: Annotated[date | None, Query()] = None,
    end:   Annotated[date | None, Query()] = None,
) -> list[MacroRow]:
    try:
        df = _macro_loader.load(series_id.upper())
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if start:
        df = df[df["date"] >= start]
    if end:
        df = df[df["date"] <= end]

    return [
        MacroRow(
            date=row["date"],
            series_id=row["series_id"],
            value=float(row["value"]),
            series_name=row.get("series_name", row["series_id"]),
        )
        for _, row in df.iterrows()
    ]


@router.post("/refresh/macro", summary="Refresh FRED macro data (requires FRED_API_KEY)")
def refresh_macro(background_tasks: BackgroundTasks) -> RefreshResponse:
    background_tasks.add_task(_macro_loader.refresh)
    return RefreshResponse(
        status="accepted",
        message="Refreshing FRED macro series in background. Requires FRED_API_KEY env var.",
    )


# ─── Signal endpoints ─────────────────────────────────────────────────────────

@router.get("/signals", summary="Harmonized prediction-market signals")
def get_signals(
    signal_id: Annotated[str | None, Query(description="Filter to a specific signal")] = None,
    start:     Annotated[date | None, Query()] = None,
    end:       Annotated[date | None, Query()] = None,
) -> list[HarmonizedSignal]:
    signal_ids = [signal_id] if signal_id else None
    try:
        return _harmonizer.get_signals(
            signal_ids=signal_ids,
            start=start,
            end=end,
        )
    except Exception as exc:
        logger.exception("Signal harmonizer failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/signals/latest", summary="Latest value for each signal")
def get_latest_signals() -> list[HarmonizedSignal]:
    from app.robo_advisor.data.loaders.harmonizer import SIGNAL_IDS
    results = []
    for sid in SIGNAL_IDS:
        sig = _harmonizer.latest(sid)
        if sig:
            results.append(sig)
    return results


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _float_or_none(v) -> float | None:
    try:
        f = float(v)
        import math
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None
