"""Trend Following strategy — ported from legacy/vol_app.py.

Processes every instrument in the trend catalogue simultaneously using 4 fixed
systems (10/30 MA, 30/100 MA, 80/160 MA, 30-Day Breakout). Four tabs:

- 📉 Signals    — price/MA/signal chart for one selected (asset, system)
- 🔁 Backtest  — multi-asset equity curves, Sharpe bar chart, metrics table
- 💼 Portfolio — EW vs Inverse-Vol portfolio equity, drawdown, correlation heatmap
- 🔬 Insights  — speed decay, diversification, drawdown pain table, Sortino vs Sharpe
"""

from __future__ import annotations

import json
import re
from datetime import date

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from pydantic import BaseModel, Field

from app.core.palette import PALETTE
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


# ─── Systems & colours ────────────────────────────────────────────────────────


SYSTEMS: list[tuple[str, int | None, int | None]] = [
    ("10/30 MA", 10, 30),
    ("30/100 MA", 30, 100),
    ("80/160 MA", 80, 160),
    ("30-Day Breakout", None, None),
]
SYSTEM_NAMES = [s[0] for s in SYSTEMS]

SYSTEM_COLOURS = {
    "10/30 MA":        "#E65100",
    "30/100 MA":       "#1565C0",
    "80/160 MA":       "#2E7D32",
    "30-Day Breakout": "#7B1FA2",
}

ASSET_BUILTIN_COLOURS = {
    "Euro FX":      "#1565C0",
    "10-Year Note": "#2E7D32",
    "S&P 500":      "#B71C1C",
}
EXTRA_COLOUR_POOL = [
    "#FF6F00", "#00695C", "#6A1B9A", "#37474F",
    "#AD1457", "#0277BD", "#558B2F", "#4E342E",
]


def _asset_colour(label: str, extras_seen: dict[str, int]) -> str:
    if label in ASSET_BUILTIN_COLOURS:
        return ASSET_BUILTIN_COLOURS[label]
    if label not in extras_seen:
        extras_seen[label] = len(extras_seen)
    return EXTRA_COLOUR_POOL[extras_seen[label] % len(EXTRA_COLOUR_POOL)]


# ─── Params ───────────────────────────────────────────────────────────────────


class TrendFollowingParams(BaseModel):
    date_start: date | None = None
    date_end: date | None = None
    tc_bps: float = Field(default=1.0, ge=0, le=5.0, description="Transaction cost (bps/trade)")
    use_ema: bool = Field(default=False, description="Use EMA instead of SMA")
    signal_asset: str | None = Field(
        default=None,
        description="Instrument label to show in the Signal tab (defaults to first available)",
    )
    signal_system: str = Field(
        default="30/100 MA",
        description="System to show in the Signal tab",
    )
    best_systems: dict[str, str] = Field(
        default_factory=dict,
        description="Per-asset system override for the Portfolio tab; "
                    "empty → best-Sharpe per asset",
    )


# ─── Compute primitives ───────────────────────────────────────────────────────


def _ma(series: pd.Series, window: int, use_ema: bool) -> pd.Series:
    if use_ema:
        return series.ewm(span=window, adjust=False).mean()
    return series.rolling(window).mean()


def _ma_signal(
    price: pd.Series, fast: int, slow: int, use_ema: bool
) -> tuple[pd.Series, pd.Series, pd.Series]:
    fast_ma = _ma(price, fast, use_ema)
    slow_ma = _ma(price, slow, use_ema)
    sig = pd.Series(np.where(fast_ma > slow_ma, 1.0, -1.0), index=price.index)
    sig.iloc[:slow] = np.nan
    return sig, fast_ma, slow_ma


def _breakout_signal(price: pd.Series, window: int = 30) -> pd.Series:
    hi = price.rolling(window).max().shift(1)
    lo = price.rolling(window).min().shift(1)
    sig = pd.Series(np.nan, index=price.index, dtype=float)
    sig[price > hi] = 1.0
    sig[price < lo] = -1.0
    sig.iloc[:window] = np.nan
    return sig.ffill()


def _backtest(
    log_rets: pd.Series, signal: pd.Series, tc_bps: float
) -> tuple[pd.Series, pd.Series, pd.Series]:
    sig = signal.reindex(log_rets.index)
    sys_ret = sig.shift(1) * log_rets
    tc = (tc_bps / 10_000) * sig.diff().abs().fillna(0)
    net_ret = (sys_ret - tc).dropna()
    eq = np.exp(net_ret.cumsum())
    dd = eq / eq.cummax() - 1
    return net_ret, eq, dd


def _trend_metrics(daily_rets: pd.Series) -> dict[str, float]:
    r = daily_rets.dropna()
    if len(r) < 20:
        return dict(ann_ret=0.0, ann_vol=0.0, sharpe=0.0, sortino=0.0, max_dd=0.0)
    mu = r.mean()
    sd = r.std()
    ann_ret = float(mu * 252)
    ann_vol = float(sd * np.sqrt(252))
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0.0
    neg = r[r < 0]
    sor_den = float(neg.std() * np.sqrt(252)) if len(neg) > 1 else 0.0
    sortino = ann_ret / sor_den if sor_den > 0 else 0.0
    eq = np.exp(r.cumsum())
    max_dd = float((eq / eq.cummax() - 1).min())
    return dict(
        ann_ret=ann_ret, ann_vol=ann_vol,
        sharpe=float(sharpe), sortino=float(sortino), max_dd=max_dd,
    )


