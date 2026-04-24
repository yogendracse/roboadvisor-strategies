"""
polymarket_loader.py
--------------------
Fetches price history for Polymarket CLOB outcome tokens.

CLOB endpoint:
    GET https://clob.polymarket.com/prices-history
        ?market={token_id}&interval=max&fidelity=1440

Response: {"history": [{"t": unix_timestamp, "p": float}, ...]}

Rate limit: 2 requests / second (enforced via inter-request sleep).
No authentication required.

Usage:
    from app.robo_advisor.data.loaders.polymarket_loader import PolymarketLoader
    loader = PolymarketLoader()
    df = loader.fetch_price_history("100379...")
    # → DataFrame[date, probability]
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

logger = logging.getLogger(__name__)

CLOB_BASE = "https://clob.polymarket.com"
_REQ_INTERVAL = 0.5  # seconds between requests → 2 req/sec


class PolymarketLoader:
    """Thin wrapper around the Polymarket CLOB price-history API."""

    def __init__(self, req_interval: float = _REQ_INTERVAL) -> None:
        self._req_interval = req_interval
        self._last_req_at: float = 0.0
        self._session = requests.Session()
        self._session.headers.update({"Accept": "application/json"})

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def fetch_price_history(
        self,
        token_id: str,
        fidelity: int = 1440,
    ) -> pd.DataFrame:
        """Return daily close probabilities for *token_id*.

        Returns
        -------
        pd.DataFrame
            Columns: date (datetime.date), probability (float in [0, 1])
            Empty DataFrame if the token returned no history.
        """
        self._throttle()

        url = f"{CLOB_BASE}/prices-history"
        params = {"market": token_id, "interval": "max", "fidelity": fidelity}

        try:
            resp = self._session.get(url, params=params, timeout=15)
            resp.raise_for_status()
        except requests.RequestException as exc:
            logger.error("CLOB request failed for token %s…: %s", token_id[:12], exc)
            return pd.DataFrame(columns=["date", "probability"])

        raw = resp.json().get("history", [])
        if not raw:
            logger.warning("Empty history for token %s…", token_id[:12])
            return pd.DataFrame(columns=["date", "probability"])

        df = pd.DataFrame(raw)                       # columns: t, p
        df["date"] = pd.to_datetime(
            df["t"], unit="s", utc=True
        ).dt.tz_convert(None).dt.normalize().dt.date
        df = (
            df.rename(columns={"p": "probability"})
            [["date", "probability"]]
            .drop_duplicates(subset="date", keep="last")
            .sort_values("date")
            .reset_index(drop=True)
        )
        df["probability"] = df["probability"].clip(0.0, 1.0)
        logger.info(
            "  token %s…: %d rows (%s → %s)",
            token_id[:12],
            len(df),
            df["date"].min(),
            df["date"].max(),
        )
        return df

    def fetch_many(
        self,
        token_ids: list[str],
        fidelity: int = 1440,
    ) -> dict[str, pd.DataFrame]:
        """Fetch price history for multiple tokens, rate-limited.

        Returns dict mapping token_id → DataFrame[date, probability].
        Tokens with empty history are included as empty DataFrames.
        """
        results: dict[str, pd.DataFrame] = {}
        for i, tid in enumerate(token_ids, 1):
            logger.info("Fetching token %d/%d: %s…", i, len(token_ids), tid[:12])
            results[tid] = self.fetch_price_history(tid, fidelity=fidelity)
        return results

    # ------------------------------------------------------------------ #
    # Internal                                                             #
    # ------------------------------------------------------------------ #

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_req_at
        if elapsed < self._req_interval:
            time.sleep(self._req_interval - elapsed)
        self._last_req_at = time.monotonic()
