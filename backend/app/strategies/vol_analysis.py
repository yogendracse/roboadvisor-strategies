"""Vol Analysis strategy — ported from legacy/vol_app.py.

Single-instrument compute returns Tabs 1–5 (Raw Data → Indicators → Z-Scores →
Quintiles → Strategy). Tab 6 (multi-instrument Summary) is served via
compute_summary() which iterates the full instrument catalogue.
"""

from __future__ import annotations

import json
from datetime import date

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from pydantic import BaseModel, Field

from app.core.config import SECTORS
from app.core.palette import PALETTE, QUANTILE_COLOURS, sector_colour
from app.schemas.common import InstrumentKind
from app.schemas.results import (
    ChartSpec,
    ColumnSpec,
    Metric,
    StrategyResult,
    TableSpec,
    TabSpec,
)
from app.services import instrument_service
from app.strategies.base import BaseStrategy


def _fig_to_dict(fig: go.Figure) -> dict:
    return json.loads(fig.to_json())


# ─── Params ───────────────────────────────────────────────────────────────────


class VolAnalysisParams(BaseModel):
    instrument_id: str
    date_start: date | None = None
    date_end: date | None = None
    window: int = Field(default=20, ge=5, le=63, description="Rolling window (days)")
    norm_win: int = Field(
        default=250, ge=60, le=500, description="Z-score normalisation window (days)"
    )
    n_quantiles: int = Field(default=5, ge=3, le=10)
    long_q: int = Field(default=1, ge=1, le=10)
    short_q: int = Field(default=5, ge=1, le=10)


# ─── Pipeline & strategy compute ──────────────────────────────────────────────


