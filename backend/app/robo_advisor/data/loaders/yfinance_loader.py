"""
yfinance_loader.py
------------------
Downloads daily OHLCV data for a list of tickers and persists to
backend/data/robo_advisor/prices.parquet.

Schema (Parquet):
    date        date        trading date
    ticker      str         Yahoo Finance symbol
    open        float64
    high        float64
    low         float64
    close       float64
    volume      float64
    adj_close   float64

Usage:
    from app.robo_advisor.data.loaders.yfinance_loader import PriceLoader
    loader = PriceLoader()
    loader.refresh(["SPY", "QQQ", "TLT"])
    df = loader.load("SPY")
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).parents[4] / "data" / "robo_advisor"
_PRICES_PATH = _DATA_DIR / "prices.csv"

# Default universe — matches the core macro sleeve in requirements
DEFAULT_UNIVERSE = ["SPY", "QQQ", "TLT", "IEF", "GLD", "DBC", "VNQ", "VXUS"]
DEFAULT_START = "2000-01-01"


class PriceLoader:
    """Downloads and caches daily OHLCV data via yfinance."""

    def __init__(self, path: Path = _PRICES_PATH) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def refresh(
        self,
        tickers: list[str] = DEFAULT_UNIVERSE,
        start: str = DEFAULT_START,
        end: str | None = None,
    ) -> pd.DataFrame:
        """Download *tickers* from *start* to *end* and write to Parquet.

        Incremental: if Parquet already exists, only fetches dates after the
        last stored date for each ticker to avoid redundant downloads.
        """
        end = end or date.today().isoformat()
        existing = self._read_existing()

        frames: list[pd.DataFrame] = []

        for ticker in tickers:
            fetch_start = start
            if existing is not None and ticker in existing["ticker"].values:
                last = existing.loc[existing["ticker"] == ticker, "date"].max()
                if last >= pd.Timestamp(end).date():
                    logger.info("%s is up to date, skipping", ticker)
                    frames.append(existing[existing["ticker"] == ticker])
                    continue
                fetch_start = (last + pd.Timedelta(days=1)).isoformat()

            logger.info("Fetching %s from %s to %s", ticker, fetch_start, end)
            raw = yf.download(
                ticker,
                start=fetch_start,
                end=end,
                auto_adjust=False,
                progress=False,
                multi_level_index=False,
            )
            if raw.empty:
                logger.warning("No data returned for %s", ticker)
                continue

            df = self._normalise(raw, ticker)
            frames.append(df)

        if not frames:
            logger.warning("No data fetched; Parquet unchanged")
            return existing if existing is not None else pd.DataFrame()

        combined = pd.concat(frames, ignore_index=True)
        combined = combined.sort_values(["ticker", "date"]).reset_index(drop=True)
        combined.to_csv(self.path, index=False)
        logger.info("Wrote %d rows to %s", len(combined), self.path)
        return combined

    def load(self, ticker: str | None = None) -> pd.DataFrame:
        """Load cached prices.  Pass *ticker* to filter to a single symbol."""
        df = self._read_existing()
        if df is None:
            raise FileNotFoundError(
                f"No price data at {self.path}. Run PriceLoader.refresh() first."
            )
        if ticker:
            df = df[df["ticker"] == ticker.upper()].copy()
            if df.empty:
                raise KeyError(f"Ticker '{ticker}' not found in cache.")
        return df

    def available_tickers(self) -> list[str]:
        df = self._read_existing()
        return sorted(df["ticker"].unique().tolist()) if df is not None else []

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _read_existing(self) -> pd.DataFrame | None:
        if not self.path.exists():
            return None
        df = pd.read_csv(self.path, parse_dates=["date"])
        df["date"] = df["date"].dt.date
        return df

    @staticmethod
    def _normalise(raw: pd.DataFrame, ticker: str) -> pd.DataFrame:
        raw = raw.copy()
        raw.index = pd.to_datetime(raw.index)
        raw.columns = [c.lower().replace(" ", "_") for c in raw.columns]

        rename = {"adj_close": "adj_close"}
        if "adj close" in raw.columns:
            rename["adj close"] = "adj_close"

        df = pd.DataFrame(
            {
                "date": raw.index.date,
                "ticker": ticker.upper(),
                "open": raw.get("open", raw.get("Open")),
                "high": raw.get("high", raw.get("High")),
                "low": raw.get("low", raw.get("Low")),
                "close": raw.get("close", raw.get("Close")),
                "volume": raw.get("volume", raw.get("Volume")),
                "adj_close": raw.get("adj_close", raw.get("adjclose", raw.get("close"))),
            }
        )
        return df.dropna(subset=["close"])