def _build_portfolio(
    best_rets: dict[str, pd.Series], lookback_vol: int = 20
) -> tuple[pd.Series, pd.Series, list[str], pd.DataFrame]:
    """Equal-weight and inverse-vol portfolio returns on a **shared calendar**.

    If there is no single trading day where *every* asset has a return (e.g. some series
    end before others begin), we drop the asset with the **earliest last date** and retry
    until an inner join is non-empty or only one series remains.
    """
    dropped: list[str] = []
    if not best_rets:
        return pd.Series(dtype=float), pd.Series(dtype=float), dropped, pd.DataFrame()

    br = dict(best_rets)
    df = pd.DataFrame()
    while True:
        df = pd.concat(br, axis=1, join="inner", sort=True)
        if not df.empty:
            break
        if len(br) <= 1:
            break
        drop_key = min(br.keys(), key=lambda k: br[k].index.max())
        dropped.append(drop_key)
        del br[drop_key]

    if df.empty:
        return pd.Series(dtype=float), pd.Series(dtype=float), dropped, pd.DataFrame()

    eq_ret = df.mean(axis=1)
    roll_vol = df.rolling(lookback_vol).std()
    inv_vol = 1.0 / roll_vol.replace(0, np.nan)
    weights = inv_vol.div(inv_vol.sum(axis=1), axis=0)
    iv_ret = (weights.shift(1) * df).sum(axis=1)
    if len(iv_ret) > lookback_vol + 1:
        iv_ret = iv_ret.iloc[lookback_vol + 1 :]
    return eq_ret, iv_ret, dropped, df


def _top_drawdowns(eq: pd.Series, n: int = 5) -> pd.DataFrame:
    if eq.empty:
        return pd.DataFrame()
    dd = eq / eq.cummax() - 1
    rows = []
    in_dd = False
    peak_date = trough_date = None
    trough_val = 0.0

    for date_, val in dd.items():
        if val < 0:
            if not in_dd:
                in_dd = True
                peak_date = eq.loc[:date_].idxmax()
                trough_val = val
                trough_date = date_
            elif val < trough_val:
                trough_val = val
                trough_date = date_
        else:
            if in_dd:
                peak_level = eq.loc[peak_date]
                future = eq.loc[trough_date:]
                recovered = future[future >= peak_level]
                rec_date = recovered.index[0] if len(recovered) else None
                rows.append({
                    "peak": peak_date.date(),
                    "trough": trough_date.date(),
                    "recovery": rec_date.date() if rec_date else "Not recovered",
                    "max_dd": trough_val,
                    "duration": (trough_date - peak_date).days,
                    "recovery_days": (rec_date - trough_date).days if rec_date else None,
                })
                in_dd = False
                trough_val = 0.0
    if in_dd and peak_date is not None:
        rows.append({
            "peak": peak_date.date(),
            "trough": trough_date.date(),
            "recovery": "Not recovered",
            "max_dd": trough_val,
            "duration": (trough_date - peak_date).days,
            "recovery_days": None,
        })
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows).sort_values("max_dd").head(n).reset_index(drop=True)
    return df


# ─── Per-instrument runner ────────────────────────────────────────────────────


def _load_asset_series(
    instrument_id: str,
) -> tuple[pd.Series, pd.Series]:
    """Return (price, log_ret) indexed by Date for a trend instrument."""
    df = instrument_service.load_instrument_frame(InstrumentKind.trend, instrument_id)
    df = df.sort_values("Date").drop_duplicates("Date").reset_index(drop=True)
    price = df.set_index("Date")["Close"]
    log_ret = np.log(price / price.shift(1)).dropna()
    return price, log_ret


def _run_asset(
    price_full: pd.Series,
    log_ret_full: pd.Series,
    ds: pd.Timestamp | None,
    de: pd.Timestamp | None,
    use_ema: bool,
    tc_bps: float,
) -> dict:
    """Compute signals + backtests for one asset across all 4 systems."""
    per_system: dict[str, dict] = {}
    for sname, fast, slow in SYSTEMS:
        if sname == "30-Day Breakout":
            sig_full = _breakout_signal(price_full, window=30)
            fm_full = sm_full = None
        else:
            sig_full, fm_full, sm_full = _ma_signal(price_full, fast, slow, use_ema)

        net_full, _eq_full, _dd_full = _backtest(log_ret_full, sig_full, tc_bps)

        # Slice to display window
        sig = sig_full.loc[ds:de] if ds or de else sig_full
        net = net_full.loc[ds:de] if ds or de else net_full
        price_w = price_full.loc[ds:de] if ds or de else price_full
        fm = fm_full.loc[ds:de] if fm_full is not None and (ds or de) else fm_full
        sm = sm_full.loc[ds:de] if sm_full is not None and (ds or de) else sm_full

        if len(net) > 0:
            eq = np.exp(net.cumsum())
            eq = eq / eq.iloc[0]
            dd = eq / eq.cummax() - 1
        else:
            eq = pd.Series(dtype=float)
            dd = pd.Series(dtype=float)

        per_system[sname] = dict(
            signal=sig,
            fast_ma=fm,
            slow_ma=sm,
            price=price_w,
            net_ret=net,
            eq=eq,
            dd=dd,
            metrics=_trend_metrics(net),
        )
    return per_system


# ─── Narrative (markdown) ─────────────────────────────────────────────────────


_OVERVIEW_MD = """\
**Trend Following — systematic momentum across a basket of assets.**

Ride the wave in whatever direction the market is moving; flip the position when it
changes. Four fixed systems run in parallel on every instrument in the trend catalogue:

- **10/30 MA**, **30/100 MA**, **80/160 MA** — moving-average crossover systems (fast MA
  crosses above slow → long; below → short).
- **30-Day Breakout** — go long on break of 30-day high, short on break of 30-day low;
  hold until the opposite signal.

Returns are combined into **equal-weight** and **inverse-volatility-weight** portfolios
using each asset's best-Sharpe system (override in the sidebar).
"""


