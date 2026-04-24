from __future__ import annotations
from datetime import date
import numpy as np
import pandas as pd
import pytest
from app.robo_advisor.backtest.engine import BacktestEngine
from app.robo_advisor.backtest.benchmarks import EqualWeight, SPYBuyHold, SixtyForty
from app.robo_advisor.backtest.metrics import compute_all, max_drawdown, sharpe_ratio

_START, _END = date(2020, 1, 2), date(2021, 12, 31)


def _prices(n=504, assets=3, seed=42):
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2020-01-02", periods=n, freq="B")
    tickers = [f"A{i}" for i in range(assets)]
    p = pd.DataFrame(100 * np.cumprod(1 + rng.normal(3e-4, 0.01, (n, assets)), axis=0), index=dates, columns=tickers)
    return p, tickers


def _engine(**kw):
    return BacktestEngine(_START, _END, 100_000, kw.get("freq", "monthly"), kw.get("cost", 5))


def test_equity_curve_length():
    p, t = _prices()
    res = _engine().run(EqualWeight(), t, p)
    assert len(res.equity_curve) == len(p)
    assert res.equity_curve.iloc[0] == pytest.approx(100_000, rel=1e-4)


def test_tx_cost_reduces_value():
    p, t = _prices()
    r0 = BacktestEngine(_START, _END, 100_000, "monthly", 0).run(EqualWeight(), t, p)
    r1 = BacktestEngine(_START, _END, 100_000, "monthly", 100).run(EqualWeight(), t, p)
    assert r0.equity_curve.iloc[-1] > r1.equity_curve.iloc[-1]


def test_quarterly_fewer_trades_than_monthly():
    p, t = _prices()
    rm = BacktestEngine(_START, _END, 100_000, "monthly", 5).run(EqualWeight(), t, p)
    rq = BacktestEngine(_START, _END, 100_000, "quarterly", 5).run(EqualWeight(), t, p)
    assert len(rm.trades) > len(rq.trades)


def test_missing_ticker_raises():
    p, t = _prices(assets=2)
    with pytest.raises(ValueError, match="not found"):
        _engine().run(EqualWeight(), ["A0", "A1", "MISSING"], p)


def test_metrics_sanity():
    p, t = _prices()
    res = _engine().run(EqualWeight(), t, p)
    m = res.metrics
    assert -1 <= m["max_drawdown"] <= 0
    assert 0 < m["volatility"] < 2
    assert m["total_return"] == pytest.approx((res.equity_curve.iloc[-1] / 100_000) - 1, abs=1e-3)
