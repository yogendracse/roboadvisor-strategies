"""Live Signals computation service.

Reuses core functions from vol_analysis and trend_following — no new computation
logic, just calls existing pipeline helpers and wraps results as Plotly figures.
Same default parameters as the strategy learning versions for consistency.
"""

from __future__ import annotations

import json
from datetime import date

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from app.core.palette import PALETTE
from app.schemas.live import LiveComputeResult
from app.strategies.trend_following import (
    SYSTEMS,
    _breakout_signal,
    _ma,
    _ma_signal,
)
from app.strategies.vol_analysis import _build_pipeline

# ── Default params (same as strategy learning defaults) ───────────────────────

VOL_WINDOW = 20
VOL_NORM_WIN = 250
VOL_N_QUANTILES = 5

_QUINTILE_COLOURS = ["#1B5E20", "#558B2F", "#F9A825", "#E65100", "#B71C1C"]
_QUINTILE_LABELS = {
    1: "Q1 — Low Vol",
    2: "Q2 — Below Avg",
    3: "Q3 — Average",
    4: "Q4 — Above Avg",
    5: "Q5 — High Vol",
}


def _fig_json(fig: go.Figure) -> dict:
    return json.loads(fig.to_json())


# ── MA overlay traces ─────────────────────────────────────────────────────────


def _ma_overlay_traces(
    price_full: pd.Series,
    ds: pd.Timestamp,
    de: pd.Timestamp,
    system_name: str,
) -> list:
    """Return Plotly Scatter traces for MA lines (or breakout levels) to overlay on the price chart."""
    for sname, fast, slow in SYSTEMS:
        if sname != system_name:
            continue
        if sname == "30-Day Breakout":
            hi = price_full.rolling(30).max().shift(1)
            lo = price_full.rolling(30).min().shift(1)
            hi_d = hi.loc[ds:de]
            lo_d = lo.loc[ds:de]
            return [
                go.Scatter(
                    x=hi_d.index, y=hi_d, name="30d High", mode="lines",
                    line=dict(color="#7B1FA2", width=1, dash="dot"),
                    hovertemplate="30d High: %{y:.2f}<extra></extra>",
                ),
                go.Scatter(
                    x=lo_d.index, y=lo_d, name="30d Low", mode="lines",
                    line=dict(color="#7B1FA2", width=1, dash="dash"),
                    hovertemplate="30d Low: %{y:.2f}<extra></extra>",
                ),
            ]
        else:
            fast_ma = _ma(price_full, fast, use_ema=False).loc[ds:de]
            slow_ma = _ma(price_full, slow, use_ema=False).loc[ds:de]
            return [
                go.Scatter(
                    x=fast_ma.index, y=fast_ma, name=f"{fast}d MA", mode="lines",
                    line=dict(color=PALETTE["orange"], width=1, dash="dash"),
                    hovertemplate=f"{fast}d MA: %{{y:.2f}}<extra></extra>",
                ),
                go.Scatter(
                    x=slow_ma.index, y=slow_ma, name=f"{slow}d MA", mode="lines",
                    line=dict(color="#7B1FA2", width=1, dash="dot"),
                    hovertemplate=f"{slow}d MA: %{{y:.2f}}<extra></extra>",
                ),
            ]
    return []


# ── Price chart ───────────────────────────────────────────────────────────────


def _price_figure(
    df: pd.DataFrame,
    label: str,
    ma_traces: list | None = None,
) -> dict:
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=df["Date"],
            y=df["Close"],
            name="Price",
            line=dict(color=PALETTE["price"], width=1.5),
            fill="tozeroy",
            fillcolor="rgba(21,101,192,0.07)",
        )
    )
    for trace in (ma_traces or []):
        fig.add_trace(trace)
    fig.update_layout(
        title=f"{label} — Price",
        yaxis_title="Price",
        height=320,
        hovermode="x unified",
        template="plotly_white",
        margin=dict(t=40, b=10),
        xaxis=dict(type="date"),
        legend=dict(orientation="h", y=1.12, x=0, font=dict(size=10)),
    )
    return _fig_json(fig)


