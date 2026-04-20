"""Simulation Engine — sequential, no-lookahead portfolio simulator.

Architecture
────────────
DataController  fetch_ticker_data()
  Fetches each ticker from yfinance for (date_start - warmup) → date_end.
  Pre-computes signals for the full window; shifts by 1 day so trades use
  only information available at yesterday's close.

StrategyModule  _compute_signal()
  Stateless: takes a full price Series, returns a +1/−1 signal Series.
  Four systems: 10/30 MA, 30/100 MA, 80/160 MA, 30-Day Breakout.
  In the simulator a signal of +1 → long; ≤ 0 → flat (cash for that ticker).

SimulationRunner  run_simulation()
  Time-steps through simulation dates. At each step:
    • reads shifted signals (no lookahead)
    • detects signal changes or periodic (weekly) rebalance trigger
    • computes target weights (equal or inverse-vol)
    • applies concentration cap
    • executes trades, deducting TC on actual share delta
    • checks circuit-breaker (drawdown > user limit → liquidate & halt)
    • records portfolio snapshot and rolling KPIs

ResultAggregator  build_result()
  Converts the history list into a StrategyResult (tabs, charts, tables,
  metric strip) so the existing frontend renderer works unchanged.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from pydantic import BaseModel, Field

from app.schemas.results import (
    ChartSpec,
    ColumnSpec,
    Metric,
    StrategyResult,
    TableSpec,
    TabSpec,
)

# ─── Systems ──────────────────────────────────────────────────────────────────

SYSTEMS = {
    "10/30 MA":        (10, 30),
    "30/100 MA":       (30, 100),
    "80/160 MA":       (80, 160),
    "30-Day Breakout": None,
}
SYSTEM_NAMES = list(SYSTEMS.keys())
DEFAULT_SYSTEM = "30/100 MA"


# ─── Params ───────────────────────────────────────────────────────────────────


class SimulatorParams(BaseModel):
    tickers: list[str] = Field(
        default=["AAPL", "MSFT", "SPY"],
        description="Yahoo Finance tickers to simulate (e.g. AAPL, SPY, GLD)",
    )
    date_start: date = Field(description="First simulation day (exclusive of warmup)")
    date_end: date = Field(description="Last simulation day")
    initial_capital: float = Field(
        default=100_000.0, ge=1_000, description="Starting cash ($)"
    )
    weighting: str = Field(
        default="equal",
        description="'equal' (1/N) or 'inv_vol' (inverse 30-day volatility)",
    )
    inv_vol_window: int = Field(
        default=30, ge=5, le=120, description="Lookback days for inverse-vol weights"
    )
    ticker_systems: dict[str, str] = Field(
        default_factory=dict,
        description="Per-ticker system override, e.g. {'AAPL': '80/160 MA'}",
    )
    default_system: str = Field(
        default="30/100 MA",
        description="System used for tickers not in ticker_systems",
    )
    max_drawdown_limit: float = Field(
        default=0.20,
        ge=0.01,
        le=1.0,
        description="Circuit-breaker: liquidate all if drawdown exceeds this fraction (e.g. 0.20 = −20%)",
    )
    concentration_cap: float = Field(
        default=0.40,
        ge=0.05,
        le=1.0,
        description="Max weight for any single ticker (e.g. 0.40 = 40% cap)",
    )
    tc_bps: float = Field(
        default=1.0, ge=0.0, le=20.0, description="Transaction cost per trade (bps)"
    )
    warmup_days: int = Field(
        default=200,
        ge=50,
        le=500,
        description="Calendar days of historical data prepended before date_start for MA burn-in",
    )
    sharpe_window: int = Field(
        default=90, ge=20, le=252, description="Rolling window (days) for Sharpe calculation"
    )
    rebalance_freq: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Rebalance every N trading days for weight drift (in addition to signal changes)",
    )


# ─── Internal state ───────────────────────────────────────────────────────────


@dataclass
class _Snapshot:
    date: pd.Timestamp
    portfolio_value: float
    cash: float
    drawdown: float
    hwm: float
    daily_return: float
    rolling_sharpe: float
    rolling_vol: float
    positions: dict[str, float]  # {ticker: shares}
    weights: dict[str, float]    # {ticker: weight}


@dataclass
class _Trade:
    date: pd.Timestamp
    ticker: str
    action: str          # "BUY" | "SELL"
    shares: float
    price: float
    value: float
    tc_cost: float
    trigger: str         # "signal_change" | "rebalance" | "circuit_breaker"


@dataclass
class _SimState:
    cash: float
    positions: dict[str, float] = field(default_factory=dict)
    hwm: float = 0.0
    history: list[_Snapshot] = field(default_factory=list)
    trades: list[_Trade] = field(default_factory=list)
    circuit_breaker_triggered: bool = False
    circuit_breaker_date: pd.Timestamp | None = None


# ─── Signal computation ────────────────────────────────────────────────────────


def _compute_signal(price: pd.Series, system: str) -> pd.Series:
    """Return a +1 / −1 signal Series (same index as price).

    Uses SMA throughout. Signal of +1 → long; −1 → flat in the simulator.
    """
    if system == "30-Day Breakout":
        hi = price.rolling(30).max().shift(1)
        lo = price.rolling(30).min().shift(1)
        sig = pd.Series(np.nan, index=price.index, dtype=float)
        sig[price > hi] = 1.0
        sig[price < lo] = -1.0
        sig.iloc[:30] = np.nan
        return sig.ffill()

    fast_w, slow_w = SYSTEMS[system]  # type: ignore[misc]
    fast_ma = price.rolling(fast_w).mean()
    slow_ma = price.rolling(slow_w).mean()
    sig = pd.Series(np.where(fast_ma > slow_ma, 1.0, -1.0), index=price.index)
    sig = sig.astype(float)
    sig.iloc[:slow_w] = np.nan
    return sig


# ─── Data controller ──────────────────────────────────────────────────────────


def fetch_ticker_data(
    tickers: list[str],
    date_start: date,
    date_end: date,
    warmup_days: int,
) -> dict[str, pd.DataFrame]:
    """Fetch yfinance data for all tickers including warmup period.

    Returns {ticker: DataFrame(Date index, Close column)}.
    Silently drops tickers that return no data (caller handles warnings).
    """
    import yfinance as yf  # lazy import

    fetch_start = date_start - timedelta(days=warmup_days + 100)  # extra buffer
    fetch_end = date_end + timedelta(days=1)

    out: dict[str, pd.DataFrame] = {}
    for ticker in tickers:
        ticker = ticker.upper().strip()
        try:
            raw = yf.Ticker(ticker).history(start=str(fetch_start), end=str(fetch_end))[["Close"]]
            if raw.empty:
                continue
            raw.index = pd.to_datetime(raw.index).tz_localize(None)
            raw = raw.sort_index().rename_axis("Date")
            raw = raw[~raw.index.duplicated(keep="last")]
            out[ticker] = raw
        except Exception:
            continue
    return out


# ─── Weight helpers ───────────────────────────────────────────────────────────


def _equal_weights(active: list[str]) -> dict[str, float]:
    if not active:
        return {}
    w = 1.0 / len(active)
    return {t: w for t in active}


def _inv_vol_weights(
    active: list[str],
    price_data: dict[str, pd.DataFrame],
    as_of: pd.Timestamp,
    window: int,
) -> dict[str, float]:
    if not active:
        return {}
    vols: dict[str, float] = {}
    for t in active:
        df = price_data[t]
        hist = df.loc[:as_of]["Close"]
        if len(hist) < 5:
            vols[t] = float("inf")
            continue
        rets = np.log(hist / hist.shift(1)).dropna()
        tail = rets.tail(window)
        vol = float(tail.std()) if len(tail) > 1 else float("inf")
        vols[t] = vol if vol > 0 else float("inf")
    inv = {t: 1.0 / v for t, v in vols.items() if v < float("inf")}
    total = sum(inv.values())
    if total == 0:
        return _equal_weights(active)
    return {t: inv.get(t, 0.0) / total for t in active}


def _apply_concentration_cap(
    weights: dict[str, float], cap: float
) -> dict[str, float]:
    """Iteratively clip any weight above cap and re-normalise."""
    w = dict(weights)
    for _ in range(20):  # converge
        clipped = {t: min(v, cap) for t, v in w.items()}
        total = sum(clipped.values())
        if total <= 0:
            return clipped
        normalised = {t: v / total for t, v in clipped.items()}
        if all(v <= cap + 1e-9 for v in normalised.values()):
            return normalised
        w = normalised
    return w


# ─── Trade execution ──────────────────────────────────────────────────────────


def _execute_trades(
    state: _SimState,
    target_weights: dict[str, float],
    prices: dict[str, float],
    date: pd.Timestamp,
    tc_bps: float,
    trigger: str,
) -> None:
    """Adjust positions to match target_weights given current portfolio value."""
    total_equity = state.cash + sum(
        state.positions.get(t, 0.0) * prices.get(t, 0.0) for t in state.positions
    )
    tc_rate = tc_bps / 10_000.0

    for ticker, price in prices.items():
        if price <= 0:
            continue
        target_w = target_weights.get(ticker, 0.0)
        target_value = total_equity * target_w
        target_shares = target_value / price
        current_shares = state.positions.get(ticker, 0.0)
        delta = target_shares - current_shares

        if abs(delta) < 0.001:
            continue

        trade_value = abs(delta) * price
        tc_cost = trade_value * tc_rate
        action = "BUY" if delta > 0 else "SELL"

        # Update position
        state.positions[ticker] = target_shares
        # Update cash (negative for buy, positive for sell, minus TC always)
        state.cash -= delta * price + tc_cost

        state.trades.append(
            _Trade(
                date=date,
                ticker=ticker,
                action=action,
                shares=abs(delta),
                price=price,
                value=trade_value,
                tc_cost=tc_cost,
                trigger=trigger,
            )
        )

    # Liquidate tickers no longer in target
    for ticker in list(state.positions.keys()):
        if ticker not in target_weights or target_weights.get(ticker, 0.0) == 0.0:
            shares = state.positions.get(ticker, 0.0)
            price = prices.get(ticker, 0.0)
            if shares > 0.001 and price > 0:
                sale_value = shares * price
                tc_cost = sale_value * tc_rate
                state.cash += sale_value - tc_cost
                state.trades.append(
                    _Trade(
                        date=date,
                        ticker=ticker,
                        action="SELL",
                        shares=shares,
                        price=price,
                        value=sale_value,
                        tc_cost=tc_cost,
                        trigger=trigger,
                    )
                )
            state.positions[ticker] = 0.0


# ─── Rolling KPI helpers ──────────────────────────────────────────────────────


def _rolling_sharpe(returns: pd.Series, window: int) -> float:
    tail = returns.tail(window).dropna()
    if len(tail) < 10:
        return float("nan")
    mu = tail.mean()
    sd = tail.std()
    if sd == 0:
        return float("nan")
    return float(np.sqrt(252) * mu / sd)


def _rolling_vol(returns: pd.Series, window: int = 30) -> float:
    tail = returns.tail(window).dropna()
    if len(tail) < 5:
        return float("nan")
    return float(tail.std() * np.sqrt(252))


# ─── Simulation runner ────────────────────────────────────────────────────────


def run_simulation(params: SimulatorParams) -> tuple[_SimState, dict[str, pd.DataFrame], list[str]]:
    """Run the full simulation.

    Returns:
        state      — final SimState (history, trades, positions)
        price_data — {ticker: DataFrame} for all successfully fetched tickers
        warnings   — list of warning strings
    """
    warnings: list[str] = []
    tickers = [t.upper().strip() for t in params.tickers if t.strip()]
    tickers = list(dict.fromkeys(tickers))  # deduplicate, preserve order

    if not tickers:
        return _SimState(cash=params.initial_capital), {}, ["No tickers provided."]

    # 1. Fetch data ─────────────────────────────────────────────────────────
    price_data = fetch_ticker_data(tickers, params.date_start, params.date_end, params.warmup_days)

    failed = [t for t in tickers if t not in price_data]
    if failed:
        warnings.append(f"No data returned for: {', '.join(failed)}")

    tickers = [t for t in tickers if t in price_data]
    if not tickers:
        return _SimState(cash=params.initial_capital), price_data, ["No ticker data available."] + warnings

    # 2. Pre-compute signals (shifted by 1 day → no lookahead) ──────────────
    ticker_systems = {t: params.ticker_systems.get(t, params.default_system) for t in tickers}
    signals: dict[str, pd.Series] = {}
    for ticker in tickers:
        sys = ticker_systems[ticker]
        if sys not in SYSTEMS:
            sys = DEFAULT_SYSTEM
            warnings.append(f"{ticker}: unknown system '{ticker_systems[ticker]}', using {DEFAULT_SYSTEM}")
        price_series = price_data[ticker]["Close"]
        raw_sig = _compute_signal(price_series, sys)
        signals[ticker] = raw_sig.shift(1)  # shift: trade on yesterday's signal

    # 3. Build simulation date index ────────────────────────────────────────
    sim_start = pd.Timestamp(params.date_start)
    sim_end = pd.Timestamp(params.date_end)

    # Union of all dates, sliced to simulation window
    all_dates_union = sorted(
        set().union(*[set(price_data[t].index) for t in tickers])
    )
    sim_dates = [d for d in all_dates_union if sim_start <= d <= sim_end]
    if not sim_dates:
        return (
            _SimState(cash=params.initial_capital),
            price_data,
            ["No trading dates found in the selected window."] + warnings,
        )

    # 4. State initialisation ───────────────────────────────────────────────
    state = _SimState(
        cash=params.initial_capital,
        positions={t: 0.0 for t in tickers},
        hwm=params.initial_capital,
    )
    daily_returns: list[float] = []
    prev_signals: dict[str, float] = {t: float("nan") for t in tickers}
    prev_value = params.initial_capital
    rebalance_counter = 0
    gap_tickers: set[str] = set()

    # 5. Time-stepping loop ─────────────────────────────────────────────────
    for step_idx, date in enumerate(sim_dates):
        # Current prices (only tickers with data on this date)
        current_prices: dict[str, float] = {}
        for t in tickers:
            df = price_data[t]
            if date in df.index:
                p = float(df.loc[date, "Close"])
                if not np.isnan(p) and p > 0:
                    current_prices[t] = p
                    gap_tickers.discard(t)
                else:
                    gap_tickers.add(t)
            else:
                gap_tickers.add(t)

        # Portfolio value using most-recent prices for gap tickers
        def _ticker_value(t: str) -> float:
            shares = state.positions.get(t, 0.0)
            if t in current_prices:
                return shares * current_prices[t]
            # Use last known position value (stale — stay put)
            return shares * float(price_data[t]["Close"].iloc[-1]) if shares > 0 else 0.0

        portfolio_value = state.cash + sum(_ticker_value(t) for t in tickers)

        # Daily return
        daily_ret = (portfolio_value - prev_value) / prev_value if prev_value > 0 else 0.0
        daily_returns.append(daily_ret)

        # Update HWM and drawdown
        state.hwm = max(state.hwm, portfolio_value)
        drawdown = (portfolio_value - state.hwm) / state.hwm if state.hwm > 0 else 0.0

        # Circuit breaker
        if -drawdown > params.max_drawdown_limit and not state.circuit_breaker_triggered:
            state.circuit_breaker_triggered = True
            state.circuit_breaker_date = date
            warnings.append(
                f"Circuit breaker triggered on {date.date()}: drawdown {drawdown:.1%} "
                f"exceeded limit −{params.max_drawdown_limit:.0%}. All positions liquidated."
            )
            # Liquidate all positions
            for t, shares in state.positions.items():
                if shares > 0.001 and t in current_prices:
                    p = current_prices[t]
                    tc_cost = shares * p * (params.tc_bps / 10_000)
                    state.cash += shares * p - tc_cost
                    state.trades.append(
                        _Trade(date=date, ticker=t, action="SELL", shares=shares,
                               price=p, value=shares * p, tc_cost=tc_cost, trigger="circuit_breaker")
                    )
                    state.positions[t] = 0.0
            portfolio_value = state.cash
            _record_snapshot(state, date, portfolio_value, drawdown, daily_returns, daily_returns, params, tickers)
            break

        # Read today's signals (shifted → yesterday's signal)
        today_signals: dict[str, float] = {}
        for t in tickers:
            if t in gap_tickers:
                today_signals[t] = float("nan")  # gap → no trade
            else:
                sig_series = signals[t]
                if date in sig_series.index:
                    v = float(sig_series.loc[date])
                    today_signals[t] = v if not np.isnan(v) else float("nan")
                else:
                    today_signals[t] = float("nan")

        # Active tickers (signal = 1, price available)
        active = [
            t for t in tickers
            if today_signals.get(t, float("nan")) == 1.0 and t in current_prices
        ]

        # Detect signal change
        signal_changed = any(
            today_signals.get(t, float("nan")) != prev_signals.get(t, float("nan"))
            for t in tickers
        )
        rebalance_counter += 1
        periodic_rebalance = (rebalance_counter >= params.rebalance_freq)

        if signal_changed or periodic_rebalance or step_idx == 0:
            rebalance_counter = 0
            # Compute target weights
            if not active:
                target_weights: dict[str, float] = {t: 0.0 for t in tickers}
            elif params.weighting == "inv_vol":
                raw_weights = _inv_vol_weights(active, price_data, date, params.inv_vol_window)
                capped = _apply_concentration_cap(raw_weights, params.concentration_cap)
                target_weights = {t: capped.get(t, 0.0) for t in tickers}
            else:
                raw_weights = _equal_weights(active)
                capped = _apply_concentration_cap(raw_weights, params.concentration_cap)
                target_weights = {t: capped.get(t, 0.0) for t in tickers}

            trigger = "signal_change" if signal_changed else ("init" if step_idx == 0 else "rebalance")
            _execute_trades(state, target_weights, current_prices, date, params.tc_bps, trigger)

            # Recalculate value after trades
            portfolio_value = state.cash + sum(_ticker_value(t) for t in tickers)

        # Current weights (for snapshot)
        current_weights = {}
        total = state.cash + sum(_ticker_value(t) for t in tickers)
        for t in tickers:
            current_weights[t] = _ticker_value(t) / total if total > 0 else 0.0

        # Rolling KPIs
        ret_series = pd.Series(daily_returns)
        rs = _rolling_sharpe(ret_series, params.sharpe_window)
        rv = _rolling_vol(ret_series, 30)

        state.history.append(
            _Snapshot(
                date=date,
                portfolio_value=portfolio_value,
                cash=state.cash,
                drawdown=drawdown,
                hwm=state.hwm,
                daily_return=daily_ret,
                rolling_sharpe=rs,
                rolling_vol=rv,
                positions={t: state.positions.get(t, 0.0) for t in tickers},
                weights=current_weights,
            )
        )

        prev_signals = dict(today_signals)
        prev_value = portfolio_value

    return state, price_data, warnings


def _record_snapshot(
    state: _SimState,
    date: pd.Timestamp,
    portfolio_value: float,
    drawdown: float,
    daily_returns: list[float],
    all_returns: list[float],
    params: SimulatorParams,
    tickers: list[str],
) -> None:
    """Helper for circuit-breaker exit."""
    ret_series = pd.Series(all_returns)
    rs = _rolling_sharpe(ret_series, params.sharpe_window)
    rv = _rolling_vol(ret_series, 30)
    state.history.append(
        _Snapshot(
            date=date,
            portfolio_value=portfolio_value,
            cash=state.cash,
            drawdown=drawdown,
            hwm=state.hwm,
            daily_return=daily_returns[-1] if daily_returns else 0.0,
            rolling_sharpe=rs,
            rolling_vol=rv,
            positions={t: state.positions.get(t, 0.0) for t in tickers},
            weights={t: 0.0 for t in tickers},
        )
    )


# ─── Result aggregation ───────────────────────────────────────────────────────


def _fig_json(fig: go.Figure) -> dict[str, Any]:
    return json.loads(fig.to_json())


# ── Event aggregation (used by multiple charts) ────────────────────────────────

_TRIGGER_CFG: dict[str, dict] = {
    "init":            {"label": "Initialise",     "colour": "#78909C", "symbol": "diamond",       "size": 9},
    "signal_change":   {"label": "Signal Change",  "colour": "#1B5E20", "symbol": "triangle-up",   "size": 11},
    "rebalance":       {"label": "Rebalance",       "colour": "#E65100", "symbol": "circle",         "size": 9},
    "circuit_breaker": {"label": "Circuit Breaker", "colour": "#B71C1C", "symbol": "x",             "size": 14},
}


def _collect_events(
    trades: list[_Trade],
    history: list[_Snapshot],
) -> list[dict[str, Any]]:
    """Aggregate trades into per-day event dicts with snapshot weights attached."""
    snapshot_by_date = {s.date: s for s in history}
    by_date: dict[pd.Timestamp, dict[str, Any]] = {}

    for trade in trades:
        d = trade.date
        if d not in by_date:
            snap = snapshot_by_date.get(d)
            by_date[d] = {
                "date": d,
                "trigger": trade.trigger,
                "buy_val": 0.0,
                "sell_val": 0.0,
                "buys": [],    # list of (ticker, value)
                "sells": [],   # list of (ticker, value)
                "portfolio_value": snap.portfolio_value if snap else None,
                "weights": snap.weights if snap else {},
            }
        ev = by_date[d]
        # circuit_breaker wins over other triggers
        if trade.trigger == "circuit_breaker":
            ev["trigger"] = "circuit_breaker"
        if trade.action == "BUY":
            ev["buy_val"] += trade.value
            ev["buys"].append((trade.ticker, trade.value))
        else:
            ev["sell_val"] += trade.value
            ev["sells"].append((trade.ticker, trade.value))

    return sorted(by_date.values(), key=lambda e: e["date"])


def _event_hover_text(ev: dict[str, Any]) -> str:
    trigger_label = _TRIGGER_CFG.get(ev["trigger"], {}).get("label", ev["trigger"])
    lines = [f"<b>{trigger_label}</b>  {ev['date'].strftime('%Y-%m-%d')}"]
    if ev["buys"]:
        buy_parts = ", ".join(f"{t} ${v:,.0f}" for t, v in sorted(ev["buys"]))
        lines.append(f"BUY  {buy_parts}")
    if ev["sells"]:
        sell_parts = ", ".join(f"{t} ${v:,.0f}" for t, v in sorted(ev["sells"]))
        lines.append(f"SELL {sell_parts}")
    if ev["weights"]:
        wt_parts = " | ".join(
            f"{t} {w*100:.1f}%"
            for t, w in sorted(ev["weights"].items(), key=lambda x: -x[1])
            if w > 0.001
        )
        lines.append(f"Weights → {wt_parts}")
    return "<br>".join(lines)


def _add_event_markers(
    fig: go.Figure,
    events: list[dict[str, Any]],
    row: int = 1,
    col: int = 1,
    use_subplots: bool = False,
) -> None:
    """Add one scatter trace per trigger type (markers only) onto an existing figure."""
    by_trigger: dict[str, list[dict[str, Any]]] = {}
    for ev in events:
        by_trigger.setdefault(ev["trigger"], []).append(ev)

    for trigger, evs in by_trigger.items():
        cfg = _TRIGGER_CFG.get(trigger, _TRIGGER_CFG["rebalance"])
        xs = [e["date"] for e in evs]
        ys = [e["portfolio_value"] for e in evs]
        texts = [_event_hover_text(e) for e in evs]

        trace = go.Scatter(
            x=xs, y=ys,
            mode="markers",
            name=cfg["label"],
            marker=dict(
                color=cfg["colour"],
                symbol=cfg["symbol"],
                size=cfg["size"],
                line=dict(color="white", width=1),
            ),
            text=texts,
            hovertemplate="%{text}<extra></extra>",
            showlegend=True,
        )
        if use_subplots:
            fig.add_trace(trace, row=row, col=col)
        else:
            fig.add_trace(trace)


def _build_equity_chart(
    history: list[_Snapshot],
    initial_capital: float,
    price_data: dict[str, pd.DataFrame],
    tickers: list[str],
    date_start: date,
    date_end: date,
    trades: list[_Trade],
) -> dict[str, Any]:
    dates = [s.date for s in history]
    values = [s.portfolio_value for s in history]
    events = _collect_events(trades, history)

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=dates, y=values,
            name="Portfolio",
            line=dict(color="#1565C0", width=2),
            hovertemplate="%{x|%Y-%m-%d}<br>$%{y:,.0f}<extra>Portfolio</extra>",
        )
    )

    # Benchmark: equal-weight buy-and-hold (invest capital/N at start, never trade)
    bm_values = _compute_benchmark(price_data, tickers, initial_capital, dates)
    if bm_values is not None:
        fig.add_trace(
            go.Scatter(
                x=dates, y=bm_values,
                name="Benchmark (B&H equal-weight)",
                line=dict(color="#78909C", width=1.2, dash="dash"),
                hovertemplate="%{x|%Y-%m-%d}<br>$%{y:,.0f}<extra>Benchmark</extra>",
            )
        )

    # Trade event markers
    _add_event_markers(fig, events)

    # Initial capital reference
    fig.add_hline(
        y=initial_capital, line_dash="dot", line_color="#9E9E9E", line_width=0.8,
        annotation_text=f"Initial ${initial_capital:,.0f}", annotation_position="right",
    )
    fig.update_layout(
        title="Portfolio Equity Curve — with trade events",
        yaxis_title="Portfolio Value ($)",
        height=460, hovermode="closest", template="plotly_white",
        legend=dict(orientation="h", y=1.04), margin=dict(t=50, b=20),
    )
    return _fig_json(fig)


def _compute_benchmark(
    price_data: dict[str, pd.DataFrame],
    tickers: list[str],
    initial_capital: float,
    dates: list[pd.Timestamp],
) -> list[float] | None:
    if not tickers or not dates:
        return None
    n = len(tickers)
    alloc = initial_capital / n
    shares_at_start: dict[str, float] = {}
    start_date = dates[0]
    for t in tickers:
        df = price_data[t]
        avail = df.loc[:start_date]
        if avail.empty:
            continue
        p0 = float(avail["Close"].iloc[-1])
        if p0 > 0:
            shares_at_start[t] = alloc / p0
    if not shares_at_start:
        return None
    bm_vals = []
    for dt in dates:
        v = 0.0
        for t, sh in shares_at_start.items():
            df = price_data[t]
            if dt in df.index:
                v += sh * float(df.loc[dt, "Close"])
            else:
                latest = df.loc[:dt]
                if not latest.empty:
                    v += sh * float(latest["Close"].iloc[-1])
        bm_vals.append(v)
    return bm_vals


def _build_drawdown_chart(history: list[_Snapshot]) -> dict[str, Any]:
    dates = [s.date for s in history]
    dds = [s.drawdown * 100 for s in history]
    hwms = [s.hwm for s in history]

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                        row_heights=[0.65, 0.35], vertical_spacing=0.06)

    # Equity + HWM on row 1
    values = [s.portfolio_value for s in history]
    fig.add_trace(
        go.Scatter(x=dates, y=values, name="Portfolio", line=dict(color="#1565C0", width=1.5)),
        row=1, col=1,
    )
    fig.add_trace(
        go.Scatter(x=dates, y=hwms, name="High Water Mark",
                   line=dict(color="#2E7D32", width=1, dash="dash")),
        row=1, col=1,
    )

    # Drawdown on row 2
    fig.add_trace(
        go.Scatter(
            x=dates, y=dds, name="Drawdown (%)",
            fill="tozeroy", fillcolor="rgba(198,40,40,0.15)",
            line=dict(color="#B71C1C", width=1),
        ),
        row=2, col=1,
    )
    fig.add_hline(y=-10, line_dash="dot", line_color="#E65100", line_width=0.8,
                  annotation_text="−10%", annotation_position="left", row=2, col=1)
    fig.add_hline(y=-20, line_dash="dot", line_color="#B71C1C", line_width=0.8,
                  annotation_text="−20%", annotation_position="left", row=2, col=1)

    fig.update_yaxes(title_text="Value ($)", row=1, col=1)
    fig.update_yaxes(title_text="Drawdown (%)", row=2, col=1)
    fig.update_layout(
        title="Drawdown Analysis — Portfolio vs High Water Mark",
        height=500, hovermode="x unified", template="plotly_white",
        legend=dict(orientation="h", y=1.03), margin=dict(t=50, b=20),
    )
    return _fig_json(fig)


def _build_kpi_chart(history: list[_Snapshot]) -> dict[str, Any]:
    dates = [s.date for s in history]
    sharpes = [s.rolling_sharpe for s in history]
    vols = [s.rolling_vol * 100 for s in history]  # → percent

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                        row_heights=[0.5, 0.5], vertical_spacing=0.06)
    fig.add_trace(
        go.Scatter(x=dates, y=sharpes, name="Rolling Sharpe",
                   line=dict(color="#1565C0", width=1.5)),
        row=1, col=1,
    )
    fig.add_hline(y=0, line_dash="dash", line_color="#9E9E9E", line_width=0.8, row=1, col=1)
    fig.add_hline(y=0.5, line_dash="dot", line_color="#2E7D32", line_width=0.8,
                  annotation_text="0.5", annotation_position="right", row=1, col=1)

    fig.add_trace(
        go.Scatter(x=dates, y=vols, name="Rolling Ann. Vol (%)",
                   line=dict(color="#E65100", width=1.5),
                   fill="tozeroy", fillcolor="rgba(230,81,0,0.08)"),
        row=2, col=1,
    )

    fig.update_yaxes(title_text="Sharpe", row=1, col=1)
    fig.update_yaxes(title_text="Ann. Vol (%)", row=2, col=1)
    fig.update_layout(
        title="Rolling KPIs (Sharpe window + 30-day Volatility)",
        height=460, hovermode="x unified", template="plotly_white",
        legend=dict(orientation="h", y=1.04), margin=dict(t=50, b=20),
    )
    return _fig_json(fig)


_TICKER_COLOURS = [
    "#1565C0", "#B71C1C", "#2E7D32", "#E65100",
    "#6A1B9A", "#00695C", "#37474F", "#AD1457",
    "#0277BD", "#558B2F",
]


def _build_weights_chart(
    history: list[_Snapshot],
    tickers: list[str],
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    dates = [s.date for s in history]
    fig = go.Figure()
    for i, ticker in enumerate(tickers):
        weights = [s.weights.get(ticker, 0.0) * 100 for s in history]
        fig.add_trace(
            go.Scatter(
                x=dates, y=weights, name=ticker,
                stackgroup="one",
                line=dict(color=_TICKER_COLOURS[i % len(_TICKER_COLOURS)], width=0.5),
                hovertemplate=f"{ticker}: %{{y:.1f}}%<extra></extra>",
            )
        )

    # Vertical lines at each trade event
    for ev in events:
        cfg = _TRIGGER_CFG.get(ev["trigger"], _TRIGGER_CFG["rebalance"])
        fig.add_vline(
            x=ev["date"],
            line_dash="dot",
            line_color=cfg["colour"],
            line_width=1,
            opacity=0.5,
        )

    fig.update_layout(
        title="Position Weights Over Time — vertical lines = trade events",
        yaxis_title="Weight (%)", yaxis_range=[0, 100],
        height=380, hovermode="x unified", template="plotly_white",
        legend=dict(orientation="h", y=1.04), margin=dict(t=50, b=20),
    )
    return _fig_json(fig)


def _build_rebalance_chart(
    events: list[dict[str, Any]],
    tickers: list[str],
) -> dict[str, Any]:
    """Stacked bar chart showing target weight allocations at each trade event."""
    # Only include events that actually changed weights (exclude no-op days)
    ev_list = [e for e in events if e["weights"]]
    if not ev_list:
        return _fig_json(go.Figure())

    event_dates = [e["date"] for e in ev_list]
    trigger_labels = [
        _TRIGGER_CFG.get(e["trigger"], {}).get("label", e["trigger"])
        for e in ev_list
    ]
    # Format x-axis labels: "2024-03-15 (Signal Change)"
    x_labels = [
        f"{d.strftime('%Y-%m-%d')}<br>({t})"
        for d, t in zip(event_dates, trigger_labels)
    ]

    fig = go.Figure()
    for i, ticker in enumerate(tickers):
        weights = [e["weights"].get(ticker, 0.0) * 100 for e in ev_list]
        buy_vals = [
            sum(v for t, v in e["buys"] if t == ticker) for e in ev_list
        ]
        sell_vals = [
            sum(v for t, v in e["sells"] if t == ticker) for e in ev_list
        ]
        hover_texts = [
            (
                f"<b>{ticker}</b>  {w:.1f}%<br>"
                f"{'BUY $' + f'{bv:,.0f}' if bv > 0 else ''}"
                f"{'  SELL $' + f'{sv:,.0f}' if sv > 0 else ''}<br>"
                f"{tl} — {d.strftime('%Y-%m-%d')}"
            )
            for w, bv, sv, d, tl in zip(
                weights, buy_vals, sell_vals, event_dates, trigger_labels
            )
        ]
        fig.add_trace(
            go.Bar(
                x=x_labels,
                y=weights,
                name=ticker,
                marker_color=_TICKER_COLOURS[i % len(_TICKER_COLOURS)],
                text=[f"{w:.0f}%" if w >= 3 else "" for w in weights],
                textposition="inside",
                textfont=dict(size=9, color="white"),
                hovertemplate="%{customdata}<extra></extra>",
                customdata=hover_texts,
            )
        )

    # Colour-code the x-axis tick background via annotations (unavailable in Plotly),
    # so instead add marker symbols at y=100 to show the trigger type
    for ev, xl in zip(ev_list, x_labels):
        cfg = _TRIGGER_CFG.get(ev["trigger"], _TRIGGER_CFG["rebalance"])
        # Cash proportion annotation
        cash_pct = max(0.0, 100.0 - sum(ev["weights"].get(t, 0.0) * 100 for t in tickers))
        if cash_pct > 0.5:
            fig.add_annotation(
                x=xl, y=100, text=f"Cash {cash_pct:.0f}%",
                showarrow=False, font=dict(size=8, color="#78909C"),
                yanchor="bottom", xanchor="center",
            )

    fig.update_layout(
        title="Target Weights at Each Trade Event",
        barmode="stack",
        yaxis_title="Allocation (%)",
        yaxis_range=[0, 108],
        height=420,
        template="plotly_white",
        legend=dict(orientation="h", y=1.04),
        margin=dict(t=50, b=80),
        xaxis=dict(tickangle=-35, tickfont=dict(size=9)),
    )
    return _fig_json(fig)


def _build_trade_table(trades: list[_Trade]) -> TableSpec:
    rows = [
        {
            "date":    t.date.strftime("%Y-%m-%d"),
            "ticker":  t.ticker,
            "action":  t.action,
            "shares":  f"{t.shares:.2f}",
            "price":   f"${t.price:,.2f}",
            "value":   f"${t.value:,.0f}",
            "tc_cost": f"${t.tc_cost:,.2f}",
            "trigger": t.trigger,
        }
        for t in trades
    ]
    return TableSpec(
        id="trade-log",
        title=f"Trade Log — {len(trades)} trades",
        description="Every order executed during the simulation.",
        columns=[
            ColumnSpec(key="date",    label="Date",    format="text"),
            ColumnSpec(key="ticker",  label="Ticker",  format="text"),
            ColumnSpec(key="action",  label="Action",  format="text"),
            ColumnSpec(key="shares",  label="Shares",  format="text", align="right"),
            ColumnSpec(key="price",   label="Price",   format="text", align="right"),
            ColumnSpec(key="value",   label="Value",   format="text", align="right"),
            ColumnSpec(key="tc_cost", label="TC Cost", format="text", align="right"),
            ColumnSpec(key="trigger", label="Trigger", format="text"),
        ],
        rows=rows,
    )


# ─── Final metric calculations ─────────────────────────────────────────────────


def _final_metrics(history: list[_Snapshot], initial_capital: float) -> dict[str, float]:
    if not history:
        return {}
    final_val = history[-1].portfolio_value
    total_ret = (final_val - initial_capital) / initial_capital

    daily_rets = pd.Series([s.daily_return for s in history]).dropna()
    n_days = len(daily_rets)
    ann_ret = (1 + total_ret) ** (252 / n_days) - 1 if n_days > 10 else 0.0
    ann_vol = float(daily_rets.std() * np.sqrt(252)) if len(daily_rets) > 1 else 0.0
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0.0
    neg = daily_rets[daily_rets < 0]
    sor_den = float(neg.std() * np.sqrt(252)) if len(neg) > 1 else 0.0
    sortino = ann_ret / sor_den if sor_den > 0 else 0.0
    max_dd = float(min(s.drawdown for s in history))

    return dict(
        total_ret=total_ret,
        ann_ret=ann_ret,
        ann_vol=ann_vol,
        sharpe=sharpe,
        sortino=sortino,
        max_dd=max_dd,
        final_val=final_val,
        n_trades=0,  # filled by caller
    )


# ─── Public entry point ────────────────────────────────────────────────────────


def build_result(params: SimulatorParams) -> StrategyResult:
    """Run the simulation and return a StrategyResult for the frontend."""
    state, price_data, warnings = run_simulation(params)
    history = state.history
    tickers = [t.upper().strip() for t in params.tickers if t.strip()]
    tickers = [t for t in dict.fromkeys(tickers) if t in price_data]

    if not history:
        return StrategyResult(
            overview_md="**Simulation Engine** — no history produced.",
            warnings=warnings,
            tabs=[],
        )

    metrics_dict = _final_metrics(history, params.initial_capital)
    metrics_dict["n_trades"] = float(len(state.trades))

    global_metrics = [
        Metric(key="final_val",  label="Final Value",    value=metrics_dict["final_val"],  format="number"),
        Metric(key="total_ret",  label="Total Return",   value=metrics_dict["total_ret"],   format="percent"),
        Metric(key="ann_ret",    label="Ann. Return",    value=metrics_dict["ann_ret"],     format="percent"),
        Metric(key="ann_vol",    label="Ann. Vol",       value=metrics_dict["ann_vol"],     format="percent"),
        Metric(key="sharpe",     label="Sharpe",         value=metrics_dict["sharpe"],      format="ratio"),
        Metric(key="sortino",    label="Sortino",        value=metrics_dict["sortino"],     format="ratio"),
        Metric(key="max_dd",     label="Max Drawdown",   value=metrics_dict["max_dd"],      format="percent"),
        Metric(key="n_trades",   label="Trades",         value=metrics_dict["n_trades"],    format="number"),
    ]

    weighting_label = "Inverse Volatility" if params.weighting == "inv_vol" else "Equal Weight"
    systems_desc = ", ".join(
        f"**{t}** → {params.ticker_systems.get(t, params.default_system)}"
        for t in tickers
    )
    circuit_note = (
        f"\n\n> ⚠️ **Circuit breaker triggered** on {state.circuit_breaker_date.date()}."
        if state.circuit_breaker_triggered
        else ""
    )

    overview_md = f"""\
