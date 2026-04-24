from __future__ import annotations

from datetime import date

import pandas as pd


class SPYBuyHold:
    """100% SPY, rebalances to SPY every period (effectively buy-and-hold)."""

    def compute_target_weights(
        self, as_of_date: date, universe: list[str], price_data: pd.DataFrame
    ) -> dict[str, float]:
        return {t: (1.0 if t == "SPY" else 0.0) for t in universe}


class SixtyForty:
    """60% SPY / 40% TLT, monthly rebalanced."""

    def compute_target_weights(
        self, as_of_date: date, universe: list[str], price_data: pd.DataFrame
    ) -> dict[str, float]:
        w: dict[str, float] = {t: 0.0 for t in universe}
        if "SPY" in w:
            w["SPY"] = 0.60
        if "TLT" in w:
            w["TLT"] = 0.40
        # Renormalize if one leg missing
        total = sum(w.values())
        if total > 0:
            w = {t: v / total for t, v in w.items()}
        return w


class EqualWeight:
    """1/N across all universe tickers."""

    def compute_target_weights(
        self, as_of_date: date, universe: list[str], price_data: pd.DataFrame
    ) -> dict[str, float]:
        n = len(universe)
        return {t: 1.0 / n for t in universe}
