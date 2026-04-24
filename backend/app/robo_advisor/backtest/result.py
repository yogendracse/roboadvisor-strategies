from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd


@dataclass
class BacktestResult:
    equity_curve: pd.Series          # DatetimeIndex -> portfolio value
    holdings: pd.DataFrame           # DatetimeIndex x tickers -> weight
    trades: pd.DataFrame             # date, ticker, delta_weight, price, cost_dollars
    metrics: dict[str, float]
    meta: dict[str, object]
    benchmark_results: dict[str, "BacktestResult"] = field(default_factory=dict)

    @property
    def returns(self) -> pd.Series:
        return self.equity_curve.pct_change().dropna()

    @property
    def normalized(self) -> pd.Series:
        """Equity curve normalized to start at 100."""
        return self.equity_curve / self.equity_curve.iloc[0] * 100