_SIGNALS_GUIDE_MD = """\
**Trend following in one sentence:** *ride the wave in whatever direction the market is
moving, and flip when it changes.*

**Moving Average Crossover systems.** A moving average smooths out daily price noise.
We use a fast one and a slow one. When the fast line crosses above the slow line, a new
uptrend may be forming → go **Long (+1)**. When fast crosses below slow → go **Short (−1)**.

**30-Day Breakout.** Instead of MAs, watches the *range* of the past 30 days. Price
breaks above the 30-day high (set yesterday) → go Long; breaks below → Short;
otherwise hold.

**What to look for in the chart:**
- **2008 crash period:** Does the signal flip to Short early enough to avoid the worst
  of the drawdown? Slower systems (80/160) stay short longer and ride the recovery.
- **Choppy markets:** Fast systems generate many more flips — each flip is a trade
  and each trade costs money. *Whiplash* is the enemy of fast systems.
- **Trend persistence:** Long stretches of solid green or solid red shading = profitable
  regimes for trend-followers. Frequent alternating = choppy, costly markets.
"""


_BACKTEST_GUIDE_MD = """\
**What is an equity curve?** The growth of $1 invested in a strategy. A curve ending at
**1.35** turned $1 into $1.35 (35% cumulative return). A flat curve means break-even.

**How system returns are calculated:**

> *Return_today = Yesterday's Signal × Today's Log Return − Transaction Cost*

We use **yesterday's** signal to avoid lookahead bias — you can only trade on a signal
you already knew. Transaction cost is deducted every time the signal *flips*. Even 1 bp
adds up for fast systems (the 10/30 flips ~50×/yr).

**The burn-in period:** the 80/160 system needs 160 days before it can produce its first
signal. All system equity curves start from the same first-valid date so the comparison
is fair.

**Reading the Sharpe bar chart.** Sharpe above **0.5** is strong for a systematic
strategy. Look for **speed decay** — the slowest system (80/160) consistently beating
the fastest (10/30) after costs. This is the Winton finding: slower systems are more
robust to noise.
"""


_PORTFOLIO_GUIDE_MD = """\
**The core problem with a single system on a single asset:** any single strategy has
good and bad years. You can't know which asset or system will outperform next year.

**The solution: diversify across uncorrelated signals.** If two assets are uncorrelated,
when one is losing the other is often doing something different — maybe even profiting.
Combining them produces a smoother ride than either alone.

> *Portfolio Sharpe ≈ S × √N* for N uncorrelated strategies each with Sharpe S.
> Three strategies each at Sharpe 0.3 combine to ~0.52 — a 70%+ improvement, for free.

**Equal Weight (1/N each)** — pure democracy. Risk: one very volatile asset dominates.

**Inverse Volatility Weight ("Risk Parity").** Weight inversely by trailing 20-day σ, so
an asset twice as volatile gets half the weight. Automatically pulls back from the most
dangerous asset — no human judgement required. Expected: smaller max drawdown than EW
during crises.

**Reading the correlation heatmap.** ρ ≈ 0 means maximum diversification benefit;
ρ ≈ +1 means no benefit. If all cross-asset correlations are near zero, the combo
equity curve should be noticeably smoother than any individual.
"""


_INSIGHTS_SPEED_MD = """\
**Does trading faster make more money?** Intuition says more signals = more profit.
The data — and the Winton paper — says the opposite.

**Why slower systems win:**
1. **Transaction costs compound against fast systems.** 10/30 might flip 40–60×/year
   (40–60 bps annual drag at 1 bp/trade). 80/160 flips 8–12×/year.
2. **Noise vs signal.** A fast MA reacts to short-term noise and triggers whiplash
   trades. A slow MA only responds to sustained trends.
3. **Raw returns are similar** before costs; *after* costs, slower systems significantly
   outperform.

Try bumping the transaction cost slider to 3 bps — the fast system's Sharpe collapses
while the slow system's barely moves.
"""


_INSIGHTS_DIVERSIFICATION_MD = """\
**Wiggles cancel out.** Two strategies that earn ±1% in opposite months combined give 0%
both months — no volatility, infinite Sharpe. In practice correlations are never
perfectly −1, but moving from ρ = +0.8 to ρ = 0.0 has a dramatic effect on smoothness.

**The free lunch:** *Portfolio Sharpe ≈ S × √N*. Three strategies at Sharpe 0.3 combine
to ~0.52 — achieved without changing any individual strategy.

**Euro FX, 10-Year Note, S&P 500** are structurally different: currencies driven by
central bank divergence, bonds by rate cycles, equities by earnings — largely independent
drivers. Their cross-correlations should be near zero.

**The combo equity curve should be smoother** than any individual asset's line. That's
the whole point.
"""


_INSIGHTS_PAIN_MD = """\
**A drawdown is the distance from the most recent all-time high.** Portfolio peaks at
$150, now at $120 → −20% drawdown. Recovery = surpassing $150.

**Drawdowns are the real test of a strategy.** A great 10-year Sharpe matters little
if a −35% drawdown made clients redeem at the bottom. The question isn't "does this
work?" — it's "can you stomach it when it isn't?"

**Recovery time is the most psychologically important column.** A −20% drawdown that
recovers in 3 months feels nothing like one that takes 18 months. In that 18 months:
clients call to redeem, the manager is second-guessed, the temptation to override the
rules is at its highest. The systematic manager's discipline is tested *precisely* when
it looks most broken.

**Reference lines:** Drawdowns below **−10%** start feeling painful to clients;
below **−20%** is where redemptions typically accelerate.
"""


_INSIGHTS_SORTINO_MD = """\
**Sharpe treats a +5% day and a −5% day as equally risky.** For trend-followers that's
wrong — a +5% day is wonderful, −5% is painful. Penalising large gains as if they were
risk systematically understates breakout/trend systems.

**Sortino fixes this:**

> *Sortino = Annualised Return / (Downside σ × √252)*

Only *negative* daily returns count toward the denominator. Positive days don't penalise.
For a strategy that *cuts losses short and lets winners run*, Sortino >> Sharpe.

**Breakout systems should show the biggest Sortino/Sharpe gap** — they enter only when
a strong trend is already forming, so when in a trade it tends to be a big move. Large
positive returns inflate Sharpe's denominator but not Sortino's.

**Scatter reading.** Points above the diagonal line have asymmetric upside (good).
Breakout points should cluster furthest above. Points below the diagonal would mean
larger losses than gains — dangerous.
"""