# ── Volatility indicator chart ────────────────────────────────────────────────


def _vol_figure(df_clean: pd.DataFrame) -> dict:
    if df_clean.empty:
        return _fig_json(go.Figure())

    fig = go.Figure()

    # Faint background line
    fig.add_trace(
        go.Scatter(
            x=df_clean["Date"],
            y=df_clean["zvol20"],
            mode="lines",
            line=dict(color="rgba(100,100,100,0.18)", width=1),
            showlegend=False,
            hoverinfo="skip",
        )
    )

    # Colored markers per quintile
    for q in range(1, VOL_N_QUANTILES + 1):
        mask = df_clean["quintile"] == q
        if not mask.any():
            continue
        fig.add_trace(
            go.Scatter(
                x=df_clean.loc[mask, "Date"],
                y=df_clean.loc[mask, "zvol20"],
                mode="markers",
                name=f"Q{q}",
                marker=dict(color=_QUINTILE_COLOURS[q - 1], size=4, opacity=0.85),
                hovertemplate=f"Q{q} · zvol20: %{{y:.3f}}<extra></extra>",
            )
        )

    # Current value — large marker
    last = df_clean.iloc[-1]
    q_val = int(last["quintile"])
    fig.add_trace(
        go.Scatter(
            x=[last["Date"]],
            y=[last["zvol20"]],
            mode="markers",
            name="Now",
            marker=dict(
                color=_QUINTILE_COLOURS[q_val - 1],
                size=14,
                symbol="circle",
                line=dict(width=2, color="white"),
            ),
            hovertemplate=f"Now: Q{q_val} · zvol20: %{{y:.3f}}<extra></extra>",
        )
    )

    fig.add_hline(y=0, line_dash="dash", line_color=PALETTE["grid"], line_width=0.7)

    fig.update_layout(
        title="Volatility Regime (zvol20 Z-score, coloured by quintile)",
        yaxis_title="zvol20",
        height=220,
        hovermode="x unified",
        template="plotly_white",
        margin=dict(t=40, b=10),
        xaxis=dict(type="date"),
        legend=dict(orientation="h", y=1.18, x=0, font=dict(size=10)),
    )
    return _fig_json(fig)


# ── Trend indicator chart ─────────────────────────────────────────────────────


def _trend_figure(sig: pd.Series, system_name: str) -> dict:
    sig = sig.dropna()
    if sig.empty:
        return _fig_json(go.Figure())

    fig = go.Figure()

    # Signal step line
    fig.add_trace(
        go.Scatter(
            x=sig.index,
            y=sig,
            mode="lines",
            line=dict(color="#37474F", width=1, shape="hv"),
            fill="tozeroy",
            fillcolor="rgba(55,71,79,0.08)",
            name=system_name,
            hovertemplate="Signal: %{y}<extra></extra>",
        )
    )

    # Coloured background rectangles per run
    buy_col = "rgba(46,125,50,0.18)"
    sell_col = "rgba(198,40,40,0.18)"
    colour_map = {1.0: buy_col, -1.0: sell_col}

    if len(sig) > 0:
        prev_val = float(sig.iloc[0])
        start_dt = sig.index[0]
        for i in range(1, len(sig)):
            curr_val = float(sig.iloc[i])
            if curr_val != prev_val:
                if prev_val in colour_map:
                    fig.add_shape(
                        type="rect",
                        xref="x", yref="y domain",
                        x0=start_dt, x1=sig.index[i],
                        y0=0, y1=1,
                        fillcolor=colour_map[prev_val],
                        layer="below", line_width=0,
                    )
                start_dt = sig.index[i]
                prev_val = curr_val
        # Close last run
        if prev_val in colour_map:
            fig.add_shape(
                type="rect",
                xref="x", yref="y domain",
                x0=start_dt, x1=sig.index[-1],
                y0=0, y1=1,
                fillcolor=colour_map[prev_val],
                layer="below", line_width=0,
            )

    fig.add_hline(y=0, line_dash="dash", line_color=PALETTE["grid"], line_width=0.7)

    fig.update_layout(
        title=f"Trend Signal — {system_name}",
        yaxis=dict(title="Signal", tickvals=[-1, 0, 1], ticktext=["Sell", "Neutral", "Buy"]),
        height=180,
        hovermode="x unified",
        template="plotly_white",
        margin=dict(t=40, b=10),
        xaxis=dict(type="date"),
        showlegend=False,
    )
    return _fig_json(fig)