**Simulation Engine** — systematic trend-following simulation on live market data.

| Parameter | Value |
|-----------|-------|
| Tickers | {', '.join(tickers)} |
| Period | {params.date_start} → {params.date_end} |
| Initial Capital | ${params.initial_capital:,.0f} |
| Weighting | {weighting_label} |
| TC | {params.tc_bps:g} bps/trade |
| Max DD Limit | {params.max_drawdown_limit:.0%} |
| Conc. Cap | {params.concentration_cap:.0%} |

**Systems:** {systems_desc}{circuit_note}
"""

    # ── Pre-compute events once (reused across charts) ─────────────────────
    events = _collect_events(state.trades, history)

    # ── Charts ─────────────────────────────────────────────────────────────
    equity_chart = ChartSpec(
        id="equity-curve",
        title="Portfolio Equity Curve",
        description=(
            "Solid blue = simulated portfolio. Dashed grey = equal-weight buy-and-hold benchmark. "
            f"Markers = trade events: **green triangle** signal change · **orange circle** rebalance · **red X** circuit-breaker. "
            f"Hover a marker for the full order breakdown and resulting weights."
        ),
        guide_md="""\
**What this shows:** how the portfolio's cash value grows (or shrinks) over time, compared
to a simple buy-and-hold of the same tickers in equal weight.