# ─── Charts ────────────────────────────────────────────────────────────────────


def _chart_signal(
    price: pd.Series,
    sig: pd.Series,
    fast_ma: pd.Series | None,
    slow_ma: pd.Series | None,
    asset: str,
    system: str,
    asset_colour: str,
) -> dict:
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        row_heights=[0.7, 0.3], vertical_spacing=0.04,
    )

    # Signal shading on row 1
    runs: list[tuple] = []
    clean = sig.dropna()
    if not clean.empty:
        prev = clean.iloc[0]
        start = clean.index[0]
        for dt, val in clean.items():
            if val != prev:
                runs.append((start, dt, prev))
                start = dt
                prev = val
        runs.append((start, clean.index[-1], prev))

    colours = {1.0: "rgba(46,125,50,0.22)", -1.0: "rgba(198,40,40,0.22)"}
    for s, e, v in runs:
        if v in colours:
            fig.add_shape(
                type="rect",
                xref="x", yref="y domain",
                x0=s, x1=e, y0=0, y1=1,
                fillcolor=colours[v],
                layer="below", line_width=0,
                row=1, col=1,
            )

    fig.add_trace(
        go.Scatter(
            x=price.index, y=price, name="Price",
            line=dict(color=asset_colour, width=1.5),
        ),
        row=1, col=1,
    )
    if fast_ma is not None:
        fig.add_trace(
            go.Scatter(
                x=fast_ma.index, y=fast_ma, name="Fast MA",
                line=dict(color=PALETTE["orange"], width=1, dash="dash"),
            ),
            row=1, col=1,
        )
    if slow_ma is not None:
        fig.add_trace(
            go.Scatter(
                x=slow_ma.index, y=slow_ma, name="Slow MA",
                line=dict(color="#7B1FA2", width=1, dash="dot"),
            ),
            row=1, col=1,
        )

    fig.add_trace(
        go.Scatter(
            x=sig.index, y=sig, name="Signal (±1)",
            line=dict(color="#37474F", width=1),
            fill="tozeroy", fillcolor="rgba(55,71,79,0.08)",
        ),
        row=2, col=1,
    )
    fig.add_hline(y=0, line_dash="dash", line_color="#9E9E9E", line_width=0.8, row=2, col=1)

    fig.update_yaxes(title_text="Price", row=1, col=1)
    fig.update_yaxes(title_text="Signal", tickvals=[-1, 0, 1], row=2, col=1)
    fig.update_layout(
        title=f"{asset} — {system}",
        height=540, hovermode="x unified", template="plotly_white",
        legend=dict(orientation="h", y=1.03), margin=dict(t=50, b=20),
    )
    return _fig_to_dict(fig)


def _chart_id_slug(label: str) -> str:
    """Stable id fragment for ChartSpec ids (ASCII slug)."""
    s = re.sub(r"[^a-zA-Z0-9]+", "-", label.strip()).strip("-").lower()
    return s or "asset"


def _chart_single_asset_equity(asset_name: str, per_system: dict[str, dict]) -> dict:
    """One simple figure per asset: four system equity curves overlaid (no stacked subplots)."""
    fig = go.Figure()
    for sname in SYSTEM_NAMES:
        eq = per_system[sname]["eq"]
        if eq is None or (isinstance(eq, pd.Series) and eq.empty):
            continue
        fig.add_trace(
            go.Scatter(
                x=eq.index,
                y=eq,
                name=sname,
                line=dict(color=SYSTEM_COLOURS[sname], width=1.4),
                hovertemplate=f"{sname}<br>%{{x|%Y-%m-%d}}<br>%{{y:.4f}}<extra></extra>",
            )
        )
    fig.update_layout(
        height=320,
        hovermode="x unified",
        template="plotly_white",
        legend=dict(orientation="h", y=1.12, x=0, font=dict(size=10)),
        margin=dict(t=40, b=40),
        xaxis=dict(type="date"),
        yaxis_title="Equity (normalised)",
    )
    return _fig_to_dict(fig)


def _chart_sharpe_bar(sharpe_df: pd.DataFrame) -> dict:
    fig = go.Figure()
    for sname in SYSTEM_NAMES:
        sub = sharpe_df[sharpe_df["system"] == sname]
        fig.add_trace(
            go.Bar(
                name=sname, x=sub["asset"], y=sub["sharpe"],
                marker_color=SYSTEM_COLOURS[sname],
                text=[f"{v:.2f}" for v in sub["sharpe"]],
                textposition="outside",
            )
        )
    fig.add_hline(y=0, line_dash="dash", line_color=PALETTE["grid"], line_width=0.8)
    fig.update_layout(
        title="Sharpe Ratio by System & Asset",
        barmode="group", height=380, template="plotly_white",
        legend=dict(orientation="h", y=1.04),
        yaxis_title="Annualised Sharpe",
        margin=dict(t=50, b=20),
    )
    return _fig_to_dict(fig)


