from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

import numpy as np
import pandas as pd

MIN_POSITION = 0.01
MAX_POSITION = 0.25


class BasePortfolioStrategy(ABC):
    @abstractmethod
    def compute_target_weights(
        self,
        as_of_date: date,
        universe: list[str],
        price_data: pd.DataFrame,  # wide: DatetimeIndex, columns=tickers, values=adj_close
    ) -> dict[str, float]:
        ...

    @staticmethod
    def validate_weights(
        weights: dict[str, float],
        min_pos: float = MIN_POSITION,
        max_pos: float = MAX_POSITION,
    ) -> dict[str, float]:
        """Clip to [min_pos, max_pos] and renormalize to sum=1."""
        tickers = list(weights.keys())
        w = np.array([weights[t] for t in tickers], dtype=float)
        w = np.clip(w, min_pos, max_pos)
        total = w.sum()
        if total <= 0:
            w = np.ones(len(tickers)) / len(tickers)
        else:
            w = w / total
        return dict(zip(tickers, w.tolist()))

    @staticmethod
    def equal_weight(universe: list[str]) -> dict[str, float]:
        n = len(universe)
        return {t: 1.0 / n for t in universe}