def _build_pipeline(
    df_raw_full: pd.DataFrame,
    window: int,
    norm_win: int,
    n_quantiles: int,
    date_start: date | None,
    date_end: date | None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    df = df_raw_full.copy()
    if date_start is not None:
        df = df[df["Date"] >= pd.Timestamp(date_start)]
    if date_end is not None:
        df = df[df["Date"] <= pd.Timestamp(date_end)]
    df = df.reset_index(drop=True)
    df["ret1"] = df["Close"].pct_change()

    df["vol20"] = df["ret1"].rolling(window).std()
    df["ret20"] = df["Close"].pct_change(periods=window)
    df["fret20"] = df["ret20"].shift(-window)

    def rzs(s: pd.Series, w: int) -> pd.Series:
        return (s - s.rolling(w).mean()) / s.rolling(w).std(ddof=1)

    df["zvol20"] = rzs(df["vol20"], norm_win)
    df["zret20"] = rzs(df["ret20"], norm_win)
    df["zfret20"] = rzs(df["fret20"], norm_win)

    df_clean = df.dropna(
        subset=["zvol20", "zret20", "zfret20"]
    ).reset_index(drop=True)

    if df_clean.empty:
        qs = pd.DataFrame(
            columns=["quintile", "count", "avg_zvol20", "avg_zret20", "avg_zfret20"]
        )
        return df, df_clean, qs

    labels = list(range(1, n_quantiles + 1))
    df_clean["quintile"] = pd.qcut(
        df_clean["zvol20"], q=n_quantiles, labels=labels, duplicates="drop"
    ).astype(int)

    df_sorted = df_clean.sort_values("zvol20").reset_index(drop=True)
    df_sorted["quintile"] = pd.qcut(
        df_sorted["zvol20"], q=n_quantiles, labels=labels, duplicates="drop"
    ).astype(int)

    qs = (
        df_sorted.groupby("quintile", observed=True)
        .agg(
            count=("zvol20", "count"),
            avg_zvol20=("zvol20", "mean"),
            avg_zret20=("zret20", "mean"),
            avg_zfret20=("zfret20", "mean"),
        )
        .reset_index()
    )
    qs["quintile"] = qs["quintile"].astype(int)
    return df, df_clean, qs


def _run_strategy(
    df_clean: pd.DataFrame, long_q: int, short_q: int
) -> tuple[pd.DataFrame, dict[str, float]]:
    dc = df_clean.copy()
    dc["signal"] = np.where(
        dc["quintile"] == long_q, 1, np.where(dc["quintile"] == short_q, -1, 0)
    )
    dc["strat_ret"] = dc["signal"] * dc["fret20"]
    dc["bh_ret"] = dc["fret20"]
    dc["cum_strat"] = (1 + dc["strat_ret"].fillna(0)).cumprod()
    dc["cum_bh"] = (1 + dc["bh_ret"].fillna(0)).cumprod()

    active_ret = dc["strat_ret"].where(dc["signal"] != 0)
    roll_mean = active_ret.rolling(60, min_periods=20).mean() * 252
    roll_std = active_ret.rolling(60, min_periods=20).std() * np.sqrt(252)
    dc["rolling_ir"] = roll_mean / roll_std.replace(0, np.nan)

    active = dc.loc[dc["signal"] != 0, "strat_ret"]
    if len(active) < 5:
        ir = sharpe = ann_ret = ann_std = win_rate = 0.0
    else:
        ann_ret = float(active.mean() * 252)
        ann_std = float(active.std() * np.sqrt(252))
        ir = ann_ret / ann_std if ann_std else 0.0
        exc = active - 0.0
        sharpe = (
            float((exc.mean() * 252) / (exc.std() * np.sqrt(252)))
            if exc.std()
            else 0.0
        )
        win_rate = float((active > 0).mean())
    if dc["cum_strat"].empty or dc["cum_strat"].isna().all():
        max_dd = 0.0
    else:
        max_dd = float(((dc["cum_strat"] / dc["cum_strat"].cummax()) - 1).min())

    return dc, dict(
        ir=float(ir),
        sharpe=float(sharpe),
        win_rate=win_rate,
        ann_ret=ann_ret,
        ann_std=ann_std,
        max_dd=max_dd,
        n_active=int(len(active)),
    )


# ─── Narrative (markdown) ─────────────────────────────────────────────────────


_OVERVIEW_MD = """\
**Volatility Analysis — systematic mean-reversion on normalised volatility.**

The core idea: raw volatility drifts with market regimes (the 1970s were calmer than
the 1990s in absolute terms), so we **Z-score** the 20-day rolling volatility against
its own trailing history. A positive Z-score means "unusually volatile *for this era*".

The strategy buckets days into **volatility quintiles** and goes **long Q1**
(unusually calm) / **short Q5** (unusually turbulent), holding the position over the
same window used to compute vol. If high-vol days systematically precede positive
forward returns — the "vol risk premium" — the strategy extracts that premium.
"""


def _tab1_intro(df_raw: pd.DataFrame, df_clean: pd.DataFrame, burned_head: int, burned_tail: int) -> str:
    ret = df_raw["ret1"].dropna() * 100
    kurt = float(ret.kurt()) if len(ret) > 3 else 0.0
    min_d = df_raw["Date"].min().date()
    max_d = df_raw["Date"].max().date()
    return f"""\
**The starting point: price and daily returns.**

We have **{len(df_raw):,} trading days** of closing prices from **{min_d}** to **{max_d}**.
Every other calculation is built on top of one simple number — the **daily return**:

> *Daily Return = (Today's Price ÷ Yesterday's Price) − 1*

**Why does the distribution shape matter?** The **excess kurtosis** of daily returns
here is **{kurt:.1f}** — a perfectly normal distribution scores 0. A positive number means
extreme crashes (and rallies) happen *more often* than you'd expect by chance — the
"fat tails" that make normal-distribution risk models systematically understate real-world risk.

**What gets discarded ("burned")?** Later steps need a rolling window *and* a Z-score
window, so the first **{burned_head}** rows can't produce valid indicators. The last
**{burned_tail}** rows are discarded because we don't yet know their future return. This
leaves **{len(df_clean):,} clean, usable observations**.
"""


def _tab2_intro(df_raw: pd.DataFrame, window: int) -> str:
    avg_vol = float(df_raw["vol20"].dropna().mean() * 100) if df_raw["vol20"].notna().any() else 0.0
    avg_ret = float(df_raw["ret20"].dropna().mean() * 100) if df_raw["ret20"].notna().any() else 0.0
    return f"""\
**From daily returns, we build three "summary" measures over a {window}-day window.**
Each answers a different question about the market:

**1. `vol20` — How nervous is the market right now?**
The standard deviation of the last {window} daily returns. Calm markets cluster tightly
around zero; panicking markets swing wildly. Average `vol20` over the selected period:
**{avg_vol:.2f}%**. Think of it as a turbulence gauge.

**2. `ret20` — How has the market done over the past {window} days?**
Percentage change in price over the last {window} trading days. Average trailing
{window}-day return: **{avg_ret:+.2f}%**.

**3. `fret20` — How will the market do over the *next* {window} days?**
`ret20` shifted {window} days forward. On any given day, `fret20` tells you what the
return *actually turned out to be* — known only in hindsight, which is exactly why it
burns the last {window} rows and why it's so valuable for testing signals.

> **The key question of this whole analysis:** does knowing `vol20` today help predict
> `fret20` tomorrow?
"""


_TAB3_INTRO_TEMPLATE = """\
**The problem:** a "high" volatility number in 1965 means something very different from a
"high" volatility number in 1998. Market regimes shift over decades. If we compare raw
numbers across those eras we'd be mixing apples and oranges.

**The fix:** Z-score each indicator relative to the recent past.

> *Z = (Today's Value − Rolling {norm_win}d Average) ÷ Rolling {norm_win}d Std Dev*

A Z-score of **0** means "exactly average for this era". **+2** means "2 standard
deviations above recent normal — unusually high". **−1** means "1 standard deviation
below — unusually calm". After Z-scoring, `zvol20`, `zret20`, `zfret20` are directly
comparable across any time period.

**What to look for:**
- **vol20 raw vs zvol20:** the raw line drifts upward over decades; zvol20 oscillates
  around zero throughout. The Z-score catches *relative* spikes even when the absolute
  level is low.
- **Three Z-scores overlaid:** when zvol20 spikes up, zret20 almost always dips
  simultaneously — they move in opposite directions (concurrent relationship). Watch
  what zfret20 does *after* a zvol20 spike — this is the lead-lag signal that drives
  the strategy.
- **Scatter zvol20 vs zfret20:** each dot is one trading day, coloured by quintile.
  Notice the Q1 (blue) dots sitting slightly below zero and Q5 (red) dots above — that
  mean-reversion pattern is the basis for the Phase 5 trading rule.

After Z-scoring, mean of zvol20 across the clean dataset is **{zvol_mean:+.3f}** and std
is **{zvol_std:.3f}** (should be near 0 and 1 respectively — confirms the normalisation worked).
"""


def _tab4_intro(df_clean: pd.DataFrame, qs: pd.DataFrame, n_quantiles: int, window: int) -> str:
    if qs.empty:
        return "No clean observations yet — widen your date range."
    q1_ret = float(qs.loc[qs["quintile"] == 1, "avg_zret20"].iloc[0])
    qT_ret = float(qs.loc[qs["quintile"] == n_quantiles, "avg_zret20"].iloc[0])
    q1_fret = float(qs.loc[qs["quintile"] == 1, "avg_zfret20"].iloc[0])
    qT_fret = float(qs.loc[qs["quintile"] == n_quantiles, "avg_zfret20"].iloc[0])
    pct = 100 // n_quantiles
    return f"""\
**Sorting and bucketing: finding the pattern across the full history.**

All **{len(df_clean):,}** clean days sorted from calmest (lowest zvol20) to most volatile
(highest zvol20) and split into **{n_quantiles} equal-sized groups**:
- **Q1** = the calmest {pct}% of days
- **Q{n_quantiles}** = the most volatile {pct}% of days

Each bucket gets an average score for all three Z-score indicators. This strips away the
time dimension and asks: *"Across all of history, what tends to happen to returns when
volatility is at a certain relative level?"*

**Chart 1 — avg zvol20:** just confirms the bucketing worked (each bar higher than the
previous; monotone).

**Chart 2 — Concurrent zret20:** what returns looked like *at the same time* as each vol
level. Low vol (Q1) → recent returns were **good** ({q1_ret:+.3f}). High vol (Q{n_quantiles}) →
recent returns were **bad** ({qT_ret:+.3f}). Volatility spikes *because* the market is falling.

**Chart 3 — Future zfret20 (the key chart):** what returns looked like *over the next
{window} days*. The pattern **reverses**:
- Low vol (Q1) → future returns tend to be **negative** ({q1_fret:+.3f})
- High vol (Q{n_quantiles}) → future returns tend to be **positive** ({qT_fret:+.3f})

**This is the mean-reversion signal.** Periods of panic overshoot — prices fall too far,
then bounce. Periods of calm overshoot the other way — and then stall or pull back.
"""


def _tab5_intro(m: dict[str, float], long_q: int, short_q: int, window: int, n_quantiles: int) -> str:
    ir = m["ir"]
    wr = m["win_rate"]
    dd = m["max_dd"]
    ir_dot = "🟢" if ir > 0.5 else ("🟡" if ir > 0.2 else "🔴")
    wr_dot = "🟢" if wr > 0.55 else ("🟡" if wr > 0.45 else "🔴")
    dd_dot = "🟢" if dd > -0.10 else ("🟡" if dd > -0.20 else "🔴")
    return f"""\
**Turning the quintile signal into a trading rule.**

The Phase-4 findings suggest a simple rule:
- When volatility is **abnormally low** (Q{long_q}) → go **long**
- When volatility is **abnormally high** (Q{short_q}) → go **short**
- All other days → stay **flat**

Current setup: **Long Q{long_q} / Short Q{short_q}** holding for {window} days.

**What each metric tells you:**

| Metric | Current | Meaning |
|---|---|---|
| Information Ratio (IR) | {ir_dot} **{ir:.3f}** | Return per unit of risk, no risk-free rate. >0.5 strong, 0.2–0.5 moderate, <0 losing. |
| Sharpe Ratio | {ir_dot} **{m["sharpe"]:.3f}** | Same as IR when rf = 0%. |
| Ann. Return | **{m["ann_ret"]:.1%}** | Average yearly gain if traded continuously. |
| Ann. Volatility | **{m["ann_std"]:.1%}** | How much strategy returns swing year-to-year. |
| Win Rate | {wr_dot} **{wr:.1%}** | % of active trades that were profitable. |
| Max Drawdown | {dd_dot} **{dd:.1%}** | Worst peak-to-trough loss on the equity curve. |

**Reading the decade × quintile heatmap:** answers "does the pattern hold across
different eras, or did it only work in one decade?" Green cells (positive future returns)
in Q{n_quantiles} across multiple decades give confidence the signal is structural. Red cells in
Q{n_quantiles} are a warning sign.

**Things to try:** narrow the date range to a specific decade to see era-by-era IR; slide
the analysis window down to 5 days (short-term) or up to 63 days (quarterly) to see how
the holding period changes signal strength.
"""


# ─── Chart builders ───────────────────────────────────────────────────────────


def _chart_price_returns(df_raw: pd.DataFrame, label: str) -> dict:
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        row_heights=[0.65, 0.35], vertical_spacing=0.04,
    )
    fig.add_trace(
        go.Scatter(
            x=df_raw["Date"], y=df_raw["Close"], name="Close",
            line=dict(color=PALETTE["price"], width=1.2),
            fill="tozeroy", fillcolor="rgba(21,101,192,0.08)",
        ),
        row=1, col=1,
    )
    fig.add_trace(
        go.Bar(
            x=df_raw["Date"], y=df_raw["ret1"] * 100, name="Daily Ret (%)",
            marker_color=np.where(df_raw["ret1"] >= 0, PALETTE["ret1"], PALETTE["down"]),
        ),
        row=2, col=1,
    )
    fig.update_yaxes(title_text="Price", row=1, col=1)
    fig.update_yaxes(title_text="Daily Ret (%)", row=2, col=1)
    fig.update_layout(
        title=f"{label} — price & daily returns", height=500,
        margin=dict(t=50, b=20), hovermode="x unified",
        template="plotly_white", legend=dict(orientation="h", y=1.05),
    )
    return _fig_to_dict(fig)