def _table_metrics(assets: list[str], per_asset: dict[str, dict]) -> TableSpec:
    rows = []
    for aname in assets:
        for sname in SYSTEM_NAMES:
            m = per_asset[aname][sname]["metrics"]
            rows.append({
                "asset": aname,
                "system": sname,
                "ann_ret": f"{m['ann_ret']:.2%}",
                "ann_vol": f"{m['ann_vol']:.2%}",
                "sharpe": f"{m['sharpe']:.3f}",
                "sortino": f"{m['sortino']:.3f}",
                "max_dd": f"{m['max_dd']:.2%}",
            })
    return TableSpec(
        id="full-metrics",
        title="Full Metrics — every asset × system",
        columns=[
            ColumnSpec(key="asset",   label="Asset",       format="text"),
            ColumnSpec(key="system",  label="System",      format="text"),
            ColumnSpec(key="ann_ret", label="Ann. Return", format="text", align="right"),
            ColumnSpec(key="ann_vol", label="Ann. Vol",    format="text", align="right"),
            ColumnSpec(key="sharpe",  label="Sharpe",      format="text", align="right"),
            ColumnSpec(key="sortino", label="Sortino",     format="text", align="right"),
            ColumnSpec(key="max_dd",  label="Max DD",      format="text", align="right"),
        ],
        rows=rows,
    )


def _chart_portfolio_equity(eq_eq: pd.Series, iv_eq: pd.Series) -> dict:
    fig = go.Figure()
    if not eq_eq.empty:
        fig.add_trace(
            go.Scatter(
                x=eq_eq.index, y=eq_eq,
                name="Equal Weight", line=dict(color="#1565C0", width=2),
            )
        )
    if not iv_eq.empty:
        fig.add_trace(
            go.Scatter(
                x=iv_eq.index, y=iv_eq,
                name="Inverse Vol Weight", line=dict(color="#B71C1C", width=2),
            )
        )
    fig.update_layout(
        title="Equal Weight vs Inverse Volatility Weight — cumulative return",
        yaxis_title="Cumulative Return",
        height=400, hovermode="x unified", template="plotly_white",
        legend=dict(orientation="h", y=1.04), margin=dict(t=50, b=20),
    )
    return _fig_to_dict(fig)


def _chart_portfolio_drawdown(eq_dd: pd.Series, iv_dd: pd.Series) -> dict:
    fig = go.Figure()
    for series, name, colour, fill in [
        (eq_dd, "Equal Weight",       "#1565C0", "rgba(21,101,192,0.12)"),
        (iv_dd, "Inverse Vol Weight", "#B71C1C", "rgba(183,28,28,0.12)"),
    ]:
        if series.empty:
            continue
        fig.add_trace(
            go.Scatter(
                x=series.index, y=series * 100, name=name,
                line=dict(color=colour, width=1.2),
                fill="tozeroy", fillcolor=fill,
            )
        )
    fig.update_layout(
        title="Portfolio drawdown",
        yaxis_title="Drawdown (%)",
        height=300, hovermode="x unified", template="plotly_white",
        legend=dict(orientation="h", y=1.04), margin=dict(t=50, b=20),
    )
    return _fig_to_dict(fig)


def _chart_correlation_heatmap(corr: pd.DataFrame, title: str, text_size: int = 10) -> dict:
    if corr.empty:
        return _fig_to_dict(go.Figure())
    fig = go.Figure(
        go.Heatmap(
            z=corr.values,
            x=corr.columns.tolist(),
            y=corr.index.tolist(),
            colorscale="RdBu", zmid=0, zmin=-1, zmax=1,
            text=[[f"{v:.2f}" for v in row] for row in corr.values],
            texttemplate="%{text}",
            textfont=dict(size=text_size),
            colorbar=dict(title="ρ"),
        )
    )
    fig.update_layout(
        title=title,
        height=max(320, 30 * len(corr)),
        template="plotly_white",
        margin=dict(t=50, b=20),
    )
    return _fig_to_dict(fig)


def _chart_speed_decay_bar(speed_df: pd.DataFrame, assets: list[str]) -> dict:
    extras_seen: dict[str, int] = {}
    fig = go.Figure()
    for aname in assets:
        sub = speed_df[speed_df["asset"] == aname]
        fig.add_trace(
            go.Bar(
                name=aname, x=sub["system"], y=sub["sharpe"],
                marker_color=_asset_colour(aname, extras_seen),
                text=[f"{v:.2f}" for v in sub["sharpe"]],
                textposition="outside",
            )
        )
    fig.add_hline(y=0, line_dash="dash", line_color=PALETTE["grid"], line_width=0.8)
    fig.update_layout(
        title="Sharpe by system speed — asset-by-asset",
        barmode="group", height=380, template="plotly_white",
        yaxis_title="Sharpe",
        legend=dict(orientation="h", y=1.04), margin=dict(t=50, b=20),
    )
    return _fig_to_dict(fig)


def _chart_sortino_line(speed_df: pd.DataFrame, assets: list[str]) -> dict:
    extras_seen: dict[str, int] = {}
    fig = go.Figure()
    for aname in assets:
        sub = speed_df[speed_df["asset"] == aname]
        fig.add_trace(
            go.Scatter(
                x=sub["system"], y=sub["sortino"],
                name=aname, mode="lines+markers",
                line=dict(color=_asset_colour(aname, extras_seen), width=2),
                marker=dict(size=8),
            )
        )
    fig.add_hline(y=0, line_dash="dash", line_color=PALETTE["grid"], line_width=0.8)
    fig.update_layout(
        title="Sortino ratio by system (downside-only risk adjustment)",
        yaxis_title="Sortino",
        height=320, template="plotly_white",
        legend=dict(orientation="h", y=1.04), margin=dict(t=50, b=20),
    )
    return _fig_to_dict(fig)


def _chart_diversification_overlay(
    per_asset: dict[str, dict],
    best_per_asset: dict[str, str],
    eq_eq_d: pd.Series,
    assets: list[str],
) -> dict:
    extras_seen: dict[str, int] = {}
    fig = go.Figure()
    for aname in assets:
        sys_name = best_per_asset[aname]
        eq = per_asset[aname][sys_name]["eq"]
        fig.add_trace(
            go.Scatter(
                x=eq.index, y=eq,
                name=f"{aname} ({sys_name})",
                line=dict(
                    color=_asset_colour(aname, extras_seen), width=1.2, dash="dot",
                ),
            )
        )
    if not eq_eq_d.empty:
        fig.add_trace(
            go.Scatter(
                x=eq_eq_d.index, y=eq_eq_d,
                name="Combo (Equal Weight)",
                line=dict(color="#37474F", width=2.5),
            )
        )
    fig.update_layout(
        title="Individual assets (best system each) vs equal-weight combo",
        yaxis_title="Cumulative Return",
        height=400, hovermode="x unified", template="plotly_white",
        legend=dict(orientation="h", y=1.04), margin=dict(t=50, b=20),
    )
    return _fig_to_dict(fig)


