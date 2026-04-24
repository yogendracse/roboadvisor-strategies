from __future__ import annotations

from datetime import date

import pandas as pd

from .base import BasePortfolioStrategy


class StrategyBlender:
    """Blends multiple portfolio strategies into a single set of target weights."""

    def __init__(self, strategies: list[tuple[BasePortfolioStrategy, float]]) -> None:
        total = sum(w for _, w in strategies)
        if total <= 0:
            raise ValueError("Strategy blend weights must sum to a positive number")
        self.strategies = [(s, w / total) for s, w in strategies]

    def compute_target_weights(
        self,
        as_of_date: date,
        universe: list[str],
        price_data: pd.DataFrame,
    ) -> dict[str, float]:
        blended: dict[str, float] = {}
        for strategy, blend_weight in self.strategies:
            w = strategy.compute_target_weights(as_of_date, universe, price_data)
            for ticker, wt in w.items():
                blended[ticker] = blended.get(ticker, 0.0) + blend_weight * wt

        total = sum(blended.values())
        if total <= 0:
            return BasePortfolioStrategy.equal_weight(universe)
        return {t: v / total for t, v in blended.items()}
