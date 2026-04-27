"""Tests for sensitivity_regression.py."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# Allow imports from backend root
sys.path.insert(0, str(Path(__file__).parents[1]))

from analysis.sensitivity_regression import (
    ASSETS,
    SIGNALS,
    RegressionResult,
    SensitivityRegressor,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _synthetic_data(
    beta: float = -1.5,
    n: int = 200,
    noise_std: float = 0.01,
    seed: int = 42,
) -> pd.DataFrame:
    """DataFrame with known beta between delta_signal and asset_ret, adjusted for market (SPY)."""
    rng = np.random.default_rng(seed)
    delta = rng.normal(0, 0.01, n)
    spy_ret = rng.normal(0, 0.02, n) # Market return
    # Fill other assets
    dates = pd.date_range("2020-01-01", periods=n, freq="D")
    df = pd.DataFrame({"delta_signal": delta, "SPY_ret": spy_ret}, index=dates)
    for asset in ASSETS:
        if asset != "SPY":
            if asset == "QQQ": # We'll use QQQ for testing the alpha isolation beta recovery
                df[f"{asset}_ret"] = spy_ret + beta * delta + rng.normal(0, noise_std, n)
            else:
                df[f"{asset}_ret"] = spy_ret + rng.normal(0, 0.01, n)
    return df

class TestRegressionRecoversBeta:
    def test_known_negative_beta(self) -> None:
        true_beta = -1.5
        reg = SensitivityRegressor()
        data = _synthetic_data(beta=true_beta, n=300)
        result = reg.run_regression(
            "recession_prob", "QQQ", data, "synthetic", "test"
        )
        assert result.excess_return_beta is not None
        assert abs(result.excess_return_beta - true_beta) / abs(true_beta) < 0.10, (
            f"Expected beta ≈ {true_beta}, got {result.excess_return_beta:.4f}"
        )

    def test_known_positive_beta(self) -> None:
        true_beta = 0.8
        reg = SensitivityRegressor()
        data = _synthetic_data(beta=true_beta, n=300)
        result = reg.run_regression(
            "fed_cuts_expected", "QQQ", data, "synthetic", "test"
        )
        assert result.excess_return_beta is not None
        assert abs(result.excess_return_beta - true_beta) / abs(true_beta) < 0.10

    def test_significant_p_value(self) -> None:
        reg = SensitivityRegressor()
        data = _synthetic_data(beta=-2.0, n=500, noise_std=0.005)
        result = reg.run_regression("recession_prob", "QQQ", data, "synthetic", "test")
        assert result.p_value_hc3 is not None
        assert result.p_value_hc3 < 0.05
        assert result.significant

    def test_conf_interval_contains_true_beta(self) -> None:
        true_beta = -1.5
        reg = SensitivityRegressor()
        data = _synthetic_data(beta=true_beta, n=300)
        result = reg.run_regression("recession_prob", "QQQ", data, "synthetic", "test")
        assert result.conf_interval_low is not None
        assert result.conf_interval_high is not None
        assert result.conf_interval_low <= true_beta <= result.conf_interval_high


# ── 2. All-zero signal changes → returns None gracefully ─────────────────────

class TestAllZeroSignal:
    def test_zero_variance_signal_returns_none(self) -> None:
        reg = SensitivityRegressor()
        rng = np.random.default_rng(0)
        n = 100
        df = pd.DataFrame(
            {
                "delta_signal": np.zeros(n),
                "QQQ_ret": rng.normal(0, 0.01, n),
                "SPY_ret": rng.normal(0, 0.01, n),
            }
        )
        result = reg.run_regression("recession_prob", "QQQ", df, "test", "test")
        assert result.excess_return_beta is None
        assert result.p_value_hc3 is None

    def test_empty_dataframe_returns_none(self) -> None:
        reg = SensitivityRegressor()
        result = reg.run_regression("recession_prob", "QQQ", pd.DataFrame(), "test", "test")
        assert result.excess_return_beta is None
        assert result.n_observations == 0

    def test_too_few_rows_returns_none(self) -> None:
        reg = SensitivityRegressor()
        df = pd.DataFrame({"delta_signal": [0.01, -0.01], "QQQ_ret": [0.005, -0.003], "SPY_ret": [0.0, 0.0]})
        result = reg.run_regression("recession_prob", "QQQ", df, "test", "test")
        assert result.excess_return_beta is None  # n < 10 → skip


# ── 3. Missing dates handled via inner join ───────────────────────────────────

class TestMissingDates:
    def test_inner_join_drops_misaligned_dates(self) -> None:
        """Signal and prices on different date ranges — inner join keeps overlap."""
        rng = np.random.default_rng(1)
        sig_dates = pd.date_range("2020-01-01", periods=100, freq="D")
        price_dates = pd.date_range("2020-01-15", periods=100, freq="D")

        delta = pd.Series(rng.normal(0, 0.01, 100), index=sig_dates, name="delta_signal")
        prices = pd.DataFrame(
            {f"{a}_ret": rng.normal(0, 0.01, 100) for a in ASSETS},
            index=price_dates,
        )
        # Simulate what prepare_data returns
        df = delta.to_frame().join(prices, how="inner").dropna()
        assert len(df) == 86  # 100 - 14 days gap at start
        assert df.index[0] == pd.Timestamp("2020-01-15")

    def test_regression_on_partial_overlap(self) -> None:
        rng = np.random.default_rng(2)
        n = 80
        dates = pd.date_range("2020-01-15", periods=n, freq="D")
        df = pd.DataFrame(
            {
                "delta_signal": rng.normal(0, 0.01, n),
                "QQQ_ret": rng.normal(0, 0.01, n),
                "SPY_ret": rng.normal(0, 0.01, n),
            },
            index=dates,
        )
        reg = SensitivityRegressor()
        result = reg.run_regression("recession_prob", "QQQ", df, "test", "test")
        assert result.n_observations == n
        assert result.excess_return_beta is not None  # Noise regression — beta exists, just insignificant


# ── 4. compare_to_configured flags sign conflicts correctly ──────────────────

class TestCompareToConfigured:
    def _make_reg_with_config(self) -> SensitivityRegressor:
        overlay_cfg = {
            "signals": {
                "recession_prob": {"sensitivities": {"SPY": -1.5, "TLT": 1.0}},
                "fed_cuts_expected": {"sensitivities": {"TLT": 0.8}},
            }
        }
        return SensitivityRegressor(overlay_cfg)

    def _make_result(
        self,
        signal: str,
        asset: str,
        beta: float | None,
        p_value: float | None,
    ) -> RegressionResult:
        return RegressionResult(
            asset=asset,
            signal=signal,
            excess_return_beta=beta,
            alpha=0.0,
            r_squared=0.05,
            p_value_hc3=p_value,
            conf_interval_low=(beta - 0.5) if beta is not None else None,
            conf_interval_high=(beta + 0.5) if beta is not None else None,
            n_observations=200,
            data_source="test",
            period="test",
        )

    def test_sign_conflict_flagged(self) -> None:
        reg = self._make_reg_with_config()
        results = {
            "recession_prob": {
                "SPY": self._make_result("recession_prob", "SPY", beta=+0.9, p_value=0.001),
                "TLT": self._make_result("recession_prob", "TLT", beta=+0.8, p_value=0.010),
            },
            "fed_cuts_expected": {
                "TLT": self._make_result("fed_cuts_expected", "TLT", beta=0.6, p_value=0.02),
            },
        }
        df = reg.compare_to_configured(results)
        spy_row = df[(df["signal"] == "recession_prob") & (df["asset"] == "SPY")].iloc[0]
        assert spy_row["sign_conflict"] == True  # configured=-1.5, empirical=+0.9

        tlt_row = df[(df["signal"] == "recession_prob") & (df["asset"] == "TLT")].iloc[0]
        assert tlt_row["sign_conflict"] == False  # same sign

    def test_no_conflict_when_not_significant(self) -> None:
        reg = self._make_reg_with_config()
        results = {
            "recession_prob": {
                "SPY": self._make_result("recession_prob", "SPY", beta=+0.9, p_value=0.30),
                "TLT": self._make_result("recession_prob", "TLT", beta=-0.3, p_value=0.40),
            },
        }
        df = reg.compare_to_configured(results)
        # Not significant — no conflict even with wrong sign
        for _, row in df.iterrows():
            assert row["sign_conflict"] == False

    def test_none_beta_no_conflict(self) -> None:
        reg = self._make_reg_with_config()
        results = {
            "recession_prob": {
                "SPY": self._make_result("recession_prob", "SPY", beta=None, p_value=None),
            }
        }
        df = reg.compare_to_configured(results)
        spy_row = df.iloc[0]
        assert spy_row["sign_conflict"] == False

    def test_difference_computed_correctly(self) -> None:
        reg = self._make_reg_with_config()
        results = {
            "recession_prob": {
                "SPY": self._make_result("recession_prob", "SPY", beta=-0.80, p_value=0.01),
            }
        }
        df = reg.compare_to_configured(results)
        spy_row = df.iloc[0]
        # configured=-1.5, empirical=-0.80 → difference = -0.80 - (-1.5) = +0.70
        assert spy_row["configured_sensitivity"] == pytest.approx(-1.5)
        assert spy_row["difference"] == pytest.approx(0.70, abs=1e-6)

    def test_low_n_warning_applied(self) -> None:
        reg = SensitivityRegressor.__new__(SensitivityRegressor)
        reg._overlay_cfg = {}
        rng = np.random.default_rng(3)
        n = 30  # below threshold of 60
        df = pd.DataFrame(
            {
                "delta_signal": rng.normal(0, 0.01, n),
                "SPY_ret": rng.normal(0, 0.01, n),
            }
        )
        result = reg.run_regression("recession_prob", "SPY", df, "polymarket", "test")
        assert result.warning is not None
        assert "Insufficient" in result.warning