def _chart_pain_drawdown(dd: pd.Series) -> dict:
    if dd.empty:
        return _fig_to_dict(go.Figure())
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=dd.index, y=dd * 100, name="Drawdown (%)",
            fill="tozeroy", fillcolor="rgba(198,40,40,0.15)",
            line=dict(color="#B71C1C", width=1),
        )
    )
    fig.add_hline(y=-10, line_dash="dot", line_color=PALETTE["orange"], line_width=0.8,
                  annotation_text="−10%", annotation_position="left")
    fig.add_hline(y=-20, line_dash="dot", line_color="#B71C1C", line_width=0.8,
                  annotation_text="−20%", annotation_position="left")
    fig.update_layout(
        title="Portfolio drawdown with −10% and −20% reference lines",
        yaxis_title="Drawdown (%)",
        height=320, hovermode="x unified", template="plotly_white",
        margin=dict(t=50, b=20),
    )
    return _fig_to_dict(fig)


def _table_pain(pain_df: pd.DataFrame) -> TableSpec:
    def _int_or_na(v) -> int | str:
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return "N/A"
        return int(v)

    rows = [
        {
            "peak": str(r.peak),
            "trough": str(r.trough),
            "recovery": str(r.recovery),
            "max_dd": f"{r.max_dd:.2%}",
            "duration": _int_or_na(r.duration),
            "recovery_days": _int_or_na(r.recovery_days),
        }
        for r in pain_df.itertuples()
    ]
    return TableSpec(
        id="pain-table",
        title="Top drawdown episodes (worst → least worst)",
        columns=[
            ColumnSpec(key="peak",          label="Peak",           format="text"),
            ColumnSpec(key="trough",        label="Trough",         format="text"),
            ColumnSpec(key="recovery",      label="Recovery",       format="text"),
            ColumnSpec(key="max_dd",        label="Max DD",         format="text", align="right"),
            ColumnSpec(key="duration",      label="Duration (d)",   format="text", align="right"),
            ColumnSpec(key="recovery_days", label="Recovery (d)",   format="text", align="right"),
        ],
        rows=rows,
    )


def _chart_sharpe_vs_sortino(speed_df: pd.DataFrame) -> dict:
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            name="Sharpe", x=speed_df["label"], y=speed_df["sharpe"],
            marker_color="#1565C0", opacity=0.8,
        )
    )
    fig.add_trace(
        go.Bar(
            name="Sortino", x=speed_df["label"], y=speed_df["sortino"],
            marker_color="#2E7D32", opacity=0.8,
        )
    )
    fig.add_hline(y=0, line_dash="dash", line_color=PALETTE["grid"], line_width=0.8)
    fig.update_layout(
        title="Sharpe vs Sortino — every asset × system combo",
        barmode="group", height=420, template="plotly_white",
        yaxis_title="Ratio",
        legend=dict(orientation="h", y=1.04),
        xaxis_tickangle=-35,
        margin=dict(t=50, b=80),
    )
    return _fig_to_dict(fig)


def _chart_sharpe_sortino_scatter(speed_df: pd.DataFrame) -> dict:
    fig = go.Figure()
    for sname in SYSTEM_NAMES:
        sub = speed_df[speed_df["system"] == sname]
        fig.add_trace(
            go.Scatter(
                x=sub["sharpe"], y=sub["sortino"],
                mode="markers+text", name=sname,
                text=sub["asset"].str[:6],
                textposition="top center",
                marker=dict(color=SYSTEM_COLOURS[sname], size=12, opacity=0.85),
            )
        )
    if not speed_df.empty:
        lo = float(speed_df[["sharpe", "sortino"]].values.min()) - 0.1
        hi = float(speed_df[["sharpe", "sortino"]].values.max()) + 0.1
        fig.add_trace(
            go.Scatter(
                x=[lo, hi], y=[lo, hi],
                mode="lines", name="Sortino = Sharpe",
                line=dict(color="#9E9E9E", dash="dash", width=1),
            )
        )
    fig.update_layout(
        title="Points above the diagonal = good asymmetry (Sortino > Sharpe)",
        xaxis_title="Sharpe", yaxis_title="Sortino",
        height=420, template="plotly_white",
        legend=dict(orientation="h", y=1.04), margin=dict(t=50, b=20),
    )
    return _fig_to_dict(fig)


# ─── Strategy ─────────────────────────────────────────────────────────────────


