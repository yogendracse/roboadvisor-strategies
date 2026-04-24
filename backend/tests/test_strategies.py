"""Unit tests for M2 strategy engine (MVO, Risk Parity, Blender)."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
from app.robo_advisor.strategies.base import BasePortfolioStrategy
from app.robo_advisor.strategies.blender import StrategyBlender
from app.robo_advisor.strategies.mvo import MVOStrategy
from app.robo_advisor.strategies.risk_parity import RiskParityStrategy

# ─── Helpers ──────────────────────────────────────────────────────────────────

_AS_OF = date(2023, 1, 31)


def _price_df(n_days: int = 300, n_assets: int = 3, seed: int = 42) -> tuple[pd.DataFrame, list[str]]:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2022-01-01", periods=n_days, freq="B")
    tickers = [f"A{i}" for i in range(n_assets)]
    rets = rng.normal(0.0005, 0.01, (n_days, n_assets))
    prices = 100.0 * np.cumprod(1 + rets, axis=0)
    df = pd.DataFrame(prices, index=dates, columns=tickers)
    return df, tickers


class _FixedStrategy(BasePortfolioStrategy):
    def __init__(self, weights: dict[str, float]) -> None:
        self._weights = weights

    def compute_target_weights(self, *_, **__) -> dict[str, float]:
        return self._weights


# ─── MVO ──────────────────────────────────────────────────────────────────────

class TestMVO:
    def test_weights_sum_to_one(self):
        df, tickers = _price_df(300, 3)
        w = MVOStrategy().compute_target_weights(_AS_OF, tickers, df)
        assert abs(sum(w.values()) - 1.0) < 1e-5

    def test_weights_respect_min_max(self):
        # Need ≥4 assets for max_pos=0.25 feasibility (4 × 0.25 = 1.0); use 8 like real universe
        df, tickers = _price_df(300, 8)
        w = MVOStrategy(min_pos=0.01, max_pos=0.25).compute_target_weights(_AS_OF, tickers, df)
        for v in w.values():
            assert v >= 0.01 - 1e-5
            assert v <= 0.25 + 1e-5

    def test_high_correlation_no_crash(self):
        rng = np.random.default_rng(0)
        dates = pd.date_range("2022-01-01", periods=300, freq="B")
        base = rng.normal(0.0005, 0.01, 300)
        df = pd.DataFrame(
            {
                "A": 100 * np.cumprod(1 + base),
                "B": 100 * np.cumprod(1 + base + rng.normal(0, 1e-6, 300)),
                "C": 100 * np.cumprod(1 + base + rng.normal(0, 1e-6, 300)),
            },
            index=dates,
        )
        w = MVOStrategy().compute_target_weights(_AS_OF, ["A", "B", "C"], df)
        assert abs(sum(w.values()) - 1.0) < 1e-5

    def test_insufficient_history_falls_back_to_equal_weight(self):
        df, tickers = _price_df(10, 3)
        w = MVOStrategy(lookback=252).compute_target_weights(
            date(2022, 1, 14), tickers, df
        )
        for v in w.values():
            assert abs(v - 1 / 3) < 1e-6

    def test_min_variance_mode(self):
        df, tickers = _price_df(300, 3)
        w = MVOStrategy(mode="min_variance").compute_target_weights(_AS_OF, tickers, df)
        assert abs(sum(w.values()) - 1.0) < 1e-5

    def test_min_variance_favors_low_vol_asset(self):
        rng = np.random.default_rng(7)
        dates = pd.date_range("2022-01-01", periods=300, freq="B")
        df = pd.DataFrame(
            {
                "LOW":  100 * np.cumprod(1 + rng.normal(0.0003, 0.003, 300)),
                "MED":  100 * np.cumprod(1 + rng.normal(0.0003, 0.010, 300)),
                "HIGH": 100 * np.cumprod(1 + rng.normal(0.0003, 0.025, 300)),
            },
            index=dates,
        )
        w = MVOStrategy(mode="min_variance", min_pos=0.01, max_pos=0.99).compute_target_weights(
            _AS_OF, ["LOW", "MED", "HIGH"], df
        )
        assert w["LOW"] > w["HIGH"], "Min-variance should favour lowest-vol asset"


# ─── Risk Parity ──────────────────────────────────────────────────────────────

class TestRiskParity:
    def test_lower_vol_gets_higher_weight(self):
        rng = np.random.default_rng(42)
        dates = pd.date_range("2022-01-01", periods=300, freq="B")
        df = pd.DataFrame(
            {
                "LOW":  100 * np.cumprod(1 + rng.normal(0.0005, 0.005, 300)),
                "HIGH": 100 * np.cumprod(1 + rng.normal(0.0005, 0.020, 300)),
            },
            index=dates,
        )
        w = RiskParityStrategy(min_pos=0.01, max_pos=0.99).compute_target_weights(
            _AS_OF, ["LOW", "HIGH"], df
        )
        assert w["LOW"] > w["HIGH"]

    def test_weights_sum_to_one(self):
        df, tickers = _price_df(300, 8)
        w = RiskParityStrategy().compute_target_weights(_AS_OF, tickers, df)
        assert abs(sum(w.values()) - 1.0) < 1e-6

    def test_all_weights_positive(self):
        df, tickers = _price_df(300, 8)
        w = RiskParityStrategy().compute_target_weights(_AS_OF, tickers, df)
        for v in w.values():
            assert v > 0

    def test_single_asset_returns_one(self):
        rng = np.random.default_rng(0)
        dates = pd.date_range("2022-01-01", periods=100, freq="B")
        df = pd.DataFrame(
            {"X": 100 * np.cumprod(1 + rng.normal(0.001, 0.01, 100))},
            index=dates,
        )
        w = RiskParityStrategy(min_pos=0.0, max_pos=1.0).compute_target_weights(
            date(2022, 5, 20), ["X"], df
        )
        assert abs(w["X"] - 1.0) < 1e-6


# ─── Blender ──────────────────────────────────────────────────────────────────

class TestBlender:
    def test_50_50_blend_is_average(self):
        s1 = _FixedStrategy({"SPY": 0.80, "TLT": 0.20})
        s2 = _FixedStrategy({"SPY": 0.40, "TLT": 0.60})
        blender = StrategyBlender([(s1, 0.5), (s2, 0.5)])
        w = blender.compute_target_weights(_AS_OF, ["SPY", "TLT"], pd.DataFrame())
        assert abs(w["SPY"] - 0.60) < 1e-6
        assert abs(w["TLT"] - 0.40) < 1e-6

    def test_100_0_blend_equals_first_strategy(self):
        s1 = _FixedStrategy({"SPY": 0.70, "TLT": 0.30})
        s2 = _FixedStrategy({"SPY": 0.20, "TLT": 0.80})
        blender = StrategyBlender([(s1, 1.0), (s2, 0.0)])
        w = blender.compute_target_weights(_AS_OF, ["SPY", "TLT"], pd.DataFrame())
        assert abs(w["SPY"] - 0.70) < 1e-6
        assert abs(w["TLT"] - 0.30) < 1e-6

    def test_blended_weights_sum_to_one(self):
        df, tickers = _price_df(300, 8)
        s1 = MVOStrategy()
        s2 = RiskParityStrategy()
        blender = StrategyBlender([(s1, 0.5), (s2, 0.5)])
        w = blender.compute_target_weights(_AS_OF, tickers, df)
        assert abs(sum(w.values()) - 1.0) < 1e-5

    def test_weights_normalized_even_if_inputs_dont_sum_to_one(self):
        # blend weights 2.0 + 1.0 = 3.0, should normalize to 0.667 / 0.333
        s1 = _FixedStrategy({"A": 1.0})
        s2 = _FixedStrategy({"A": 1.0})
        blender = StrategyBlender([(s1, 2.0), (s2, 1.0)])
        w = blender.compute_target_weights(_AS_OF, ["A"], pd.DataFrame())
        assert abs(w["A"] - 1.0) < 1e-6