A strategy that beats the benchmark line earns its trading costs. Periods where the
simulator is below the benchmark but above the initial capital line still represent profit
— just not relative outperformance.

**Trade event markers** sit on the equity curve at the exact portfolio value when each event fired:
- **Green triangle** — signal changed (MA crossover / breakout flip)
- **Orange circle** — periodic rebalance (weight drift correction every N days)
- **Red X** — circuit-breaker (all positions liquidated)
- **Grey diamond** — portfolio initialised

Hover any marker for: date · trigger type · buy/sell orders with values · resulting weights.

**Cash drag:** when all signals are neutral (flat), the portfolio sits 100% in cash and
the equity curve is flat. That's intentional — the system only allocates when it has
conviction.
""",
        figure=_build_equity_chart(
            history, params.initial_capital, price_data, tickers,
            params.date_start, params.date_end, state.trades,
        ),
    )

    rebalance_chart = ChartSpec(
        id="rebalance-weights",
        title="Target Weights at Each Trade Event",
        description=(
            "Stacked bars show the portfolio allocation computed at each signal change, "
            "periodic rebalance, or circuit-breaker event. Cash = unallocated portion (no active signal). "
            "Hover a bar segment for the buy/sell order that caused the shift."
        ),
        figure=_build_rebalance_chart(events, tickers),
    )

    drawdown_chart = ChartSpec(
        id="drawdown",
        title="Drawdown vs High Water Mark",
        description=(
            "Upper panel: portfolio value + HWM (dashed green). "
            f"Lower panel: drawdown %. Circuit-breaker limit: −{params.max_drawdown_limit:.0%}."
        ),
        guide_md="""\