class TrendFollowingStrategy(BaseStrategy):
    id = "trend-following"
    name = "Trend Following"
    description = (
        "MA crossovers & 30-day breakout across a basket of assets; "
        "equal-weight and inverse-vol portfolios."
    )
    instrument_kind = InstrumentKind.trend
    ParamsModel = TrendFollowingParams
    has_summary = False

    def compute(self, params: BaseModel) -> StrategyResult:
        assert isinstance(params, TrendFollowingParams)
        instruments = instrument_service.list_instruments(InstrumentKind.trend)
        if not instruments:
            return StrategyResult(
                overview_md=_OVERVIEW_MD,
                warnings=["No trend instruments — add some from the sidebar."],
                tabs=[],
            )

        ds = pd.Timestamp(params.date_start) if params.date_start else None
        de = pd.Timestamp(params.date_end) if params.date_end else None

        per_asset: dict[str, dict] = {}
        asset_names: list[str] = []
        skipped: list[str] = []
        for inst in instruments:
            try:
                price_full, log_ret_full = _load_asset_series(inst.id)
            except Exception as exc:
                skipped.append(f"{inst.label}: {exc}")
                continue
            in_window = price_full.loc[ds:de] if ds or de else price_full
            if len(in_window) == 0:
                skipped.append(f"{inst.label}: no data in window")
                continue
            per_asset[inst.label] = _run_asset(
                price_full, log_ret_full, ds, de, params.use_ema, params.tc_bps
            )
            asset_names.append(inst.label)

        if not asset_names:
            return StrategyResult(
                overview_md=_OVERVIEW_MD,
                warnings=(["No instruments have data in the selected window."] + skipped),
                tabs=[],
            )

        # ── Choose signal-tab asset + system ───────────────────────────────────
        signal_asset = params.signal_asset if params.signal_asset in per_asset else asset_names[0]
        signal_system = (
            params.signal_system if params.signal_system in SYSTEM_NAMES else "30/100 MA"
        )
        r = per_asset[signal_asset][signal_system]

        extras_seen: dict[str, int] = {}
        signal_chart = _chart_signal(
            r["price"], r["signal"].reindex(r["price"].index),
            r["fast_ma"], r["slow_ma"],
            signal_asset, signal_system,
            _asset_colour(signal_asset, extras_seen),
        )

        # ── Aggregate dataframes for reuse ─────────────────────────────────────
        sharpe_rows = []
        speed_rows = []
        all_ret_cols: dict[str, pd.Series] = {}
        for aname in asset_names:
            for sname in SYSTEM_NAMES:
                m = per_asset[aname][sname]["metrics"]
                sharpe_rows.append({"asset": aname, "system": sname, "sharpe": m["sharpe"]})
                speed_rows.append({
                    "asset": aname, "system": sname,
                    "label": f"{aname[:6]} {sname}",
                    "sharpe": m["sharpe"], "sortino": m["sortino"],
                    "ann_ret": m["ann_ret"],
                })
                all_ret_cols[f"{aname[:6]} {sname}"] = per_asset[aname][sname]["net_ret"]
        sharpe_df = pd.DataFrame(sharpe_rows)
        speed_df = pd.DataFrame(speed_rows)
        all_corr = pd.concat(all_ret_cols, axis=1).dropna().corr() if all_ret_cols else pd.DataFrame()

        # ── Choose best-system-per-asset (default: highest Sharpe) ─────────────
        best_per_asset: dict[str, str] = {}
        for aname in asset_names:
            override = params.best_systems.get(aname)
            if override and override in SYSTEM_NAMES:
                best_per_asset[aname] = override
                continue
            best = max(
                SYSTEM_NAMES,
                key=lambda s: per_asset[aname][s]["metrics"]["sharpe"],
            )
            best_per_asset[aname] = best

        # ── Portfolio ───────────────────────────────────────────────────────────
        best_rets = {a: per_asset[a][best_per_asset[a]]["net_ret"] for a in asset_names}
        eq_ret, iv_ret, dropped_portfolio, aligned_best_rets = _build_portfolio(best_rets)
        eq_eq = np.exp(eq_ret.cumsum()) if not eq_ret.empty else pd.Series(dtype=float)
        iv_eq = np.exp(iv_ret.cumsum()) if not iv_ret.empty else pd.Series(dtype=float)
        eq_dd = eq_eq / eq_eq.cummax() - 1 if not eq_eq.empty else pd.Series(dtype=float)
        iv_dd = iv_eq / iv_eq.cummax() - 1 if not iv_eq.empty else pd.Series(dtype=float)
        eq_m = _trend_metrics(eq_ret)
        iv_m = _trend_metrics(iv_ret)

        # Best-system correlation on the **same dates** used for the portfolio combo
        best_corr = (
            aligned_best_rets.corr()
            if not aligned_best_rets.empty and aligned_best_rets.shape[1] >= 2
            else pd.DataFrame()
        )

        # Pain table — for EW combo (falls back to first asset if empty)
        pain_eq = eq_eq
        pain_dd = eq_dd
        if pain_eq.empty and asset_names:
            first_name = asset_names[0]
            pain_eq = per_asset[first_name][best_per_asset[first_name]]["eq"]
            pain_dd = per_asset[first_name][best_per_asset[first_name]]["dd"]
        pain_df = _top_drawdowns(pain_eq, n=5)

        # ── Global metric strip ────────────────────────────────────────────────
        global_metrics = [
            Metric(key="n_assets",    label="Assets",     value=float(len(asset_names)), format="number"),
            Metric(key="ew_sharpe",   label="EW Sharpe",  value=eq_m["sharpe"],  format="ratio"),
            Metric(key="iv_sharpe",   label="IV Sharpe",  value=iv_m["sharpe"],  format="ratio"),
            Metric(key="ew_dd",       label="EW Max DD",  value=eq_m["max_dd"],  format="percent"),
            Metric(key="iv_dd",       label="IV Max DD",  value=iv_m["max_dd"],  format="percent"),
            Metric(key="ew_ret",      label="EW Ann Ret", value=eq_m["ann_ret"], format="percent"),
            Metric(key="iv_ret",      label="IV Ann Ret", value=iv_m["ann_ret"], format="percent"),
        ]

        # ── Tabs ───────────────────────────────────────────────────────────────
        tab_signals = TabSpec(
            id="signals",
            title="Signals",
            icon="📉",
            intro_md=_SIGNALS_GUIDE_MD,
            charts=[
                ChartSpec(
                    id="signal-chart",
                    title=f"{signal_asset} — {signal_system}",
                    description=(
                        "Green shading = long (+1), red = short (−1). "
                        "Change asset or system in the sidebar. "
                        f"TC: **{params.tc_bps:g} bp** · MA type: **{'EMA' if params.use_ema else 'SMA'}**."
                    ),
                    figure=signal_chart,
                ),
            ],
        )

        equity_chart_specs = [
            ChartSpec(
                id=f"equity-{_chart_id_slug(aname)}",
                title=f"{aname} — system equity curves",
                description=(
                    "All four systems on one chart for this asset. "
                    "Curves re-based to 1.0 at the first in-window date after burn-in."
                ),
                figure=_chart_single_asset_equity(aname, per_asset[aname]),
            )
            for aname in asset_names
        ]
        tab_backtest = TabSpec(
            id="backtest",
            title="Backtest",
            icon="🔁",
            intro_md=_BACKTEST_GUIDE_MD,
            charts=[
                *equity_chart_specs,
                ChartSpec(
                    id="sharpe-bars",
                    title="Sharpe Ratio by System × Asset",
                    description="Look for a monotone pattern (10/30 → 80/160) — the speed-decay tell.",
                    figure=_chart_sharpe_bar(sharpe_df),
                ),
            ],
            tables=[_table_metrics(asset_names, per_asset)],
        )

        best_info = " · ".join(f"**{a}** → {s}" for a, s in best_per_asset.items())
        tab_portfolio = TabSpec(
            id="portfolio",
            title="Portfolio",
            icon="💼",
            intro_md=_PORTFOLIO_GUIDE_MD,
            charts=[
                ChartSpec(
                    id="portfolio-equity",
                    title="Equal Weight vs Inverse Volatility Weight",
                    description=f"Best system per asset: {best_info}",
                    figure=_chart_portfolio_equity(eq_eq, iv_eq),
                ),
                ChartSpec(
                    id="portfolio-drawdown",
                    title="Portfolio drawdown",
                    figure=_chart_portfolio_drawdown(eq_dd, iv_dd),
                ),
                ChartSpec(
                    id="best-system-corr",
                    title="Best-system-per-asset correlation",
                    description=(
                        "Near-zero cross-asset correlations confirm the diversification "
                        "story: the combo equity curve should be smoother than any individual."
                    ),
                    figure=_chart_correlation_heatmap(
                        best_corr, "Best-system-per-asset return correlation"
                    ),
                ),
            ],
        )

        insights_charts: list[ChartSpec] = [
            ChartSpec(
                id="speed-decay-sharpe",
                title="Speed decay — Sharpe by system speed",
                description=(
                    "Group by asset and compare across systems. Decreasing left-to-right "
                    "(10/30 → 80/160) = speed decay is real here."
                ),
                guide_md=_INSIGHTS_SPEED_MD,
                figure=_chart_speed_decay_bar(speed_df, asset_names),
            ),
            ChartSpec(
                id="speed-decay-sortino",
                title="Sortino by system speed",
                description="Same picture but on downside-only risk adjustment.",
                figure=_chart_sortino_line(speed_df, asset_names),
            ),
            ChartSpec(
                id="diversification-overlay",
                title="Individual best systems vs equal-weight combo",
                description=(
                    "Dotted lines = each asset's best system. Thick grey = equal-weight combo. "
                    "The combo should be smoother than any individual."
                ),
                guide_md=_INSIGHTS_DIVERSIFICATION_MD,
                figure=_chart_diversification_overlay(
                    per_asset, best_per_asset, eq_eq, asset_names
                ),
            ),
            ChartSpec(
                id="full-corr-matrix",
                title="Full correlation matrix — every asset × system combo",
                description=(
                    "Useful for picking combinations that aren't redundant. Near-zero cross-cells "
                    "= good. Clumps of ρ ≈ 1 = these systems move together; no free diversification."
                ),
                figure=_chart_correlation_heatmap(
                    all_corr, "All system-pair return correlations", text_size=8
                ),
            ),
            ChartSpec(
                id="pain-drawdown",
                title="Portfolio drawdown with −10% / −20% reference lines",
                description=(
                    "Lines at −10% and −20% mark 'painful' and 'redemptions accelerate' territory "
                    "for institutional clients."
                ),
                guide_md=_INSIGHTS_PAIN_MD,
                figure=_chart_pain_drawdown(pain_dd),
            ),
            ChartSpec(
                id="sharpe-vs-sortino-bars",
                title="Sharpe vs Sortino — every asset × system",
                description=(
                    "Taller green bar = more asymmetric upside. Breakout systems should show "
                    "the biggest gap."
                ),
                guide_md=_INSIGHTS_SORTINO_MD,
                figure=_chart_sharpe_vs_sortino(speed_df),
            ),
            ChartSpec(
                id="sharpe-sortino-scatter",
                title="Scatter: Sharpe vs Sortino",
                description=(
                    "Points above the diagonal = good asymmetry. Breakout systems should cluster "
                    "furthest above."
                ),
                figure=_chart_sharpe_sortino_scatter(speed_df),
            ),
        ]

        insights_tables = [_table_pain(pain_df)] if not pain_df.empty else []

        tab_insights = TabSpec(
            id="insights",
            title="Insights",
            icon="🔬",
            intro_md=(
                "**Deeper diagnostics:** speed decay, diversification benefit, drawdown pain, "
                "and why Sortino tells a different story to Sharpe for trend-followers. "
                "Each chart below has its own plain-language guide."
            ),
            charts=insights_charts,
            tables=insights_tables,
        )

        warnings: list[str] = list(skipped)
        if dropped_portfolio:
            warnings.append(
                "Portfolio & combo metrics use only assets that share at least one common "
                "trading day with every other included asset. Excluded (no overlap with the "
                "rest of the basket, dropping earliest-ending series first): "
                + ", ".join(dropped_portfolio)
            )
        return StrategyResult(
            overview_md=_OVERVIEW_MD,
            metrics=global_metrics,
            tabs=[tab_signals, tab_backtest, tab_portfolio, tab_insights],
            warnings=warnings,
        )


STRATEGY = TrendFollowingStrategy()
