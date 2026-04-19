"""Service for managing Live Signals instruments.

Stored separately under data/live/*.csv to avoid polluting vol/trend catalogues.
Reuses the yfinance fetch and upload parsing logic from instrument_service.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from app.core.config import LIVE_DATA_DIR
from app.schemas.live import LiveInstrument
from app.services.instrument_service import (
    InstrumentError,
    _load_csv,
    _safe_id,
    fetch_yfinance,
    parse_upload,
)


def _csv_path(instrument_id: str) -> Path:
    return LIVE_DATA_DIR / f"{instrument_id}.csv"


def _stat(path: Path) -> LiveInstrument | None:
    try:
        df = pd.read_csv(path, parse_dates=["Date"])
        if df.empty:
            return None
        return LiveInstrument(
            id=path.stem,
            label=path.stem,
            n_rows=len(df),
            min_date=df["Date"].min().date(),
            max_date=df["Date"].max().date(),
        )
    except Exception:
        return None


def list_instruments() -> list[LiveInstrument]:
    out: list[LiveInstrument] = []
    for path in sorted(LIVE_DATA_DIR.glob("*.csv")):
        stat = _stat(path)
        if stat is not None:
            out.append(stat)
    return out


def get_instrument(instrument_id: str) -> LiveInstrument:
    for inst in list_instruments():
        if inst.id == instrument_id:
            return inst
    raise InstrumentError(f"Live instrument not found: {instrument_id}")


def load_instrument_frame(instrument_id: str) -> pd.DataFrame:
    path = _csv_path(instrument_id)
    if not path.exists():
        raise InstrumentError(f"Live instrument not found: {instrument_id}")
    return _load_csv(path)


def add_from_yfinance(ticker: str) -> LiveInstrument:
    ticker = ticker.upper().strip()
    if not ticker:
        raise InstrumentError("Ticker required")
    df = fetch_yfinance(ticker)
    if len(df) < 100:
        raise InstrumentError(
            f"Too little data for {ticker} ({len(df)} rows; need ≥100)"
        )
    instrument_id = _safe_id(ticker)
    path = _csv_path(instrument_id)
    df[["Date", "Close"]].to_csv(path, index=False)
    return get_instrument(instrument_id)


def add_from_upload(label: str, file_bytes: bytes, filename: str) -> LiveInstrument:
    label = label.strip()
    if not label:
        raise InstrumentError("Label required")
    df = parse_upload(file_bytes, filename)
    if len(df) < 50:
        raise InstrumentError(f"Upload has only {len(df)} rows (need ≥50)")
    instrument_id = _safe_id(label)
    path = _csv_path(instrument_id)
    df[["Date", "Close"]].to_csv(path, index=False)
    return get_instrument(instrument_id)


def refresh_from_yfinance(instrument_id: str) -> LiveInstrument:
    """Re-fetch data from yfinance and overwrite the stored CSV.

    Uses the instrument_id as the yfinance ticker (works for instruments that
    were originally added via yfinance; CSV-uploaded instruments will error).
    """
    path = _csv_path(instrument_id)
    if not path.exists():
        raise InstrumentError(f"Live instrument not found: {instrument_id}")
    df = fetch_yfinance(instrument_id)
    if len(df) < 100:
        raise InstrumentError(
            f"yfinance returned too little data for '{instrument_id}' ({len(df)} rows). "
            "If this instrument was added via CSV upload, refresh is not supported."
        )
    df[["Date", "Close"]].to_csv(path, index=False)
    return get_instrument(instrument_id)


def delete_instrument(instrument_id: str) -> None:
    path = _csv_path(instrument_id)
    if not path.exists():
        raise InstrumentError(f"Live instrument not found: {instrument_id}")
    path.unlink()
