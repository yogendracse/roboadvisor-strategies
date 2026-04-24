from __future__ import annotations

import logging
from datetime import date

import numpy as np
import pandas as pd

from .base import BasePortfolioStrategy, MIN_POSITION, MAX_POSITION

logger = logging.getLogger(__name__)

_LOOKBACK = 252


class RiskParityStrategy(BasePortfolioStrategy):
    def __init__(
        self,
        mode: str = "inverse_vol",
        lookback: int = _LOOKBACK,
        min_pos: float = MIN_POSITION,
        max_pos: float = MAX_POSITION,
    ) -> None:
        self.mode = mode
        self.lookback = lookback
        self.min_pos = min_pos
        self.max_pos = max_pos

    def compute_target_weights(
        self,
        as_of_date: date,
        universe: list[str],
        price_data: pd.DataFrame,
    ) -> dict[str, float]:
        cols = [c for c in universe if c in price_data.columns]
        if not cols:
            return self.equal_weight(universe)

        df = price_data[cols].copy()
        df = df[df.index <= pd.Timestamp(as_of_date)]
        df = df.tail(self.lookback + 1).dropna(how="all")

        if len(df) < 2:
            return self.equal_weight(universe)

        returns = df.pct_change().dropna()
        if returns.empty:
            return self.equal_weight(universe)

        vols = returns.std().values.astype(float)
        vols = np.where(vols < 1e-8, 1e-8, vols)
        inv_vols = 1.0 / vols
        raw_weights = inv_vols / inv_vols.sum()

        result = {t: float(raw_weights[i]) for i, t in enumerate(cols)}
        for t in universe:
            if t not in result:
                result[t] = 0.0
        return self.validate_weights(result, self.min_pos, self.max_pos)