# ── Main entry point ──────────────────────────────────────────────────────────


def _signal_label(signal: float) -> str:
    if signal > 0:
        return "Buy"
    if signal < 0:
        return "Sell"
    return "Neutral"


def compute_live(
    df: pd.DataFrame,
    label: str,
    instrument_id: str,
    date_start: date,
    date_end: date,
    strategies: list[str],
    active_trend_system: str = "30/100 MA",
) -> LiveComputeResult:
    warnings: list[str] = []

    ds = pd.Timestamp(date_start)
    de = pd.Timestamp(date_end)

    # Slice for display
    df_display = df[(df["Date"] >= ds) & (df["Date"] <= de)].reset_index(drop=True)
    if df_display.empty:
        return LiveComputeResult(
            instrument_id=instrument_id,
            label=label,
            price_figure=_fig_json(go.Figure()),
            warnings=["No data in the selected date range."],
        )

    # Build price_full for MA overlay (needed before price figure)
    df_sorted = df.sort_values("Date").drop_duplicates("Date").reset_index(drop=True)
    price_full = df_sorted.set_index("Date")["Close"]

    ma_traces = (
        _ma_overlay_traces(price_full, ds, de, active_trend_system)
        if "trend" in strategies
        else []
    )
    price_fig = _price_figure(df_display, label, ma_traces or None)

    vol_figure = None
    current_vol_quintile = None
    current_vol_label = None

    trend_figures: dict[str, dict] = {}
    current_trend_signals: dict[str, float] = {}
    current_trend_labels: dict[str, str] = {}

    # ── Volatility signals ─────────────────────────────────────────────────────
    if "volatility" in strategies:
        # _build_pipeline applies date_start/date_end internally; pass full df
        # so the norm window has as much history as possible
        df_raw, df_clean, _ = _build_pipeline(
            df,
            window=VOL_WINDOW,
            norm_win=VOL_NORM_WIN,
            n_quantiles=VOL_N_QUANTILES,
            date_start=date_start,
            date_end=date_end,
        )
        if df_clean.empty:
            warnings.append(
                f"Volatility: insufficient data "
                f"({len(df)} total rows; need {VOL_WINDOW + VOL_NORM_WIN}+ for signals)"
            )
        else:
            vol_figure = _vol_figure(df_clean)
            last = df_clean.iloc[-1]
            current_vol_quintile = int(last["quintile"])
            current_vol_label = _QUINTILE_LABELS.get(
                current_vol_quintile, f"Q{current_vol_quintile}"
            )

    # ── Trend signals ──────────────────────────────────────────────────────────
    if "trend" in strategies:
        for sname, fast, slow in SYSTEMS:
            if sname == "30-Day Breakout":
                sig_full = _breakout_signal(price_full, window=30)
            else:
                sig_full, _, _ = _ma_signal(price_full, fast, slow, use_ema=False)

            # Slice to display window for the chart
            sig_display = sig_full.loc[ds:de]
            trend_figures[sname] = _trend_figure(sig_display, sname)

            # Current signal = latest value on or before date_end
            sig_clipped = sig_full[sig_full.index <= de].dropna()
            if not sig_clipped.empty:
                latest = float(sig_clipped.iloc[-1])
                current_trend_signals[sname] = latest
                current_trend_labels[sname] = _signal_label(latest)

    return LiveComputeResult(
        instrument_id=instrument_id,
        label=label,
        warnings=warnings,
        price_figure=price_fig,
        vol_figure=vol_figure,
        current_vol_quintile=current_vol_quintile,
        current_vol_label=current_vol_label,
        trend_figures=trend_figures,
        current_trend_signals=current_trend_signals,
        current_trend_labels=current_trend_labels,
    )