**High Water Mark (HWM):** the maximum portfolio value ever achieved. The drawdown is
always measured from this peak, not from the starting capital.

**−10% / −20% lines:** institutional clients typically start getting uncomfortable below
−10%. Redemptions accelerate below −20%. The circuit-breaker fires at your configured
limit and liquidates everything to cash.

**Recovery:** after a drawdown, the portfolio must surpass the previous HWM before the
drawdown counter resets to 0.
""",
        figure=_build_drawdown_chart(history),
    )

    kpi_chart = ChartSpec(
        id="rolling-kpis",
        title="Rolling Sharpe & Volatility",
        description=(
            f"Rolling Sharpe ({params.sharpe_window}-day window, annualised). "
            "Rolling 30-day annualised volatility."
        ),
        guide_md="""\
**Rolling Sharpe:** calculated on the last N daily returns, annualised by ×√252.
A Sharpe above **0.5** is strong for a systematic strategy. When Sharpe dips negative,
the strategy is losing money faster than its volatility justifies.

**Rolling Volatility:** standard deviation of the last 30 daily returns, annualised.
Rising vol during drawdowns is typical — a high-vol, low-return period is the worst
combination for Sharpe.

**What to look for:** regimes where Sharpe stays persistently above 0 are the strategy's
"good years." Periods where it oscillates around 0 with high vol are choppy, costly
markets where trend-following tends to underperform.
""",
        figure=_build_kpi_chart(history),
    )

    weights_chart = ChartSpec(
        id="weights",
        title="Position Weights Over Time",
        description=(
            "Stacked area = % of portfolio in each ticker. "
            "White gap = cash (no active signals or post circuit-breaker). "
            "Dotted vertical lines = trade events (green = signal change, orange = rebalance, red = circuit-breaker)."
        ),
        figure=_build_weights_chart(history, tickers, events),
    )

    tab_performance = TabSpec(
        id="performance",
        title="Equity",
        icon="📈",
        intro_md=(
            "The simulated portfolio equity curve versus a buy-and-hold benchmark. "
            "Markers on the curve show every trade event — hover for full order details and resulting weights. "
            "The rebalance chart below shows the exact target allocation computed at each event."
        ),
        charts=[equity_chart, rebalance_chart],
    )

    tab_drawdown = TabSpec(
        id="drawdown",
        title="Drawdown",
        icon="📉",
        intro_md=(
            "Drawdown analysis with High Water Mark tracking. "
            f"Circuit-breaker fires at −{params.max_drawdown_limit:.0%}."
        ),
        charts=[drawdown_chart],
    )

    tab_kpis = TabSpec(
        id="kpis",
        title="Rolling KPIs",
        icon="📊",
        intro_md=(
            f"Rolling {params.sharpe_window}-day Sharpe ratio and 30-day annualised volatility. "
            "Watch how these metrics evolve through different market regimes."
        ),
        charts=[kpi_chart, weights_chart],
    )

    tab_trades = TabSpec(
        id="trades",
        title="Trade Log",
        icon="🗒️",
        intro_md=(
            f"Every order executed during the simulation. "
            f"**{len(state.trades)} trades** total. "
            f"TC: {params.tc_bps:g} bps per trade."
        ),
        tables=[_build_trade_table(state.trades)],
    )

    if state.circuit_breaker_triggered:
        warnings.insert(0, "Simulation ended early — see circuit-breaker note above.")

    return StrategyResult(
        overview_md=overview_md,
        metrics=global_metrics,
        tabs=[tab_performance, tab_drawdown, tab_kpis, tab_trades],
        warnings=warnings,
    )
