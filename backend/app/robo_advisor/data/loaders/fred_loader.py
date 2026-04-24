"""
fred_loader.py
--------------
Downloads macro proxy series from FRED and persists to
backend/data/robo_advisor/macro.parquet.

Required env var:
    FRED_API_KEY   — free key from https://fred.stlouisfed.org/docs/api/api_key.html

Series fetched:
    RECPROUSM156N  NY Fed recession probability  (monthly, %)
    VIXCLS         CBOE VIX closing price        (daily)
    DGS10          10-Year Treasury yield         (daily)
    DGS2           2-Year Treasury yield          (daily, for yield curve)
    FEDFUNDS       Effective Fed Funds Rate        (monthly)
    T10Y2Y         10Y-2Y Treasury spread         (daily, FRED computed)

Schema (Parquet):
    date        date        observation date
    series_id   str         FRED series identifier
    value       float64     raw value from FRED
    series_name str         human-readable label
    as_of_date  date        earliest date data was publicly available (release date);
                            equals observation date for daily series, later for monthly
                            with publication lag. Use this column to prevent lookahead
                            bias in backtests.

Usage:
    from app.robo_advisor.data.loaders.fred_loader import MacroLoader
    loader = MacroLoader()          # reads FRED_API_KEY from env
    loader.refresh()
    df = loader.load("RECPROUSM156N")
"""

from __future__ import annotations

import logging
import os
from datetime import timedelta
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).parents[4] / "data" / "robo_advisor"
_MACRO_PATH = _DATA_DIR / "macro.csv"

DEFAULT_START = "2000-01-01"

SERIES_META: dict[str, str] = {
    "RECPROUSM156N": "NY Fed Recession Probability (%)",
    "VIXCLS":        "CBOE VIX",
    "DGS10":         "10Y Treasury Yield (%)",
    "DGS2":          "2Y Treasury Yield (%)",
    "FEDFUNDS":      "Effective Fed Funds Rate (%)",
    "T10Y2Y":        "10Y-2Y Treasury Spread (%)",
}

# Approximate publication lag per series (days after observation date).
# Used to populate as_of_date — prevents lookahead bias in backtests.
# Daily H.15 releases: ~1 day lag. Monthly series have longer lags.
_RELEASE_LAG_DAYS: dict[str, int] = {
    "RECPROUSM156N": 90,   # NY Fed publishes ~3 months after reference month
    "FEDFUNDS":      30,   # released ~1 month after reference month
    "VIXCLS":         1,
    "DGS10":          1,
    "DGS2":           1,
    "T10Y2Y":         1,
}


class MacroLoader:
    """Downloads and caches FRED macro series."""

    def __init__(self, path: Path = _MACRO_PATH, api_key: str | None = None) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._api_key = api_key or os.environ.get("FRED_API_KEY", "")

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def refresh(
        self,
        series: list[str] | None = None,
        start: str = DEFAULT_START,
    ) -> pd.DataFrame:
        """Fetch *series* from FRED and write to Parquet.

        If FRED_API_KEY is absent, logs a warning and skips — callers should
        fall back to cached data or synthetic proxies.
        """
        if not self._api_key:
            logger.warning(
                "FRED_API_KEY not set. Macro data will not be refreshed. "
                "Set the env var and call MacroLoader.refresh() again."
            )
            return self.load() if self.path.exists() else pd.DataFrame()

        try:
            from fredapi import Fred  # type: ignore[import-untyped]
        except ImportError:
            logger.error("fredapi not installed. Run: uv add fredapi")
            return pd.DataFrame()

        fred = Fred(api_key=self._api_key)
        target_series = series or list(SERIES_META.keys())
        frames: list[pd.DataFrame] = []

        for sid in target_series:
            try:
                logger.info("Fetching FRED series %s", sid)
                raw: pd.Series = fred.get_series(sid, observation_start=start)
                lag = timedelta(days=_RELEASE_LAG_DAYS.get(sid, 1))
                obs_dates = pd.to_datetime(raw.index).date
                df = pd.DataFrame(
                    {
                        "date": obs_dates,
                        "series_id": sid,
                        "value": raw.values,
                        "series_name": SERIES_META.get(sid, sid),
                        "as_of_date": [d + lag for d in obs_dates],
                    }
                ).dropna(subset=["value"])
                frames.append(df)
                logger.info("  → %d rows for %s", len(df), sid)
            except Exception as exc:
                logger.error("Failed to fetch %s: %s", sid, exc)

        if not frames:
            return pd.DataFrame()

        combined = pd.concat(frames, ignore_index=True)
        combined = combined.sort_values(["series_id", "date"]).reset_index(drop=True)
        combined.to_csv(self.path, index=False)
        logger.info("Wrote %d rows to %s", len(combined), self.path)
        return combined

    def load(self, series_id: str | None = None) -> pd.DataFrame:
        """Load cached macro data.  Pass *series_id* to filter."""
        if not self.path.exists():
            raise FileNotFoundError(
                f"No macro data at {self.path}. Run MacroLoader.refresh() first "
                "(requires FRED_API_KEY env var)."
            )
        df = pd.read_csv(self.path, parse_dates=["date"])
        df["date"] = df["date"].dt.date
        if series_id:
            df = df[df["series_id"] == series_id.upper()].copy()
            if df.empty:
                raise KeyError(f"Series '{series_id}' not found in cache.")
        return df

    def available_series(self) -> list[str]:
        if not self.path.exists():
            return []
        df = pd.read_csv(self.path, usecols=["series_id"])
        return sorted(df["series_id"].unique().tolist())

    # ------------------------------------------------------------------ #
    # Normalised accessors (used by harmonizer)                           #
    # ------------------------------------------------------------------ #

    def recession_prob(self) -> pd.DataFrame:
        """Return RECPROUSM156N as a probability in [0, 1] (divide by 100)."""
        df = self.load("RECPROUSM156N")
        df = df.copy()
        df["value"] = df["value"] / 100.0
        return df

    def vix_percentile(self, window: int = 252) -> pd.DataFrame:
        """Return VIX normalised to [0, 1] via rolling *window*-day percentile."""
        df = self.load("VIXCLS").copy()
        df = df.sort_values("date").reset_index(drop=True)
        df["value"] = (
            df["value"]
            .rolling(window, min_periods=30)
            .rank(pct=True)
        )
        return df.dropna(subset=["value"])

    def yield_curve_slope(self) -> pd.DataFrame:
        """Return 10Y − 2Y spread (positive = normal; negative = inverted)."""
        dgs10 = self.load("DGS10").set_index("date")["value"].rename("dgs10")
        dgs2  = self.load("DGS2").set_index("date")["value"].rename("dgs2")
        merged = pd.concat([dgs10, dgs2], axis=1).dropna()
        merged["value"] = merged["dgs10"] - merged["dgs2"]
        merged = merged.reset_index()[["date", "value"]]
        merged["series_id"] = "YIELD_CURVE_SLOPE"
        merged["series_name"] = "10Y-2Y Yield Curve Slope (%)"
        return merged
