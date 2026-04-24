"""
harmonizer.py
-------------
Merges all signal sources into a uniform HarmonizedSignal schema.

Priority per (date, signal_name):
  1. polymarket (confidence=1.0) — from signals.parquet built by backfill_polymarket.py
  2. fred_proxy (confidence=0.70) — RECPROUSM156N / FEDFUNDS derived

FRED proxy mapping:
  recession_prob       → RECPROUSM156N / 100
  fed_cuts_expected    → derived from FEDFUNDS level changes (confidence=0.60)
  sp500_close_expected → no FRED proxy; NaN if Polymarket missing

The backtest engine consumes list[HarmonizedSignal] exclusively.
Source is recorded but callers need not care which source won.
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Literal

import pandas as pd
from pydantic import BaseModel, Field, field_validator

from app.robo_advisor.data.loaders.fred_loader import MacroLoader

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).parents[4] / "data" / "robo_advisor"
_SIGNALS_CSV = _DATA_DIR / "signals.csv"

SourceKind = Literal["polymarket", "fred_proxy", "cme_proxy"]

SIGNAL_IDS = ["recession_prob", "fed_cuts_expected", "sp500_close_expected"]

_CONFIDENCE: dict[str, float] = {
    "polymarket": 1.00,
    "fred_proxy":  0.70,
    "cme_proxy":   0.80,
}


class HarmonizedSignal(BaseModel):
    date: date
    signal_name: str
    value: float
    source: SourceKind
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("value", mode="before")
    @classmethod
    def _allow_nan(cls, v: float) -> float:
        return float(v)


class SignalHarmonizer:
    """Combines Polymarket + FRED into a deduplicated signal time series."""

    def __init__(self) -> None:
        self._macro = MacroLoader()

    def get_signals(
        self,
        signal_ids: list[str] | None = None,
        start: str | date | None = None,
        end: str | date | None = None,
        as_of: str | date | None = None,
    ) -> list[HarmonizedSignal]:
        effective_end = as_of or end
        frames = self._collect_frames(signal_ids)
        if frames.empty:
            return []

        df = frames.copy()
        if start:
            df = df[df["date"] >= pd.Timestamp(start).date()]
        if effective_end:
            df = df[df["date"] <= pd.Timestamp(effective_end).date()]

        # Keep highest-confidence source per (date, signal_name)
        df = (
            df.sort_values("confidence", ascending=False)
            .drop_duplicates(subset=["date", "signal_name"])
            .sort_values(["signal_name", "date"])
            .reset_index(drop=True)
        )

        return [
            HarmonizedSignal(
                date=row["date"],
                signal_name=row["signal_name"],
                value=row["value"],
                source=row["source"],
                confidence=row["confidence"],
            )
            for _, row in df.iterrows()
        ]

    def as_dataframe(self, **kwargs) -> pd.DataFrame:
        signals = self.get_signals(**kwargs)
        if not signals:
            return pd.DataFrame(columns=["date", "signal_name", "value", "source", "confidence"])
        return pd.DataFrame([s.model_dump() for s in signals])

    def latest(self, signal_name: str) -> HarmonizedSignal | None:
        signals = self.get_signals(signal_ids=[signal_name])
        if not signals:
            return None
        return max(signals, key=lambda s: s.date)

    # ------------------------------------------------------------------ #

    def _collect_frames(self, signal_ids: list[str] | None) -> pd.DataFrame:
        frames: list[pd.DataFrame] = []

        # 1. Polymarket (signals.csv written by backfill script)
        if _SIGNALS_CSV.exists():
            try:
                pm = pd.read_csv(_SIGNALS_CSV, parse_dates=["date"])
                pm["date"] = pm["date"].dt.date
                if signal_ids:
                    pm = pm[pm["signal_name"].isin(signal_ids)]
                frames.append(pm[["date", "signal_name", "value", "source", "confidence"]])
                logger.debug("Polymarket: %d rows from %s", len(pm), _SIGNALS_CSV)
            except Exception as exc:
                logger.warning("Failed to load signals.csv: %s", exc)

        # 2. FRED proxies (fill gaps where Polymarket has no history)
        try:
            if self._macro.path.exists():
                fred_frames = self._build_fred_proxies(signal_ids)
                frames.extend(fred_frames)
        except Exception as exc:
            logger.debug("FRED proxy unavailable: %s", exc)

        if not frames:
            return pd.DataFrame()

        return pd.concat(frames, ignore_index=True)

    def _build_fred_proxies(self, signal_ids: list[str] | None) -> list[pd.DataFrame]:
        out: list[pd.DataFrame] = []

        # recession_prob ← RECPROUSM156N / 100
        if not signal_ids or "recession_prob" in signal_ids:
            try:
                df = self._macro.recession_prob()[["date", "value"]].copy()
                df = df.rename(columns={"value": "value"})
                df["signal_name"] = "recession_prob"
                df["source"] = "fred_proxy"
                df["confidence"] = _CONFIDENCE["fred_proxy"]
                out.append(df[["date", "signal_name", "value", "source", "confidence"]])
            except Exception as exc:
                logger.debug("RECPROUSM156N proxy skip: %s", exc)

        # fed_cuts_expected ← month-over-month FEDFUNDS drops summed over horizon
        # (crude proxy: annualised implied cuts from level)
        if not signal_ids or "fed_cuts_expected" in signal_ids:
            try:
                ff = self._macro.load("FEDFUNDS")[["date", "value"]].copy()
                ff = ff.sort_values("date").reset_index(drop=True)
                # Rolling 12-month implied cuts = -Δ(12m) / 0.25 (1 cut = 25bp)
                ff["value"] = -(ff["value"].diff(12) / 0.25).clip(lower=0)
                ff = ff.dropna(subset=["value"])
                ff["signal_name"] = "fed_cuts_expected"
                ff["source"] = "fred_proxy"
                ff["confidence"] = 0.60
                out.append(ff[["date", "signal_name", "value", "source", "confidence"]])
            except Exception as exc:
                logger.debug("FEDFUNDS proxy skip: %s", exc)

        return out