def _chart_return_distribution(df_raw: pd.DataFrame) -> dict:
    ret = df_raw["ret1"].dropna() * 100
    fig = go.Figure()
    fig.add_trace(
        go.Histogram(
            x=ret, nbinsx=120, marker_color=PALETTE["ret1"],
            name="Daily returns", histnorm="probability density",
        )
    )
    if len(ret) > 10:
        x_n = np.linspace(float(ret.min()), float(ret.max()), 200)
        std = float(ret.std())
        mean = float(ret.mean())
        y_n = (1 / (std * np.sqrt(2 * np.pi))) * np.exp(-0.5 * ((x_n - mean) / std) ** 2)
        fig.add_trace(
            go.Scatter(
                x=x_n, y=y_n, name="Normal fit",
                line=dict(color="#F44336", dash="dash", width=2),
            )
        )
    fig.update_layout(
        title="Return Distribution vs Normal",
        xaxis_title="Daily Return (%)", yaxis_title="Density",
        height=340, template="plotly_white",
        margin=dict(t=50, b=20), legend=dict(orientation="h", y=1.05),
    )
    return _fig_to_dict(fig)


def _table_descriptive_stats(df_raw: pd.DataFrame) -> TableSpec:
    ret = df_raw["ret1"].dropna() * 100
    stats = ret.describe() if len(ret) else pd.Series(dtype=float)
    rows = [
        {"metric": "Count",        "value": f"{len(ret):,}"},
        {"metric": "Mean (%)",     "value": f"{stats.get('mean', 0):.3f}" if len(ret) else "—"},
        {"metric": "Std (%)",      "value": f"{stats.get('std', 0):.3f}" if len(ret) else "—"},
        {"metric": "Min (%)",      "value": f"{stats.get('min', 0):.3f}" if len(ret) else "—"},
        {"metric": "Max (%)",      "value": f"{stats.get('max', 0):.3f}" if len(ret) else "—"},
        {"metric": "Kurtosis",     "value": f"{ret.kurt():.3f}" if len(ret) > 3 else "—"},
        {"metric": "Skewness",     "value": f"{ret.skew():.3f}" if len(ret) > 2 else "—"},
    ]
    return TableSpec(
        id="descriptive-stats",
        title="Descriptive Statistics",
        columns=[
            ColumnSpec(key="metric", label="Metric", format="text"),
            ColumnSpec(key="value",  label="Value",  format="text", align="right"),
        ],
        rows=rows,
    )


def _chart_vol20(df_raw: pd.DataFrame) -> dict:
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=df_raw["Date"], y=df_raw["vol20"] * 100, name="vol20 (%)",
            line=dict(color=PALETTE["vol20"], width=1),
            fill="tozeroy", fillcolor="rgba(123,31,162,0.10)",
        )
    )
    fig.update_layout(
        title="Rolling Volatility (vol20)",
        yaxis_title="Volatility (%)", height=320,
        hovermode="x unified", template="plotly_white",
        margin=dict(t=50, b=20),
    )
    return _fig_to_dict(fig)


def _chart_ret20_fret20(df_raw: pd.DataFrame) -> dict:
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=df_raw["Date"], y=df_raw["ret20"] * 100,
            name="ret20 — trailing (%)",
            line=dict(color=PALETTE["ret20"], width=0.9),
        )
    )
    fig.add_trace(
        go.Scatter(
            x=df_raw["Date"], y=df_raw["fret20"] * 100,
            name="fret20 — future (%)",
            line=dict(color=PALETTE["fret20"], width=0.9, dash="dot"),
        )
    )
    fig.add_trace(
        go.Scatter(
            x=df_raw["Date"], y=df_raw["vol20"] * 100, name="vol20 (%)",
            yaxis="y2", opacity=0.55,
            line=dict(color=PALETTE["vol20"], width=0.7, dash="dash"),
        )
    )
    fig.update_layout(
        title="Historical & Future 20-Day Returns (vol20 secondary axis)",
        yaxis=dict(title="Return (%)"),
        yaxis2=dict(title="vol20 (%)", overlaying="y", side="right", showgrid=False),
        height=340, hovermode="x unified", template="plotly_white",
        legend=dict(orientation="h", y=1.05),
        margin=dict(t=50, b=20),
    )
    fig.add_hline(y=0, line_dash="dash", line_color=PALETTE["grid"], line_width=0.8)
    return _fig_to_dict(fig)


