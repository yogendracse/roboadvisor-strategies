"""Instrument persistence + loading.

Lifts persistence logic from legacy/vol_app.py (lines 91-213) into a service.
The on-disk format is preserved: Date,Close CSVs in data/ (vol) or data/trend/ (trend),
with sector tags in _metadata.json keyed by label.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from app.core.config import (
    DATA_DIR,
    SP500_BUILTIN_ID,
    SP500_BUILTIN_LABEL,
    SP500_XLSX,
    TREND_BUILTIN_SHEETS,
    TREND_DATA_DIR,
    TREND_XLSX,
)
from app.schemas.common import Instrument, InstrumentKind
from app.services import metadata_service


class InstrumentError(Exception):
    """User-facing errors raised while adding/loading instruments."""


def _safe_id(label: str) -> str:
    return re.sub(r"[^\w\-]", "_", label)


def _dir_for(kind: InstrumentKind) -> Path:
    return DATA_DIR if kind is InstrumentKind.vol else TREND_DATA_DIR


def _csv_path(kind: InstrumentKind, instrument_id: str) -> Path:
    return _dir_for(kind) / f"{instrument_id}.csv"


# ─── Loaders ──────────────────────────────────────────────────────────────────


def load_sp500_builtin() -> pd.DataFrame:
    df = pd.read_excel(SP500_XLSX, usecols=["Date", "Close"])
    df["Date"] = pd.to_datetime(df["Date"])
    return df.sort_values("Date").reset_index(drop=True)


_TREND_BUILTIN_CACHE: dict[str, pd.DataFrame] = {}


def _load_trend_xlsx() -> dict[str, pd.DataFrame]:
    """Parse TREND_data.xlsx once. Each sheet → DataFrame(Date, Close) using the synthetic price column (col 8)."""
    global _TREND_BUILTIN_CACHE
    if _TREND_BUILTIN_CACHE:
        return _TREND_BUILTIN_CACHE
    xl = pd.ExcelFile(TREND_XLSX)
    out: dict[str, pd.DataFrame] = {}
    for sheet, (instrument_id, _label) in TREND_BUILTIN_SHEETS.items():
        raw = xl.parse(sheet, header=None)
        # Row 0 = group labels, Row 1 = real headers, Row 2+ = data. Col 0 = Date, Col 8 = Syn
        df = raw.iloc[2:].reset_index(drop=True).iloc[:, [0, 8]].copy()
        df.columns = ["Date", "Close"]
        df["Date"] = pd.to_datetime(
            df["Date"].astype(str).str.strip(),
            format="%Y%m%d",
            errors="coerce",
        )
        df["Close"] = pd.to_numeric(df["Close"], errors="coerce")
        df = (
            df.dropna()
            .sort_values("Date")
            .drop_duplicates("Date")
            .reset_index(drop=True)
        )
        out[instrument_id] = df
    _TREND_BUILTIN_CACHE = out
    return out


def load_trend_builtin(instrument_id: str) -> pd.DataFrame:
    data = _load_trend_xlsx()
    if instrument_id not in data:
        raise InstrumentError(f"Unknown trend built-in: {instrument_id}")
    return data[instrument_id]


def _load_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["Date"])
    return (
        df.sort_values("Date")
        .drop_duplicates("Date")
        .reset_index(drop=True)[["Date", "Close"]]
    )


def load_instrument_frame(kind: InstrumentKind, instrument_id: str) -> pd.DataFrame:
    """Load a single instrument's DataFrame (Date, Close columns only).

    For built-ins, reads from the bundled Excel files; otherwise from the CSV on disk.
    For trend instruments not found in the trend dir, falls back to the vol dir
    (instruments are shared between strategies).
    """
    if kind is InstrumentKind.vol and instrument_id == SP500_BUILTIN_ID:
        return load_sp500_builtin()
    if kind is InstrumentKind.trend:
        trend_builtins = _load_trend_xlsx()
        if instrument_id in trend_builtins:
            return trend_builtins[instrument_id].copy()
    path = _csv_path(kind, instrument_id)
    if not path.exists():
        # Fall back to vol directory for shared instruments
        if kind is InstrumentKind.trend:
            vol_path = DATA_DIR / f"{instrument_id}.csv"
            if vol_path.exists():
                return _load_csv(vol_path)
        raise InstrumentError(f"Instrument not found: {kind.value}/{instrument_id}")
    return _load_csv(path)


# ─── Metadata (stat only, no loading) ─────────────────────────────────────────


@dataclass
class _CsvStat:
    id: str
    label: str
    n_rows: int
    min_date: date
    max_date: date


def _stat_csv(path: Path) -> _CsvStat | None:
    try:
        df = pd.read_csv(path, usecols=["Date"], parse_dates=["Date"])
        if df.empty:
            return None
        return _CsvStat(
            id=path.stem,
            label=path.stem,
            n_rows=len(df),
            min_date=df["Date"].min().date(),
            max_date=df["Date"].max().date(),
        )
    except Exception:
        return None


def _stat_sp500_builtin() -> Instrument:
    df = load_sp500_builtin()
    return Instrument(
        id=SP500_BUILTIN_ID,
        label=SP500_BUILTIN_LABEL,
        kind=InstrumentKind.vol,
        sector=metadata_service.get_sector(SP500_BUILTIN_LABEL, "Broad Market / Index"),
        n_rows=len(df),
        min_date=df["Date"].min().date(),
        max_date=df["Date"].max().date(),
        builtin=True,
    )


def _stat_trend_builtins() -> list[Instrument]:
    out: list[Instrument] = []
    try:
        data = _load_trend_xlsx()
    except Exception:
        return out
    for instrument_id, (_, label) in [
        (iid, (iid, lbl)) for iid, lbl in (
            (v[0], v[1]) for v in TREND_BUILTIN_SHEETS.values()
        )
    ]:
        df = data.get(instrument_id)
        if df is None or df.empty:
            continue
        out.append(
            Instrument(
                id=instrument_id,
                label=label,
                kind=InstrumentKind.trend,
                sector=None,
                n_rows=len(df),
                min_date=df["Date"].min().date(),
                max_date=df["Date"].max().date(),
                builtin=True,
            )
        )
    return out


def list_instruments(kind: InstrumentKind) -> list[Instrument]:
    """List all instruments of the given kind, including built-ins.

    For trend, also surfaces any vol-directory CSVs that aren't already present
    in the trend-specific directory, so instruments added on one dashboard are
    visible on the other.
    """
    out: list[Instrument] = []
    if kind is InstrumentKind.vol:
        out.append(_stat_sp500_builtin())
    elif kind is InstrumentKind.trend:
        out.extend(_stat_trend_builtins())

    seen_ids: set[str] = {inst.id for inst in out}

    for path in sorted(_dir_for(kind).glob("*.csv")):
        stat = _stat_csv(path)
        if stat is None or stat.id in seen_ids:
            continue
        seen_ids.add(stat.id)
        out.append(
            Instrument(
                id=stat.id,
                label=stat.label,
                kind=kind,
                sector=metadata_service.get_sector(stat.label) if kind is InstrumentKind.vol else None,
                n_rows=stat.n_rows,
                min_date=stat.min_date,
                max_date=stat.max_date,
                builtin=False,
            )
        )

    # For trend: also include user-added instruments from the vol directory
    # (same Date/Close format) that aren't already present.
    if kind is InstrumentKind.trend:
        for path in sorted(DATA_DIR.glob("*.csv")):
            stat = _stat_csv(path)
            if stat is None or stat.id in seen_ids:
                continue
            seen_ids.add(stat.id)
            out.append(
                Instrument(
                    id=stat.id,
                    label=stat.label,
                    kind=kind,
                    sector=None,
                    n_rows=stat.n_rows,
                    min_date=stat.min_date,
                    max_date=stat.max_date,
                    builtin=False,
                )
            )

    return out


def get_instrument(kind: InstrumentKind, instrument_id: str) -> Instrument:
    for inst in list_instruments(kind):
        if inst.id == instrument_id:
            return inst
    raise InstrumentError(f"Instrument not found: {kind.value}/{instrument_id}")


# ─── Writers ──────────────────────────────────────────────────────────────────


def _save_frame(kind: InstrumentKind, instrument_id: str, df: pd.DataFrame) -> None:
    path = _csv_path(kind, instrument_id)
    path.parent.mkdir(exist_ok=True)
    df[["Date", "Close"]].to_csv(path, index=False)


def fetch_yfinance(ticker: str) -> pd.DataFrame:
    import yfinance as yf

    raw = yf.Ticker(ticker).history(period="max")[["Close"]].copy()
    if raw.empty:
        raise InstrumentError(f"yfinance returned no data for {ticker}")
    raw.index = pd.to_datetime(raw.index).tz_localize(None)
    return (
        raw.reset_index()
        .rename(columns={"index": "Date"})
        .sort_values("Date")
        .drop_duplicates("Date")
        .reset_index(drop=True)[["Date", "Close"]]
    )


def _normalise_upload_df(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [c.strip() for c in df.columns]
    col_map: dict[str, str] = {}
    for c in df.columns:
        lc = c.lower()
        if lc in ("date", "time", "datetime"):
            col_map[c] = "Date"
        elif lc in ("close", "adj close", "adjusted close", "price"):
            col_map[c] = "Close"
    if "Date" not in col_map.values() or "Close" not in col_map.values():
        raise InstrumentError(
            "Upload must have a Date column and a Close (or Price / Adj Close) column"
        )
    df = df.rename(columns=col_map)[["Date", "Close"]]
    df["Date"] = pd.to_datetime(df["Date"])
    return (
        df.dropna()
        .sort_values("Date")
        .drop_duplicates("Date")
        .reset_index(drop=True)
    )


def parse_upload(file_bytes: bytes, filename: str) -> pd.DataFrame:
    if filename.lower().endswith((".xlsx", ".xls")):
        raw = pd.read_excel(io.BytesIO(file_bytes))
    else:
        raw = pd.read_csv(io.BytesIO(file_bytes))
    return _normalise_upload_df(raw)


def add_from_yfinance(
    ticker: str, kind: InstrumentKind, sector: str | None
) -> Instrument:
    ticker = ticker.upper().strip()
    if not ticker:
        raise InstrumentError("Ticker required")
    df = fetch_yfinance(ticker)
    if len(df) < 100:
        raise InstrumentError(
            f"Too little data returned for {ticker} ({len(df)} rows; need ≥100)"
        )
    instrument_id = _safe_id(ticker)
    _save_frame(kind, instrument_id, df)
    if kind is InstrumentKind.vol and sector:
        metadata_service.set_sector(ticker, sector)
    return get_instrument(kind, instrument_id)


def add_from_upload(
    label: str,
    kind: InstrumentKind,
    sector: str | None,
    file_bytes: bytes,
    filename: str,
) -> Instrument:
    label = label.strip()
    if not label:
        raise InstrumentError("Label required")
    df = parse_upload(file_bytes, filename)
    if len(df) < 50:
        raise InstrumentError(f"Upload has only {len(df)} rows (need ≥50)")
    instrument_id = _safe_id(label)
    _save_frame(kind, instrument_id, df)
    if kind is InstrumentKind.vol and sector:
        metadata_service.set_sector(label, sector)
    return get_instrument(kind, instrument_id)


def delete_instrument(kind: InstrumentKind, instrument_id: str) -> None:
    if kind is InstrumentKind.vol and instrument_id == SP500_BUILTIN_ID:
        raise InstrumentError("Cannot delete built-in instrument")
    if kind is InstrumentKind.trend and instrument_id in _load_trend_xlsx():
        raise InstrumentError("Cannot delete built-in instrument")
    path = _csv_path(kind, instrument_id)
    if path.exists():
        path.unlink()
    if kind is InstrumentKind.vol:
        metadata_service.delete_entry(instrument_id)


def update_sector(instrument_id: str, sector: str) -> Instrument:
    metadata_service.set_sector(instrument_id, sector)
    return get_instrument(InstrumentKind.vol, instrument_id)
