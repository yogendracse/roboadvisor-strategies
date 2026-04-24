from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any, Protocol

import pandas as pd
import numpy as np

from .metrics import compute_all
from .result import BacktestResult

logger = logging.getLogger(__name__)

_VALID_FREQS = {"daily", "weekly", "monthly", "quarterly"}


class StrategyLike(Protocol):
    def compute_target_weights(
        self,
        as_of_date: date,
        universe: list[str],
        price_data: pd.DataFrame,
    ) -> dict[str, float]: ...


class BacktestEngine:
    def __init__(
        self,
        start_date: date,
        end_date: date,
        initial_capital: float = 100_000.0,
        rebalance_freq: str = "monthly",
        tx_cost_bps: float = 5.0,
    ) -> None:
        if rebalance_freq not in _VALID_FREQS:
            raise ValueError(f"rebalance_freq must be one of {_VALID_FREQS}")
        self.start_date = pd.Timestamp(start_date)
        self.end_date = pd.Timestamp(end_date)
        self.initial_capital = float(initial_capital)
        self.rebalance_freq = rebalance_freq
        self.tx_cost_bps = float(tx_cost_bps)

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def run(
        self,
        strategy: StrategyLike,
        universe: list[str],
        price_data: pd.DataFrame,
        strategy_name: str = "portfolio",
    ) -> BacktestResult:
        """Walk-forward backtest.

        price_data: wide DataFrame (DatetimeIndex, columns=tickers, adj_close values).
        """
        # Validate tickers
        missing = [t for t in universe if t not in price_data.columns]
        if missing:
            raise ValueError(
                f"Tickers {missing} not found in price_data. "
                f"Available: {list(price_data.columns)}"
            )

        # Restrict and clean price data for the simulation period
        sim_data = (
            price_data[universe]
            .loc[self.start_date : self.end_date]
            .ffill()
        )
        sim_data = sim_data.dropna(how="all")

        trading_days = sim_data.index
        if len(trading_days) < 5:
            raise ValueError("Too few trading days in [start_date, end_date]")

        rebalance_set = set(self._rebalance_dates(trading_days, self.rebalance_freq))
        # Force allocation on first trading day
        rebalance_set.add(trading_days[0])

        # State
        portfolio_value = self.initial_capital
        current_weights: dict[str, float] = {t: 0.0 for t in universe}
        prev_prices: pd.Series | None = None
        is_first_allocation = True

        # Accumulators
        equity_vals: list[float] = []
        holdings_rows: list[dict[str, float]] = []
        trades_rows: list[dict[str, object]] = []

        for day in trading_days:
            prices = sim_data.loc[day]

            # ── Daily portfolio update ────────────────────────────────────
            if prev_prices is not None and not is_first_allocation:
                allocated = sum(current_weights.values())
                if allocated > 1e-8:
                    r_port = 0.0
                    for t in universe:
                        p0, p1 = float(prev_prices[t]), float(prices[t])
                        if p0 > 1e-8 and not (np.isnan(p0) or np.isnan(p1)):
                            r_port += current_weights[t] * (p1 / p0 - 1)
                    portfolio_value *= 1 + r_port

                    # Drift weights
                    scale = 1 + r_port
                    if scale > 1e-10:
                        new_w: dict[str, float] = {}
                        for t in universe:
                            p0, p1 = float(prev_prices[t]), float(prices[t])
                            if p0 > 1e-8 and not (np.isnan(p0) or np.isnan(p1)):
                                new_w[t] = current_weights[t] * (1 + (p1 / p0 - 1)) / scale
                            else:
                                new_w[t] = current_weights[t] / scale
                        current_weights = new_w

            # ── Rebalance ─────────────────────────────────────────────────
            if day in rebalance_set:
                target = strategy.compute_target_weights(
                    day.date(), universe, price_data
                )

                if not is_first_allocation:
                    # Apply transaction costs
                    turnover = sum(
                        abs(target.get(t, 0.0) - current_weights.get(t, 0.0))
                        for t in universe
                    )
                    cost = turnover * portfolio_value * self.tx_cost_bps / 10_000
                    portfolio_value -= cost

                    for t in universe:
                        delta = target.get(t, 0.0) - current_weights.get(t, 0.0)
                        if abs(delta) > 1e-5:
                            t_cost = abs(delta) * portfolio_value * self.tx_cost_bps / 10_000
                            trades_rows.append(
                                {
                                    "date": day,
                                    "ticker": t,
                                    "delta_weight": round(delta, 6),
                                    "price": round(float(prices[t]), 4),
                                    "cost_dollars": round(t_cost, 4),
                                }
                            )
                else:
                    is_first_allocation = False

                current_weights = {t: target.get(t, 0.0) for t in universe}

            equity_vals.append(portfolio_value)
            holdings_rows.append(dict(current_weights))
            prev_prices = prices

        equity_curve = pd.Series(equity_vals, index=trading_days, name="value")
        holdings_df = pd.DataFrame(holdings_rows, index=trading_days)
        trades_df = (
            pd.DataFrame(trades_rows)
            if trades_rows
            else pd.DataFrame(columns=["date", "ticker", "delta_weight", "price", "cost_dollars"])
        )

        return BacktestResult(
            equity_curve=equity_curve,
            holdings=holdings_df,
            trades=trades_df,
            metrics=compute_all(equity_curve),
            meta={
                "strategy_name": strategy_name,
                "rebalance_freq": self.rebalance_freq,
                "tx_cost_bps": self.tx_cost_bps,
                "start_date": self.start_date.date().isoformat(),
                "end_date": trading_days[-1].date().isoformat(),
                "n_trading_days": len(trading_days),
                "n_rebalances": len(rebalance_set),
            },
        )

    # ------------------------------------------------------------------ #
    # Internals                                                            #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _rebalance_dates(
        trading_days: pd.DatetimeIndex,
        freq: str,
    ) -> list[pd.Timestamp]:
        if freq == "daily":
            return trading_days.tolist()

        period_key = {
            "weekly":    lambda d: (d.year, d.isocalendar()[1]),
            "monthly":   lambda d: (d.year, d.month),
            "quarterly": lambda d: (d.year, (d.month - 1) // 3),
        }[freq]

        seen: set = set()
        result: list[pd.Timestamp] = []
        for d in trading_days:
            key = period_key(d)
            if key not in seen:
                seen.add(key)
                result.append(d)
        return result