def _chart_vol_vs_zvol(df_clean: pd.DataFrame) -> dict:
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(
        go.Scatter(
            x=df_clean["Date"], y=df_clean["vol20"] * 100,
            name="vol20 (raw %)", opacity=0.45,
            line=dict(color=PALETTE["vol20"], width=0.8),
        ),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            x=df_clean["Date"], y=df_clean["zvol20"],
            name="zvol20 (Z-score)",
            line=dict(color=PALETTE["orange"], width=1.1),
        ),
        secondary_y=True,
    )
    fig.add_hline(
        y=0, line_dash="dash", line_color=PALETTE["grid"], line_width=0.7,
        secondary_y=True,
    )
    fig.update_yaxes(title_text="vol20 (%)", secondary_y=False)
    fig.update_yaxes(title_text="Z-score", secondary_y=True)
    fig.update_layout(
        title="vol20 (raw) vs zvol20 (normalised)",
        height=320, hovermode="x unified", template="plotly_white",
        legend=dict(orientation="h", y=1.05), margin=dict(t=50, b=20),
    )
    return _fig_to_dict(fig)


def _chart_zscores_overlay(df_clean: pd.DataFrame) -> dict:
    fig = go.Figure()
    for col, color, name in [
        ("zvol20", PALETTE["zvol20"], "zvol20 — normalised volatility"),
        ("zret20", PALETTE["zret20"], "zret20 — concurrent return"),
        ("zfret20", PALETTE["zfret20"], "zfret20 — future return"),
    ]:
        fig.add_trace(
            go.Scatter(
                x=df_clean["Date"], y=df_clean[col], name=name,
                line=dict(color=color, width=0.9),
            )
        )
    fig.add_hline(y=0, line_dash="dash", line_color=PALETTE["grid"], line_width=0.7)
    fig.update_layout(
        title="All three Z-scores overlaid",
        yaxis_title="Z-score", height=360,
        hovermode="x unified", template="plotly_white",
        legend=dict(orientation="h", y=1.05), margin=dict(t=50, b=20),
    )
    return _fig_to_dict(fig)


def _chart_scatter_zvol_zfret(df_clean: pd.DataFrame) -> dict:
    fig = go.Figure()
    for q in sorted(df_clean["quintile"].unique()):
        mask = df_clean["quintile"] == q
        colour = QUANTILE_COLOURS[min(int(q) - 1, len(QUANTILE_COLOURS) - 1)]
        fig.add_trace(
            go.Scatter(
                x=df_clean.loc[mask, "zvol20"],
                y=df_clean.loc[mask, "zfret20"],
                mode="markers", name=f"Q{int(q)}",
                marker=dict(color=colour, size=3, opacity=0.4),
            )
        )
    fig.add_hline(y=0, line_dash="dash", line_color=PALETTE["grid"], line_width=0.7)
    fig.add_vline(x=0, line_dash="dash", line_color=PALETTE["grid"], line_width=0.7)
    fig.update_layout(
        title="Scatter: zvol20 vs zfret20 (coloured by quintile)",
        xaxis_title="zvol20", yaxis_title="zfret20",
        height=420, template="plotly_white",
        legend=dict(orientation="h", y=1.05), margin=dict(t=50, b=20),
    )
    return _fig_to_dict(fig)


def _chart_quintile_bar(qs: pd.DataFrame, field: str, title: str) -> dict:
    if qs.empty:
        return _fig_to_dict(go.Figure())
    x_labels = [f"Q{int(q)}" for q in qs["quintile"]]
    colours = [
        QUANTILE_COLOURS[min(i, len(QUANTILE_COLOURS) - 1)]
        for i in range(len(qs))
    ]
    vals = qs[field].tolist()
    fig = go.Figure(
        go.Bar(
            x=x_labels, y=vals, marker_color=colours,
            text=[f"{v:+.3f}" for v in vals], textposition="outside",
        )
    )
    fig.add_hline(y=0, line_dash="dash", line_color=PALETTE["grid"], line_width=0.8)
    fig.update_layout(
        title=title, yaxis_title="Mean Z-score",
        height=340, template="plotly_white",
        showlegend=False, margin=dict(t=50, b=20),
    )
    return _fig_to_dict(fig)


def _table_quintile_summary(qs: pd.DataFrame) -> TableSpec:
    rows = [
        {
            "quintile": f"Q{int(row.quintile)}",
            "count": int(row.count),
            "zvol20": f"{row.avg_zvol20:+.4f}",
            "zret20": f"{row.avg_zret20:+.4f}",
            "zfret20": f"{row.avg_zfret20:+.4f}",
        }
        for row in qs.itertuples()
    ]
    return TableSpec(
        id="quintile-summary",
        title="Full Quintile Summary Table",
        columns=[
            ColumnSpec(key="quintile", label="Quintile", format="text"),
            ColumnSpec(key="count",    label="Count",    format="number", align="right"),
            ColumnSpec(key="zvol20",   label="Avg zvol20", format="text", align="right"),
            ColumnSpec(key="zret20",   label="Avg zret20 (Concurrent)", format="text", align="right"),
            ColumnSpec(key="zfret20",  label="Avg zfret20 (Future)",    format="text", align="right"),
        ],
        rows=rows,
    )


def _chart_equity(df_strat: pd.DataFrame, long_q: int, short_q: int) -> dict:
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        row_heights=[0.65, 0.35], vertical_spacing=0.06,
    )
    fig.add_trace(
        go.Scatter(
            x=df_strat["Date"], y=df_strat["cum_bh"],
            name="Buy & Hold (fret20 benchmark)",
            line=dict(color=PALETTE["bh"], width=1.2, dash="dot"),
        ),
        row=1, col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=df_strat["Date"], y=df_strat["cum_strat"],
            name=f"Strategy (Long Q{long_q} / Short Q{short_q})",
            line=dict(color=PALETTE["strat"], width=1.5),
        ),
        row=1, col=1,
    )
    fig.update_yaxes(title_text="Cumulative Wealth", row=1, col=1)
    fig.add_trace(
        go.Scatter(
            x=df_strat["Date"], y=df_strat["rolling_ir"],
            name="Rolling IR (60-obs)",
            line=dict(color=PALETTE["price"], width=1.1),
        ),
        row=2, col=1,
    )
    fig.add_hline(y=0, line_dash="dash", line_color=PALETTE["grid"], line_width=0.7, row=2, col=1)
    fig.add_hline(y=0.5, line_dash="dot", line_color=PALETTE["ret1"], line_width=0.8, row=2, col=1)
    fig.update_yaxes(title_text="Rolling IR", row=2, col=1)
    fig.update_layout(
        title="Cumulative equity & rolling IR",
        height=540, hovermode="x unified", template="plotly_white",
        legend=dict(orientation="h", y=1.04), margin=dict(t=50, b=20),
    )
    return _fig_to_dict(fig)


def _chart_strategy_return_distribution(df_strat: pd.DataFrame) -> dict:
    active = df_strat.loc[df_strat["signal"] != 0, "strat_ret"] * 100
    fig = go.Figure()
    fig.add_trace(
        go.Histogram(
            x=active, nbinsx=80, marker_color=PALETTE["strat"],
            name="Strategy returns", histnorm="probability density",
        )
    )
    if len(active) > 10:
        x_n = np.linspace(float(active.min()), float(active.max()), 200)
        mean = float(active.mean())
        std = float(active.std())
        y_n = (1 / (std * np.sqrt(2 * np.pi))) * np.exp(-0.5 * ((x_n - mean) / std) ** 2)
        fig.add_trace(
            go.Scatter(
                x=x_n, y=y_n, name="Normal fit",
                line=dict(color=PALETTE["price"], dash="dash", width=2),
            )
        )
    fig.add_vline(x=0, line_dash="dash", line_color=PALETTE["grid"])
    fig.update_layout(
        title="Strategy Return Distribution",
        xaxis_title="20-Day Return (%)", yaxis_title="Density",
        height=340, template="plotly_white",
        legend=dict(orientation="h", y=1.05), margin=dict(t=50, b=20),
    )
    return _fig_to_dict(fig)


def _chart_decade_quintile_heatmap(df_strat: pd.DataFrame) -> dict:
    if df_strat.empty or "quintile" not in df_strat:
        return _fig_to_dict(go.Figure())
    df = df_strat.copy()
    df["decade"] = (df["Date"].dt.year // 10 * 10).astype(str) + "s"
    heat = (
        df.groupby(["decade", "quintile"], observed=True)["fret20"]
        .mean()
        .unstack("quintile")
        * 100
    )
    if heat.empty:
        return _fig_to_dict(go.Figure())
    heat.columns = [f"Q{int(c)}" for c in heat.columns]
    text_vals = [
        [f"{v:.2f}%" if not np.isnan(v) else "" for v in row]
        for row in heat.values
    ]
    fig = go.Figure(
        go.Heatmap(
            z=heat.values,
            x=heat.columns.tolist(),
            y=heat.index.tolist(),
            colorscale="RdYlGn",
            zmid=0,
            text=text_vals,
            texttemplate="%{text}",
            colorbar=dict(title="Avg fret20 (%)"),
        )
    )
    fig.update_layout(
        title="Average Forward Return by Quintile × Decade",
        xaxis_title="Volatility Quintile", yaxis_title="Decade",
        height=320, template="plotly_white", margin=dict(t=50, b=20),
    )
    return _fig_to_dict(fig)


# ─── Strategy ─────────────────────────────────────────────────────────────────


class VolAnalysisStrategy(BaseStrategy):
    id = "vol-analysis"
    name = "Volatility Analysis"
    description = (
        "Mean-reversion on rolling vol z-scores. "
        "Long low-vol quantile, short high-vol quantile."
    )
    instrument_kind = InstrumentKind.vol
    ParamsModel = VolAnalysisParams
    has_summary = True

    def compute(self, params: BaseModel) -> StrategyResult:
        assert isinstance(params, VolAnalysisParams)
        instrument = instrument_service.get_instrument(
            InstrumentKind.vol, params.instrument_id
        )
        df_raw_full = instrument_service.load_instrument_frame(
            InstrumentKind.vol, params.instrument_id
        )
        df_raw, df_clean, qs = _build_pipeline(
            df_raw_full, params.window, params.norm_win, params.n_quantiles,
            params.date_start, params.date_end,
        )

        warnings: list[str] = []
        if df_clean.empty:
            warnings.append(
                "No clean observations after burn-in. Try a longer date range or smaller windows."
            )
            return StrategyResult(
                overview_md=_OVERVIEW_MD, warnings=warnings, tabs=[]
            )

        df_strat, m = _run_strategy(df_clean, params.long_q, params.short_q)
        burned_head = params.window + params.norm_win
        burned_tail = params.window

        global_metrics = [
            Metric(key="ir",       label="Info. Ratio",   value=m["ir"],       format="ratio"),
            Metric(key="sharpe",   label="Sharpe",        value=m["sharpe"],   format="ratio"),
            Metric(key="ann_ret",  label="Ann. Return",   value=m["ann_ret"],  format="percent"),
            Metric(key="ann_std",  label="Ann. Vol",      value=m["ann_std"],  format="percent"),
            Metric(key="win_rate", label="Win Rate",      value=m["win_rate"], format="percent"),
            Metric(key="max_dd",   label="Max Drawdown",  value=m["max_dd"],   format="percent"),
            Metric(key="n_active", label="Active Signals", value=m["n_active"], format="number"),
        ]

        # ── Tab 1 ──────────────────────────────────────────────────────────────
        tab1 = TabSpec(
            id="raw-data",
            title="Raw Data",
            icon="📊",
            intro_md=_tab1_intro(df_raw, df_clean, burned_head, burned_tail),
            charts=[
                ChartSpec(
                    id="price-returns",
                    title="Price & daily returns",
                    description=(
                        f"**ret1 = (Closeₜ / Closeₜ₋₁) − 1** · "
                        f"First **{burned_head}** rows burned (look-back) · "
                        f"Last **{burned_tail}** rows burned (look-ahead)."
                    ),
                    figure=_chart_price_returns(df_raw, instrument.label),
                ),
                ChartSpec(
                    id="return-distribution",
                    title="Return distribution vs Normal",
                    description=(
                        "Empirical histogram of daily returns, with a Normal fit overlaid. "
                        "Fat tails = the empirical bars at the extremes are taller than Normal predicts."
                    ),
                    figure=_chart_return_distribution(df_raw),
                ),
            ],
            tables=[_table_descriptive_stats(df_raw)],
        )

        # ── Tab 2 ──────────────────────────────────────────────────────────────
        tab2 = TabSpec(
            id="indicators",
            title="Indicators",
            icon="🔧",
            intro_md=_tab2_intro(df_raw, params.window),
            charts=[
                ChartSpec(
                    id="vol20",
                    title="Rolling Volatility (vol20)",
                    description=f"**vol20 = std(ret1, window={params.window}d)** · a 'turbulence gauge'.",
                    figure=_chart_vol20(df_raw),
                ),
                ChartSpec(
                    id="ret20-fret20",
                    title="Historical & future 20-day returns",
                    description=(
                        f"**ret20** (trailing) and **fret20** (look-ahead, shifted −{params.window}d) "
                        "plotted alongside vol20 on the right axis. "
                        "High-vol spikes typically coincide with large negative ret20."
                    ),
                    figure=_chart_ret20_fret20(df_raw),
                ),
            ],
        )

        # ── Tab 3 ──────────────────────────────────────────────────────────────
        zvol_mean = float(df_clean["zvol20"].mean())
        zvol_std = float(df_clean["zvol20"].std())
        tab3 = TabSpec(
            id="z-scores",
            title="Z-Scores",
            icon="🔁",
            intro_md=_TAB3_INTRO_TEMPLATE.format(
                norm_win=params.norm_win, zvol_mean=zvol_mean, zvol_std=zvol_std,
            ),
            charts=[
                ChartSpec(
                    id="vol-vs-zvol",
                    title="vol20 (raw) vs zvol20 (normalised)",
                    description="Dual-axis: raw vol drifts with the regime; zvol oscillates around 0.",
                    figure=_chart_vol_vs_zvol(df_clean),
                ),
                ChartSpec(
                    id="z-overlay",
                    title="All three Z-scores overlaid",
                    description=(
                        "zvol20 spikes during turmoil; zret20 dips concurrently; "
                        "zfret20 is what ret20 *will be* in the next window — the lead-lag signal."
                    ),
                    figure=_chart_zscores_overlay(df_clean),
                ),
                ChartSpec(
                    id="zvol-zfret-scatter",
                    title="Scatter: zvol20 vs zfret20 (by quintile)",
                    description=(
                        "Each dot = one trading day. Coloured by quintile. "
                        "Q1 (blue, low-vol) sits slightly below 0 on y-axis; "
                        f"Q{params.n_quantiles} (red, high-vol) sits slightly above — the mean-reversion pattern."
                    ),
                    figure=_chart_scatter_zvol_zfret(df_clean),
                ),
            ],
        )

        # ── Tab 4 ──────────────────────────────────────────────────────────────
        tab4 = TabSpec(
            id="quintiles",
            title="Quintiles",
            icon="🗂️",
            intro_md=_tab4_intro(df_clean, qs, params.n_quantiles, params.window),
            charts=[
                ChartSpec(
                    id="q-zvol",
                    title="Average zvol20 by quintile",
                    description="Sanity check — each bar should be higher than the previous.",
                    figure=_chart_quintile_bar(qs, "avg_zvol20", "Average zvol20 by Q"),
                ),
                ChartSpec(
                    id="q-zret",
                    title="Concurrent zret20 by quintile",
                    description="Co-occurring returns: high-vol = recent bad returns.",
                    figure=_chart_quintile_bar(qs, "avg_zret20", "Average zret20 (Concurrent) by Q"),
                ),
                ChartSpec(
                    id="q-zfret",
                    title="Future zfret20 by quintile (lead-lag)",
                    description="The key chart: what returns look like *after* each vol regime.",
                    figure=_chart_quintile_bar(qs, "avg_zfret20", "Average zfret20 (Future) by Q"),
                ),
            ],
            tables=[_table_quintile_summary(qs)],
        )

        # ── Tab 5 ──────────────────────────────────────────────────────────────
        tab5 = TabSpec(
            id="strategy",
            title="Strategy",
            icon="💼",
            intro_md=_tab5_intro(m, params.long_q, params.short_q, params.window, params.n_quantiles),
            charts=[
                ChartSpec(
                    id="equity-curve",
                    title="Cumulative equity & rolling IR",
                    description=(
                        f"**Long Q{params.long_q}** / **Short Q{params.short_q}** · "
                        f"Holding period = {params.window}d · Active signals: {m['n_active']:,}."
                    ),
                    figure=_chart_equity(df_strat, params.long_q, params.short_q),
                ),
                ChartSpec(
                    id="strat-distribution",
                    title="Strategy return distribution",
                    description=(
                        "Distribution of 20-day strategy returns on active-signal days only. "
                        "Compare the location (mean above 0 = positive edge) and spread (narrow = "
                        "low volatility) to the Normal fit."
                    ),
                    figure=_chart_strategy_return_distribution(df_strat),
                ),
                ChartSpec(
                    id="decade-q-heatmap",
                    title="Avg forward return by Quintile × Decade",
                    description=(
                        "Green = positive future returns, red = negative. "
                        "Consistent green in the extreme-vol quintile across decades = the signal "
                        "is structural, not a historical accident."
                    ),
                    figure=_chart_decade_quintile_heatmap(df_strat),
                ),
            ],
        )

        return StrategyResult(
            overview_md=_OVERVIEW_MD,
            metrics=global_metrics,
            tabs=[tab1, tab2, tab3, tab4, tab5],
            warnings=warnings,
        )


# ─── Tab 6 — multi-instrument summary ─────────────────────────────────────────


_SUMMARY_OVERVIEW_MD = """\
**Cross-portfolio summary — the strategy run on every instrument in your catalogue.**

For each instrument, we apply the same pipeline (rolling vol → z-scores → quintiles →
long/short rule) using the parameters from the sidebar. This tells you *which* instruments
have the strongest vol-mean-reversion edge and how performance clusters by sector.

**Caveats:**
- Every instrument uses **its own full available history** (not the date range from the
  single-instrument view) — otherwise thin overlap would penalise newer instruments.
- Instruments with fewer than 100 clean observations are surfaced in the warnings list.
"""


_TAB6_INTRO_MD = """\
**How to read this tab:**

- **Portfolio-wide KPIs** strip: averages across all instruments. Think of it as the
  "if I ran this strategy on everything" summary.
- **Metrics comparison** bars: rank instruments on each metric. Bars are coloured by
  sector to spot clusters (e.g. tech instruments with systematically higher IR).
- **Risk/Return map:** bubble size = |IR|, y-axis = annualised return, x-axis =
  annualised volatility. Top-left corner = high return, low vol = ideal.
- **Avg IR by Sector:** groups instruments by sector and averages the metrics —
  quick read on which sectors the strategy works best in.
- **Quintile Profiles by Sector:** three sub-charts showing how each sector's
  instruments behave in each volatility quintile — helps spot sector-specific
  mean-reversion patterns.
- **Decade × Quintile heatmaps per sector:** one heatmap per sector showing whether
  the vol → future-return signal is consistent across decades.
"""


def _run_one_instrument(
    label: str,
    sector: str,
    df: pd.DataFrame,
    window: int,
    norm_win: int,
    n_quantiles: int,
    long_q: int,
    short_q: int,
) -> dict:
    """Run the pipeline on one instrument's full history. Returns metrics + per-quintile + per-decade."""
    df_raw, df_clean, qs = _build_pipeline(
        df, window, norm_win, n_quantiles,
        date_start=None, date_end=None,
    )
    if df_clean.empty or len(df_clean) < 100:
        return {
            "label": label,
            "sector": sector,
            "error": f"Only {len(df_clean)} clean observations (need 100+).",
        }
    df_strat, m = _run_strategy(df_clean, long_q, short_q)

    # Per-decade fret20 average by quintile (for heatmap)
    df2 = df_strat.copy()
    df2["decade"] = (df2["Date"].dt.year // 10 * 10).astype(str) + "s"
    decade_df = (
        df2.groupby(["decade", "quintile"], observed=True)["fret20"]
        .mean()
        .reset_index()
    )
    decade_df["label"] = label
    decade_df["sector"] = sector

    qs_out = qs[["quintile", "avg_zvol20", "avg_zret20", "avg_zfret20"]].copy()
    qs_out["label"] = label
    qs_out["sector"] = sector

    date_min = df_raw["Date"].min()
    date_max = df_raw["Date"].max()

    return {
        "label": label,
        "sector": sector,
        "rows": int(len(df)),
        "clean_rows": int(len(df_clean)),
        "years": round((date_max - date_min).days / 365.25, 1),
        "ir": m["ir"],
        "sharpe": m["sharpe"],
        "ann_ret": m["ann_ret"],
        "ann_std": m["ann_std"],
        "win_rate": m["win_rate"],
        "max_dd": m["max_dd"],
        "qs_df": qs_out,
        "decade_df": decade_df,
    }


def _metric_format(metric: str) -> str:
    return ".1%" if metric in ("ann_ret", "ann_std", "win_rate", "max_dd") else ".2f"


def _chart_metric_bar(summary: pd.DataFrame, metric: str, title: str) -> dict:
    if summary.empty:
        return _fig_to_dict(go.Figure())
    asc = metric == "max_dd"
    sv = summary.sort_values(metric, ascending=asc)
    colours = [sector_colour(s) for s in sv["sector"]]
    is_pct = metric in ("ann_ret", "ann_std", "win_rate", "max_dd")
    text = [f"{v:.1%}" if is_pct else f"{v:.2f}" for v in sv[metric]]
    fig = go.Figure(
        go.Bar(
            x=sv["label"], y=sv[metric],
            marker_color=colours, text=text, textposition="outside",
            customdata=sv["sector"],
            hovertemplate="%{x}<br>Sector: %{customdata}<br>" + title + ": %{y:" + _metric_format(metric) + "}<extra></extra>",
        )
    )
    fig.add_hline(y=0, line_dash="dash", line_color=PALETTE["grid"], line_width=0.8)
    fig.update_layout(
        title=title, height=340, template="plotly_white",
        showlegend=False, margin=dict(t=50, b=40),
        yaxis=dict(tickformat=".1%" if is_pct else ".2f"),
    )
    return _fig_to_dict(fig)


def _chart_risk_return_map(summary: pd.DataFrame) -> dict:
    if summary.empty:
        return _fig_to_dict(go.Figure())
    fig = go.Figure()
    for sec in sorted(summary["sector"].unique()):
        sub = summary[summary["sector"] == sec]
        if sub.empty:
            continue
        fig.add_trace(
            go.Scatter(
                x=sub["ann_std"], y=sub["ann_ret"],
                mode="markers+text", name=sec,
                text=sub["label"], textposition="top center",
                textfont=dict(size=9),
                marker=dict(
                    size=np.clip(sub["ir"].abs() * 40, 8, 60),
                    color=sector_colour(sec),
                    opacity=0.75, line=dict(width=1, color="white"),
                ),
                hovertemplate=(
                    "<b>%{text}</b><br>Sector: " + sec +
                    "<br>Ann. Vol: %{x:.1%}<br>Ann. Return: %{y:.1%}<extra></extra>"
                ),
            )
        )
    fig.add_hline(y=0, line_dash="dash", line_color=PALETTE["grid"], line_width=0.7)
    fig.update_layout(
        title="Risk / Return map (bubble size = |IR|)",
        xaxis=dict(title="Annualised Volatility", tickformat=".0%"),
        yaxis=dict(title="Annualised Return", tickformat=".0%"),
        height=480, template="plotly_white",
        legend=dict(orientation="v", x=1.01, y=1),
        margin=dict(t=50, b=20, r=160),
    )
    return _fig_to_dict(fig)


def _chart_sector_avg(summary: pd.DataFrame) -> dict:
    if summary.empty:
        return _fig_to_dict(go.Figure())
    sec_avg = (
        summary.groupby("sector")[["ir", "sharpe", "win_rate", "ann_ret"]]
        .mean()
        .reset_index()
        .sort_values("ir", ascending=False)
    )
    fig = go.Figure()
    for key, label in [("ir", "IR"), ("sharpe", "Sharpe"), ("win_rate", "Win Rate")]:
        fig.add_trace(
            go.Bar(
                name=label, x=sec_avg["sector"], y=sec_avg[key],
                text=[f"{v:.2f}" for v in sec_avg[key]],
                textposition="outside",
            )
        )
    fig.add_hline(y=0, line_dash="dash", line_color=PALETTE["grid"], line_width=0.8)
    fig.update_layout(
        title="Average IR / Sharpe / Win-Rate by Sector",
        barmode="group", height=400, template="plotly_white",
        legend=dict(orientation="h", y=1.06),
        margin=dict(t=50, b=20), yaxis_title="Score",
    )
    return _fig_to_dict(fig)


def _chart_quintile_profile_by_sector(all_qs: pd.DataFrame, field: str, label: str) -> dict:
    if all_qs.empty:
        return _fig_to_dict(go.Figure())
    sec_qs = (
        all_qs.groupby(["sector", "quintile"], observed=True)[[field]]
        .mean()
        .reset_index()
    )
    sec_qs["quintile"] = sec_qs["quintile"].astype(int)
    pivot = sec_qs.pivot(index="sector", columns="quintile", values=field)
    pivot.columns = [f"Q{c}" for c in pivot.columns]
    ordered = [s for s in SECTORS if s in pivot.index]
    pivot = pivot.reindex(index=ordered)

    fig = go.Figure()
    for i, col in enumerate(pivot.columns):
        colour = QUANTILE_COLOURS[min(i, len(QUANTILE_COLOURS) - 1)]
        fig.add_trace(
            go.Bar(
                name=col, x=pivot.index.tolist(), y=pivot[col].tolist(),
                marker_color=colour,
                text=[f"{v:+.3f}" if not np.isnan(v) else "" for v in pivot[col]],
                textposition="outside",
            )
        )
    fig.add_hline(y=0, line_dash="dash", line_color=PALETTE["grid"], line_width=0.8)
    fig.update_layout(
        title=f"Quintile profile by sector — {label}",
        barmode="group", height=440, template="plotly_white",
        yaxis_title="Mean Z-score", xaxis_title="Sector",
        legend=dict(orientation="h", y=1.06),
        margin=dict(t=50, b=20),
    )
    return _fig_to_dict(fig)


def _chart_sector_decade_heatmap(all_decade: pd.DataFrame, sector: str) -> dict:
    sub = all_decade[all_decade["sector"] == sector]
    if sub.empty:
        return _fig_to_dict(go.Figure())
    pivot = (
        sub.groupby(["decade", "quintile"], observed=True)["fret20"]
        .mean()
        .unstack("quintile")
        * 100
    )
    if pivot.empty:
        return _fig_to_dict(go.Figure())
    pivot = pivot.sort_index()
    pivot.columns = [f"Q{int(c)}" for c in pivot.columns]
    text_vals = [
        [f"{v:.2f}%" if not np.isnan(v) else "" for v in row]
        for row in pivot.values
    ]
    fig = go.Figure(
        go.Heatmap(
            z=pivot.values, x=pivot.columns.tolist(), y=pivot.index.tolist(),
            colorscale="RdYlGn", zmid=0,
            text=text_vals, texttemplate="%{text}",
            textfont=dict(size=9),
            colorbar=dict(title="%", thickness=12, len=0.8),
        )
    )
    fig.update_layout(
        title=sector, xaxis_title="Quintile", yaxis_title="Decade",
        height=280, template="plotly_white",
        margin=dict(t=40, b=20, l=10, r=10),
    )
    return _fig_to_dict(fig)


def _table_full_instruments(summary: pd.DataFrame) -> TableSpec:
    rows = [
        {
            "label": r.label,
            "sector": r.sector,
            "years": f"{r.years:.1f}",
            "clean_rows": int(r.clean_rows),
            "ir": f"{r.ir:.3f}",
            "sharpe": f"{r.sharpe:.3f}",
            "ann_ret": f"{r.ann_ret:.1%}",
            "ann_std": f"{r.ann_std:.1%}",
            "win_rate": f"{r.win_rate:.1%}",
            "max_dd": f"{r.max_dd:.1%}",
        }
        for r in summary.itertuples()
    ]
    return TableSpec(
        id="full-instruments",
        title="Full Instruments Table",
        columns=[
            ColumnSpec(key="label",      label="Instrument", format="text"),
            ColumnSpec(key="sector",     label="Sector",     format="text"),
            ColumnSpec(key="years",      label="Years",      format="text", align="right"),
            ColumnSpec(key="clean_rows", label="Clean Obs",  format="number", align="right"),
            ColumnSpec(key="ir",         label="IR",         format="text", align="right"),
            ColumnSpec(key="sharpe",     label="Sharpe",     format="text", align="right"),
            ColumnSpec(key="ann_ret",    label="Ann. Return", format="text", align="right"),
            ColumnSpec(key="ann_std",    label="Ann. Vol",   format="text", align="right"),
            ColumnSpec(key="win_rate",   label="Win Rate",   format="text", align="right"),
            ColumnSpec(key="max_dd",     label="Max DD",     format="text", align="right"),
        ],
        rows=rows,
    )


def _vol_compute_summary(params: VolAnalysisParams) -> StrategyResult:
    instruments = instrument_service.list_instruments(InstrumentKind.vol)
    warnings: list[str] = []
    rows: list[dict] = []
    for inst in instruments:
        try:
            df = instrument_service.load_instrument_frame(InstrumentKind.vol, inst.id)
            r = _run_one_instrument(
                inst.label, inst.sector or "Unclassified", df,
                params.window, params.norm_win, params.n_quantiles,
                params.long_q, params.short_q,
            )
            if "error" in r:
                warnings.append(f"{inst.label}: {r['error']}")
            else:
                rows.append(r)
        except Exception as exc:
            warnings.append(f"{inst.label}: {exc}")

    if not rows:
        return StrategyResult(
            overview_md=_SUMMARY_OVERVIEW_MD,
            warnings=warnings or ["No instruments with enough data."],
            tabs=[],
        )

    summary = pd.DataFrame(rows).sort_values(["sector", "ir"], ascending=[True, False])
    all_qs = pd.concat([r["qs_df"] for r in rows], ignore_index=True)
    all_decade = pd.concat([r["decade_df"] for r in rows], ignore_index=True)

    global_metrics = [
        Metric(key="n",        label="Instruments",     value=float(len(summary)), format="number"),
        Metric(key="avg_ir",   label="Avg IR",          value=float(summary["ir"].mean()), format="ratio"),
        Metric(key="avg_shar", label="Avg Sharpe",      value=float(summary["sharpe"].mean()), format="ratio"),
        Metric(key="avg_ret",  label="Avg Ann. Return", value=float(summary["ann_ret"].mean()), format="percent"),
        Metric(key="avg_wr",   label="Avg Win Rate",    value=float(summary["win_rate"].mean()), format="percent"),
        Metric(key="avg_dd",   label="Avg Max DD",      value=float(summary["max_dd"].mean()), format="percent"),
    ]

    metric_charts = [
        ChartSpec(
            id=f"bar-{key}",
            title=title,
            figure=_chart_metric_bar(summary, key, title),
        )
        for key, title in [
            ("ir", "Information Ratio"),
            ("sharpe", "Sharpe Ratio"),
            ("ann_ret", "Ann. Return"),
            ("ann_std", "Ann. Volatility"),
            ("win_rate", "Win Rate"),
            ("max_dd", "Max Drawdown"),
        ]
    ]

    quintile_profile_charts = [
        ChartSpec(
            id=f"q-sec-{field}",
            title=title,
            figure=_chart_quintile_profile_by_sector(all_qs, field, title),
        )
        for field, title in [
            ("avg_zvol20", "avg zvol20 — Normalised Volatility"),
            ("avg_zret20", "avg zret20 — Concurrent Return"),
            ("avg_zfret20", "avg zfret20 — Future Return (Lead-Lag)"),
        ]
    ]

    sectors_with_data = sorted(all_decade["sector"].unique())
    sector_heat_charts = [
        ChartSpec(
            id=f"heat-{sec.lower().replace(' ', '-').replace('/', '-')}",
            title=f"{sec} — decade × quintile",
            figure=_chart_sector_decade_heatmap(all_decade, sec),
        )
        for sec in sectors_with_data
    ]

    summary_tab = TabSpec(
        id="summary",
        title="Summary · All Instruments",
        icon="🌐",
        intro_md=_TAB6_INTRO_MD,
        metrics=global_metrics,
        charts=[
            *metric_charts,
            ChartSpec(
                id="risk-return-map",
                title="Risk / Return map",
                description="Bubble size = |IR|, colour = sector. Top-left is ideal (high return, low vol).",
                figure=_chart_risk_return_map(summary),
            ),
            ChartSpec(
                id="sector-avg",
                title="Average IR / Sharpe / Win-Rate by Sector",
                figure=_chart_sector_avg(summary),
            ),
            *quintile_profile_charts,
            *sector_heat_charts,
        ],
        tables=[_table_full_instruments(summary)],
    )

    return StrategyResult(
        overview_md=_SUMMARY_OVERVIEW_MD,
        tabs=[summary_tab],
        warnings=warnings,
    )


VolAnalysisStrategy.compute_summary = lambda self, params: _vol_compute_summary(params)  # type: ignore[method-assign]


STRATEGY = VolAnalysisStrategy()
