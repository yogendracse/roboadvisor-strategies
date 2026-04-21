"""Counter Trend strategy plugin — Strategy Learnings section.

Six tabs covering the lecture material on counter-trend / mean-reversion approaches:

  1. 📐 Range Exhaustion  — P×AvgRange retrace entry, long & short, P sensitivity
  2. 🕯️  Doji Detection    — candle pattern classification with Bollinger Band confirmation
  3. 📊 Spread System     — Z-score mean reversion on price vs rolling mean
  4. 📉 Drawdown Entry    — tier-based accumulation at -25 / -33 % drawdown
  5. 🧱 Renko             — time-independent brick chart with counter-trend signals
  6. 🤖 ML Enhancement    — educational placeholder for ML-based signal scoring

Data: backend/data/counter-trend/COUNTER_TREND_DATA.xlsx
      S&P 500 futures OHLC + roll-adjusted columns, 2003-07-01 → 2021-02-04
"""

from __future__ import annotations

import json
from datetime import date

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from pydantic import BaseModel, Field

from app.core.config import BACKEND_ROOT
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
from app.strategies.base import BaseStrategy

# ─── Data path ────────────────────────────────────────────────────────────────

COUNTER_TREND_XLSX = BACKEND_ROOT / "data" / "counter-trend" / "COUNTER_TREND_DATA.xlsx"

# ─── Colours ──────────────────────────────────────────────────────────────────

C_LONG  = "#2E7D32"   # dark green  (long / bullish)
C_SHORT = "#C62828"   # dark red    (short / bearish)
C_BH    = PALETTE["bh"]      # #546E7A  steel blue
C_STRAT = PALETTE["strat"]   # #D84315  burnt orange
C_DOJI  = "#7B1FA2"   # purple (Doji standard)
C_GY    = "#C62828"   # graveyard → bearish
C_DF    = "#2E7D32"   # dragonfly → bullish


def _fig_to_dict(fig: go.Figure) -> dict:
    return json.loads(fig.to_json())


# ─── Data loading ─────────────────────────────────────────────────────────────


def _load_ohlc() -> pd.DataFrame:
    """Load and clean the OHLC sheet from COUNTER_TREND_DATA.xlsx."""
    df = pd.read_excel(COUNTER_TREND_XLSX, sheet_name="data+analysis", header=1)
    df["#Date"] = pd.to_numeric(df["#Date"], errors="coerce")
    df = df[df["#Date"].notna() & (df["#Date"] > 19_000_101)].copy()
    df["Date"] = pd.to_datetime(df["#Date"].astype(int).astype(str), format="%Y%m%d")
    df = df.sort_values("Date").reset_index(drop=True)
    df["Roll"] = pd.to_numeric(df["Roll"], errors="coerce").fillna(0.0)
    for col in ("Open", "High", "Low", "Close"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["Open", "High", "Low", "Close"]).reset_index(drop=True)
    return df[["Date", "Open", "High", "Low", "Close", "Roll"]]


def _filter_dates(df: pd.DataFrame, date_start, date_end) -> pd.DataFrame:
    if date_start:
        df = df[df["Date"] >= pd.to_datetime(date_start)]
    if date_end:
        df = df[df["Date"] <= pd.to_datetime(date_end)]
    return df.reset_index(drop=True)


# ─── Maths helpers ────────────────────────────────────────────────────────────


def _sharpe(returns: pd.Series, ann: int = 252) -> float:
    r = returns.dropna()
    if len(r) < 2 or r.std() == 0:
        return 0.0
    return float(r.mean() / r.std() * np.sqrt(ann))


def _max_dd(equity: pd.Series) -> float:
    if equity.empty:
        return 0.0
    peak = equity.cummax()
    return float(((equity - peak) / peak).min())


def _ann_return(equity: pd.Series, ann: int = 252) -> float:
    if len(equity) < 2 or equity.iloc[0] <= 0:
        return 0.0
    total = equity.iloc[-1] / equity.iloc[0]
    if total <= 0:
        return 0.0
    return float(total ** (ann / len(equity)) - 1)


def _equity_from_returns(rets: pd.Series, fill_zero: bool = True, start: float = 100.0) -> pd.Series:
    r = rets.fillna(0) if fill_zero else rets.dropna()
    return (1 + r).cumprod() * start


# ─── Markdown guides ──────────────────────────────────────────────────────────

_RE_GUIDE = """
## Range Exhaustion — How it works

**Concept**: Markets often over-extend intraday and then retrace. The Range Exhaustion system
sells that over-extension. On each day we define an *entry level* **L** below the previous
session's high. If the market pulls back down to L during the day, we buy at L and exit at
the close.

**Key formula**
```
A   = 20-day trailing average of (High − Low)   ← average daily range
L   = PrvHiWRoll − P × A                        ← entry level for long
```
- **PrvHiWRoll** = previous day's High adjusted for any futures roll
  (`PrvHiWRoll[t] = High[t-1] + Roll[t-1]`)
- **P** is the retrace multiplier — the single configurable parameter. Higher P = deeper
  retrace required = fewer but higher-quality signals.

**Signal logic**
| Event | Action |
|---|---|
| `Low[t] ≤ L` | Enter long at L, exit at Close[t] |
| `Low[t] > L` | No trade today |

**Short side**: mirror image — entry = `PrvLoWRoll + P × A`, enter short if `High ≥ level`.

**Sharpe variants**
*Zero method*: non-signal days counted as 0 return (penalises dead capital).
*Blank method*: only signal days in the Sharpe calculation (raw trade-by-trade quality).

**Roll handling**: On futures roll days the previous contract's high is adjusted by the roll
differential so the entry level is comparable to today's prices. Days with zero true range are
excluded from the 20-day average to avoid distortion.
"""

_DOJI_GUIDE = """
## Doji Detection — How it works

A **Doji** is a candle where open ≈ close — the market was indecisive for the session.
After a trending move, a Doji signals potential exhaustion and reversal.

**Classification**
| Type | Rule | Bias |
|---|---|---|
| Standard Doji | Body < ε_OC × Range | Neutral reversal |
| Graveyard | Doji + lower wick < ε_GW × Range + large upper wick | Bearish |
| Dragonfly | Doji + upper wick < ε_DF × Range + large lower wick | Bullish |

**Filters applied**
1. **Trend context**: only act on a Doji if the prior *N* days trended consistently in one
   direction — a Doji after a flat period has no reversal meaning.
2. **Bollinger Band confirmation**: a Doji at the outer band (body touching Upper or Lower BB)
   is a stronger signal than one in the middle of the range.

**Trade mechanics**
- Entry: open of the next session (T+1)
- Exit: close of the same session (T+1) — one-day holding period
- Dragonfly → long; Graveyard → short; Standard Doji → fade the prior trend
"""

_PAIRS_GUIDE = """
## Spread / Mean-Reversion — How it works

Rather than two separate instruments, this tab applies the pairs-trading *Z-score framework*
to a single price series vs its own rolling trend:

```
Spread   = Close − Rolling_Mean(Close, window)
Z-score  = (Spread − mean(Spread)) / std(Spread)
```

When `Z < −threshold` the price is unusually far below its recent trend → **long entry**.
When `Z > +threshold` the price is unusually far above it → **short entry**.
Exit when Z reverts to 0.

This is equivalent to a Bollinger Band breakout system applied to deviations from the
rolling mean — it captures the same mean-reversion thesis as a traditional pairs trade
but on a single instrument.

**Mean-reversion test**: we regress `ΔSpread[t]` on `Spread[t-1]`. A negative slope
coefficient confirms the spread is mean-reverting (the Dickey-Fuller principle). The
half-life of mean reversion is `−ln(2) / slope`.

In a full pairs implementation you would select two co-integrated instruments (e.g. VOO vs QQQ),
align them, compute the log-price spread, and run the same Z-score logic.
"""

_DD_GUIDE = """
## Long-Term Drawdown Entry — How it works

The lecture shows that patient accumulation *during* large drawdowns has historically produced
superior long-run returns. This system defines structured entry tiers:

| Tier | Drawdown Threshold | Allocation |
|---|---|---|
| Tier 1 | −25 % from rolling peak | 50 % of capital |
| Tier 2 | −33 % from rolling peak | Remaining 50 % |

**Rolling peak** = highest closing price over the full history to date (all-time high).

**Metrics tracked per drawdown event**
- Start of drawdown (first day below prior high)
- Trough date and price
- Tier breach dates
- Recovery date (first new all-time high)
- Return from each tier entry to recovery
- Days to recover

The S&P 500 futures data (2003–2021) captures two major drawdown events: the 2008–2009 bear
market (−57 % trough) and the 2020 COVID crash (−34 % trough). Both breach both tiers.

**Current status panel**: shows today's distance from each tier, helping you identify when
the system is close to triggering.
"""

_RENKO_GUIDE = """
## Renko — Time-Independent Methods

Renko charts filter out noise by only adding a new brick when price moves a fixed *brick size*
in one direction, ignoring time entirely. This makes trend and reversal signals cleaner.

**Brick construction**
```
If Close ≥ last_top + brick_size  → add UP brick
If Close ≤ last_bottom − brick_size → add DOWN brick
Otherwise → no new brick
```

**ATR-based brick size**: brick_size = ATR(N) × multiplier, recalculated at the start of the
backtest. This adapts the brick size to the instrument's volatility.

**Counter-trend signal**: after *N* consecutive same-direction bricks, the *first reversal brick*
triggers a counter-trend trade in the opposite direction.
- After N down-bricks → first up-brick = LONG entry
- After N up-bricks → first down-brick = SHORT entry
- Exit: when the next reversal brick forms

**Sensitivity analysis**: as you increase the minimum brick count N (trend length required before
acting), fewer but higher-quality signals are produced.
"""

_ML_GUIDE = """
## ML Signal Enhancement — Forward-Looking Tab

This tab outlines the natural ML extension of the five rule-based counter-trend systems.
Rather than fixed parameter thresholds (P = 2.2, ε = 5 %, Z = 2), an ML model *learns*
which combinations of features produce reliable reversals.

### Feature inputs

| Feature | Source tab |
|---|---|
| Z-score of Close vs rolling mean | Spread tab |
| Drawdown depth (% from ATH) | Drawdown tab |
| Renko consecutive brick count | Renko tab |
| Doji type classification | Doji tab |
| 20-day average range (A) | Range Exhaustion tab |
| Rolling vol z-score (zvol20) | Volatility Analysis strategy |
| Rolling correlation (60-day) | Spread tab |
| Day of week, distance from recent high/low | Derived |
| Recent return momentum (5-day, 20-day) | Derived |

### Target variable

Binary: did the counter-trend trade on this day produce a **positive return by close**?

### What to build

1. **Feature importance chart** — which inputs the model weights most
2. **Predicted probability** of counter-trend success for the most recent date (live score)
3. **Precision/recall** tradeoff at different probability thresholds
4. **ML-enhanced Sharpe** vs rule-based Sharpe across all tabs — does ML improve signal quality?

### Why ML helps here

Rule-based systems use fixed thresholds that don't adapt to regime. A rising-rate environment
or a high-volatility regime may shift which P value is optimal. An ML model conditioned on
regime features (vol quintile, correlation state) can dynamically adjust signal strength.
"""


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 1 — RANGE EXHAUSTION
# ═══════════════════════════════════════════════════════════════════════════════


def _compute_re(df: pd.DataFrame, P: float) -> pd.DataFrame:
    """Compute range exhaustion signals for both long and short sides."""
    df = df.copy()
    # Zero-range days excluded from the 20-day average
    rng = (df["High"] - df["Low"]).copy()
    rng[rng == 0] = np.nan
    df["Av20R"] = rng.rolling(20).mean()
    # Roll-adjusted prior high/low
    df["PrvHiWRoll"] = (df["High"] + df["Roll"]).shift(1)
    df["PrvLoWRoll"] = (df["Low"] + df["Roll"]).shift(1)
    df = df.dropna(subset=["Av20R", "PrvHiWRoll"]).reset_index(drop=True)

    df["L_Long"]  = df["PrvHiWRoll"] - P * df["Av20R"]
    df["L_Short"] = df["PrvLoWRoll"] + P * df["Av20R"]
    df["Hit_Long"]  = df["Low"]  <= df["L_Long"]
    df["Hit_Short"] = df["High"] >= df["L_Short"]

    df["Ret_Long"] = np.where(
        df["Hit_Long"],
        (df["Close"] - df["L_Long"]) / df["L_Long"].replace(0, np.nan),
        np.nan,
    )
    df["Ret_Short"] = np.where(
        df["Hit_Short"],
        (df["L_Short"] - df["Close"]) / df["L_Short"].replace(0, np.nan),
        np.nan,
    )
    df["Ret_BH"] = df["Close"].pct_change()
    return df


def _tab_range_exhaustion(df_raw: pd.DataFrame, params) -> TabSpec:
    P = params.p_value
    df = _compute_re(df_raw, P)
    dates = df["Date"].dt.strftime("%Y-%m-%d").tolist()

    # ── Core metrics ──────────────────────────────────────────────────────────
    hits = df["Hit_Long"]
    sig_rets = df["Ret_Long"].dropna()
    total_days = len(df)
    signal_days = int(hits.sum())
    hit_rate = signal_days / total_days if total_days else 0.0
    avg_ret = float(sig_rets.mean()) if len(sig_rets) else 0.0
    win_rate = float((sig_rets > 0).mean()) if len(sig_rets) else 0.0

    rets_zero  = df["Ret_Long"].fillna(0)
    sharpe_zero  = _sharpe(rets_zero)
    sharpe_blank = _sharpe(sig_rets)
    bh_sharpe  = _sharpe(df["Ret_BH"])

    strat_eq = _equity_from_returns(df["Ret_Long"])
    bh_eq    = _equity_from_returns(df["Ret_BH"])
    strat_mdd = _max_dd(strat_eq)
    bh_mdd    = _max_dd(bh_eq)
    strat_ann = _ann_return(strat_eq)
    bh_ann    = _ann_return(bh_eq)

    # Current signal (last available date)
    last = df.iloc[-1]
    curr_signal = "LONG" if last["Hit_Long"] else ("SHORT" if last["Hit_Short"] else "NEUTRAL")

    metrics = [
        Metric(key="hit_rate",    label="Hit Rate",             value=hit_rate,    format="percent"),
        Metric(key="signal_days", label="Signal Days",           value=float(signal_days), format="number"),
        Metric(key="total_days",  label="Total Trading Days",    value=float(total_days),  format="number"),
        Metric(key="avg_ret",     label="Avg Return / Signal",  value=avg_ret,     format="percent"),
        Metric(key="win_rate",    label="Win Rate (signal days)",value=win_rate,    format="percent"),
        Metric(key="sharpe_zero", label="Sharpe (zero method)",  value=sharpe_zero, format="ratio"),
        Metric(key="sharpe_blank",label="Sharpe (blank method)", value=sharpe_blank,format="ratio"),
        Metric(key="bh_sharpe",   label="B&H Sharpe",            value=bh_sharpe,   format="ratio"),
        Metric(key="strat_mdd",   label="Max Drawdown (strat)",  value=strat_mdd,   format="percent"),
        Metric(key="bh_mdd",      label="Max Drawdown (B&H)",    value=bh_mdd,      format="percent"),
        Metric(key="strat_ann",   label="Ann. Return (strat)",   value=strat_ann,   format="percent"),
        Metric(key="bh_ann",      label="Ann. Return (B&H)",     value=bh_ann,      format="percent"),
    ]

    # ── Chart 1: Equity curves + drawdown ────────────────────────────────────
    fig_eq = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        row_heights=[0.68, 0.32], vertical_spacing=0.03,
        subplot_titles=("Equity (rebased to 100)", "Drawdown %"),
    )
    fig_eq.add_trace(go.Scatter(
        x=dates, y=strat_eq.tolist(),
        name=f"Counter-Trend (P={P})", line=dict(color=C_STRAT, width=1.8),
    ), row=1, col=1)
    fig_eq.add_trace(go.Scatter(
        x=dates, y=bh_eq.tolist(),
        name="Buy & Hold", line=dict(color=C_BH, width=1.8),
    ), row=1, col=1)

    strat_dd = ((strat_eq - strat_eq.cummax()) / strat_eq.cummax() * 100).tolist()
    bh_dd    = ((bh_eq    - bh_eq.cummax())    / bh_eq.cummax()    * 100).tolist()
    fig_eq.add_trace(go.Scatter(
        x=dates, y=strat_dd, name="Strat DD",
        fill="tozeroy", line=dict(color=C_STRAT, width=0),
        fillcolor="rgba(216,67,21,0.20)", showlegend=False,
    ), row=2, col=1)
    fig_eq.add_trace(go.Scatter(
        x=dates, y=bh_dd, name="B&H DD",
        fill="tozeroy", line=dict(color=C_BH, width=0),
        fillcolor="rgba(84,110,122,0.20)", showlegend=False,
    ), row=2, col=1)
    fig_eq.update_layout(
        height=500, template="plotly_white",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    )

    # ── Chart 2: P-sensitivity (dual axis) ───────────────────────────────────
    p_vals = np.round(np.arange(0.8, 2.41, 0.2), 1)
    s_zero, s_blank, n_sigs = [], [], []
    for pv in p_vals:
        tmp = _compute_re(df_raw, float(pv))
        z = tmp["Ret_Long"].fillna(0)
        b = tmp["Ret_Long"].dropna()
        s_zero.append(_sharpe(z))
        s_blank.append(_sharpe(b))
        n_sigs.append(int(tmp["Hit_Long"].sum()))

    fig_p = make_subplots(specs=[[{"secondary_y": True}]])
    fig_p.add_trace(go.Bar(
        x=p_vals.tolist(), y=n_sigs,
        name="# Signals", marker_color="rgba(84,110,122,0.35)",
        showlegend=True,
    ), secondary_y=True)
    fig_p.add_trace(go.Scatter(
        x=p_vals.tolist(), y=s_zero,
        name="Sharpe (zero)", line=dict(color=C_STRAT, width=2.5),
        mode="lines+markers", marker=dict(size=7),
    ), secondary_y=False)
    fig_p.add_trace(go.Scatter(
        x=p_vals.tolist(), y=s_blank,
        name="Sharpe (blank)", line=dict(color=C_LONG, width=2.5, dash="dash"),
        mode="lines+markers", marker=dict(size=7),
    ), secondary_y=False)
    fig_p.update_xaxes(title_text="P value")
    fig_p.update_yaxes(title_text="Sharpe Ratio", secondary_y=False)
    fig_p.update_yaxes(title_text="Signal Count", secondary_y=True)
    fig_p.update_layout(
        height=420, template="plotly_white",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    )

    # ── Chart 3: Signal map ───────────────────────────────────────────────────
    hit_df = df[df["Hit_Long"]].copy()
    fig_sig = go.Figure()
    fig_sig.add_trace(go.Scatter(
        x=dates, y=df["Close"].tolist(),
        name="Close", line=dict(color=C_BH, width=1),
    ))
    fig_sig.add_trace(go.Scatter(
        x=hit_df["Date"].dt.strftime("%Y-%m-%d").tolist(),
        y=hit_df["L_Long"].tolist(),
        name=f"Long Entry (L, P={P})",
        mode="markers", marker=dict(color=C_LONG, size=4, symbol="circle"),
    ))
    fig_sig.update_layout(
        height=400, template="plotly_white",
        yaxis_title="Price",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    )

    # ── Chart 4: 2×2 contingency heatmap ────────────────────────────────────
    sig_df = df[df["Hit_Long"]].dropna(subset=["Ret_Long", "Ret_BH"])
    strat_pos = sig_df["Ret_Long"] > 0
    mkt_pos   = sig_df["Ret_BH"]   > 0
    quads = {
        ("Strat +", "Mkt +"): sig_df[ strat_pos &  mkt_pos],
        ("Strat +", "Mkt −"): sig_df[ strat_pos & ~mkt_pos],
        ("Strat −", "Mkt +"): sig_df[~strat_pos &  mkt_pos],
        ("Strat −", "Mkt −"): sig_df[~strat_pos & ~mkt_pos],
    }
    z_mat, t_mat = [], []
    for row_lbl in ("Strat +", "Strat −"):
        row_z, row_t = [], []
        for col_lbl in ("Mkt +", "Mkt −"):
            cell = quads[(row_lbl, col_lbl)]
            n = len(cell)
            pnl = float(cell["Ret_Long"].sum() * 100)
            row_z.append(pnl)
            row_t.append(f"n={n}<br>PnL={pnl:+.1f}%")
        z_mat.append(row_z)
        t_mat.append(row_t)
    fig_hm = go.Figure(go.Heatmap(
        z=z_mat, x=["Mkt +", "Mkt −"], y=["Strat +", "Strat −"],
        text=t_mat, texttemplate="%{text}",
        colorscale=[[0, C_SHORT], [0.5, "#FFFFFF"], [1, C_LONG]], zmid=0,
        showscale=True,
    ))
    fig_hm.update_layout(
        height=350, template="plotly_white",
        xaxis_title="Market Direction", yaxis_title="Strategy Direction",
    )

    # ── Chart 5: Short-side equity ────────────────────────────────────────────
    short_rets   = df["Ret_Short"]
    short_eq     = _equity_from_returns(short_rets)
    short_sh_z   = _sharpe(short_rets.fillna(0))
    short_sh_b   = _sharpe(short_rets.dropna())
    short_n      = int(df["Hit_Short"].sum())
    short_dd_vals = ((short_eq - short_eq.cummax()) / short_eq.cummax() * 100).tolist()

    fig_sh = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        row_heights=[0.68, 0.32], vertical_spacing=0.03,
        subplot_titles=("Short Counter-Trend Equity", "Drawdown %"),
    )
    fig_sh.add_trace(go.Scatter(
        x=dates, y=short_eq.tolist(),
        name=f"Short CT (P={P})", line=dict(color=C_SHORT, width=1.8),
    ), row=1, col=1)
    fig_sh.add_trace(go.Scatter(
        x=dates, y=bh_eq.tolist(),
        name="Buy & Hold", line=dict(color=C_BH, width=1.8),
    ), row=1, col=1)
    fig_sh.add_trace(go.Scatter(
        x=dates, y=short_dd_vals, fill="tozeroy",
        line=dict(color=C_SHORT, width=0),
        fillcolor="rgba(198,40,40,0.20)", showlegend=False,
    ), row=2, col=1)
    fig_sh.update_layout(
        height=460, template="plotly_white",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    )

    # ── P sensitivity table ───────────────────────────────────────────────────
    p_table = [
        {"p": float(pv), "sharpe_zero": round(sz, 3),
         "sharpe_blank": round(sb, 3), "signals": ns}
        for pv, sz, sb, ns in zip(p_vals, s_zero, s_blank, n_sigs)
    ]

    return TabSpec(
        id="range-exhaustion",
        title="📐 Range Exhaustion",
        intro_md=_RE_GUIDE,
        metrics=metrics,
        charts=[
            ChartSpec(
                id="re-equity", title="Equity Curves — Strategy vs Buy & Hold",
                description=(
                    f"P = {P}. Zero method (non-signal days = 0 return). "
                    f"Strat Sharpe: {sharpe_zero:.2f} | B&H Sharpe: {bh_sharpe:.2f}. "
                    f"Current signal as of last data date: **{curr_signal}**."
                ),
                figure=_fig_to_dict(fig_eq),
            ),
            ChartSpec(
                id="re-sensitivity", title="P Sensitivity — Sharpe vs Signal Count",
                description=(
                    "Bars (right axis) = number of signals triggered. "
                    "Lines (left axis) = Sharpe ratio. Higher P → fewer, deeper retraces."
                ),
                figure=_fig_to_dict(fig_p),
            ),
            ChartSpec(
                id="re-signal-map", title="Signal Map — Long Entry Points",
                description=f"Green dots mark where Low ≤ L (entry level). P = {P}.",
                figure=_fig_to_dict(fig_sig),
            ),
            ChartSpec(
                id="re-contingency", title="2×2 Contingency Matrix (Signal Days Only)",
                description=(
                    "Quadrant breakdown of signal-day outcomes. "
                    "n = trade count, PnL = sum of returns for that quadrant."
                ),
                figure=_fig_to_dict(fig_hm),
            ),
            ChartSpec(
                id="re-short", title="Short Side — Symmetric Counter-Trend",
                description=(
                    f"Enter short when High ≥ PrvLoWRoll + P×A. Exit at close. P = {P}. "
                    f"Signals: {short_n} | Sharpe (zero): {short_sh_z:.2f} | Sharpe (blank): {short_sh_b:.2f}."
                ),
                figure=_fig_to_dict(fig_sh),
            ),
        ],
        tables=[
            TableSpec(
                id="re-p-table", title="P Sensitivity — Full Table",
                description="Sharpe ratio and signal count for each P value in the sweep.",
                columns=[
                    ColumnSpec(key="p",            label="P",             format="number", align="right"),
                    ColumnSpec(key="sharpe_zero",  label="Sharpe (zero)", format="ratio",  align="right"),
                    ColumnSpec(key="sharpe_blank", label="Sharpe (blank)",format="ratio",  align="right"),
                    ColumnSpec(key="signals",      label="# Signals",     format="number", align="right"),
                ],
                rows=p_table,
            ),
        ],
    )


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 2 — DOJI DETECTION
# ═══════════════════════════════════════════════════════════════════════════════


def _tab_doji(df_raw: pd.DataFrame, params) -> TabSpec:
    eps_oc = params.epsilon_oc
    eps_gw = params.epsilon_gw
    eps_df = params.epsilon_df
    n_trend = params.trend_length
    bb_win  = params.bb_window
    bb_std  = params.bb_std

    df = df_raw.copy()
    df["Body"]  = (df["Close"] - df["Open"]).abs()
    df["Upper"] = df["High"] - df[["Open", "Close"]].max(axis=1)
    df["Lower"] = df[["Open", "Close"]].min(axis=1) - df["Low"]
    df["Range"] = df["High"] - df["Low"]

    safe_range = df["Range"].replace(0, np.nan)
    df["IsDoji"]      = df["Body"] < eps_oc * safe_range
    df["IsGraveyard"] = (
        df["IsDoji"]
        & (df["Lower"] < eps_gw * safe_range)
        & (df["Upper"] > 0.5 * safe_range)
    )
    df["IsDragonfly"] = (
        df["IsDoji"]
        & (df["Upper"] < eps_df * safe_range)
        & (df["Lower"] > 0.5 * safe_range)
    )
    df["IsStd"] = df["IsDoji"] & ~df["IsGraveyard"] & ~df["IsDragonfly"]

    # Trend context: last N days all up (or all down)
    df["DailyRet"] = df["Close"].pct_change()
    up_cols = []
    for k in range(1, n_trend + 1):
        col = f"_up{k}"
        df[col] = df["DailyRet"].shift(k) > 0
        up_cols.append(col)
    df["TrendUp"] = df[up_cols].all(axis=1)
    df["TrendDn"] = (~df[up_cols]).all(axis=1)

    # Bollinger Bands
    df["BB_MA"]  = df["Close"].rolling(bb_win).mean()
    df["BB_Std"] = df["Close"].rolling(bb_win).std()
    df["BB_Hi"]  = df["BB_MA"] + bb_std * df["BB_Std"]
    df["BB_Lo"]  = df["BB_MA"] - bb_std * df["BB_Std"]
    df["AtBBHi"] = df["High"] >= df["BB_Hi"]
    df["AtBBLo"] = df["Low"]  <= df["BB_Lo"]

    # Signals
    df["Sig_GY"] = df["IsGraveyard"] & df["TrendUp"]  # short
    df["Sig_DF"] = df["IsDragonfly"] & df["TrendDn"]  # long
    df["Sig_Std_Short"] = df["IsStd"] & df["TrendUp"]
    df["Sig_Std_Long"]  = df["IsStd"] & df["TrendDn"]

    # Returns: entry at T+1 open, exit at T+1 close
    df["Next_Open"]  = df["Open"].shift(-1)
    df["Next_Close"] = df["Close"].shift(-1)

    def _ret_long(mask: pd.Series) -> pd.Series:
        ent = df["Next_Open"].where(mask)
        ext = df["Next_Close"].where(mask)
        return ((ext - ent) / ent.replace(0, np.nan)).where(mask)

    def _ret_short(mask: pd.Series) -> pd.Series:
        ent = df["Next_Open"].where(mask)
        ext = df["Next_Close"].where(mask)
        return ((ent - ext) / ent.replace(0, np.nan)).where(mask)

    df["Ret_DF"]        = _ret_long(df["Sig_DF"])
    df["Ret_GY"]        = _ret_short(df["Sig_GY"])
    df["Ret_Std_Long"]  = _ret_long(df["Sig_Std_Long"])
    df["Ret_Std_Short"] = _ret_short(df["Sig_Std_Short"])

    # ── Win rates by type ──────────────────────────────────────────────────────
    def _stats(rets: pd.Series, label: str) -> dict:
        r = rets.dropna()
        return {
            "type": label,
            "count": len(r),
            "win_rate": round(float((r > 0).mean()) if len(r) else 0.0, 3),
            "avg_ret":  round(float(r.mean()) if len(r) else 0.0, 5),
            "sharpe":   round(_sharpe(r), 3),
        }

    stats_rows = [
        _stats(df["Ret_DF"],        "Dragonfly (bullish)"),
        _stats(df["Ret_GY"],        "Graveyard (bearish)"),
        _stats(df["Ret_Std_Long"],  "Std Doji → Long"),
        _stats(df["Ret_Std_Short"], "Std Doji → Short"),
    ]

    # BB-confirmation vs no-BB for Dragonfly
    df_bb_long  = df["Sig_DF"] & df["AtBBLo"]
    df_no_bb_long = df["Sig_DF"] & ~df["AtBBLo"]
    bb_stats = [
        _stats(_ret_long(df_bb_long),   "Dragonfly + BB Touch"),
        _stats(_ret_long(df_no_bb_long),"Dragonfly No BB"),
    ]
    df_bb_short  = df["Sig_GY"] & df["AtBBHi"]
    df_no_bb_short = df["Sig_GY"] & ~df["AtBBHi"]
    bb_stats += [
        _stats(_ret_short(df_bb_short),   "Graveyard + BB Touch"),
        _stats(_ret_short(df_no_bb_short),"Graveyard No BB"),
    ]

    # ── Chart 1: Candlestick with Doji markers ─────────────────────────────────
    # Use a scatter over the close line for performance (4k candles ok, but keep it readable)
    dates_str = df["Date"].dt.strftime("%Y-%m-%d").tolist()

    # Sample for candlestick (full 4k rows)
    fig_candle = go.Figure()
    fig_candle.add_trace(go.Candlestick(
        x=dates_str,
        open=df["Open"].tolist(), high=df["High"].tolist(),
        low=df["Low"].tolist(), close=df["Close"].tolist(),
        name="OHLC",
        increasing_line_color="#AEDAA9", decreasing_line_color="#F4AEAD",
        showlegend=True,
    ))
    # BB overlay
    fig_candle.add_trace(go.Scatter(
        x=dates_str, y=df["BB_MA"].tolist(),
        name="BB Mid", line=dict(color="#546E7A", width=1, dash="dot"),
    ))
    fig_candle.add_trace(go.Scatter(
        x=dates_str, y=df["BB_Hi"].tolist(),
        name="BB Upper", line=dict(color="#7B1FA2", width=1, dash="dash"),
    ))
    fig_candle.add_trace(go.Scatter(
        x=dates_str, y=df["BB_Lo"].tolist(),
        name="BB Lower", line=dict(color="#7B1FA2", width=1, dash="dash"),
        fill="tonexty", fillcolor="rgba(123,31,162,0.05)",
    ))
    # Doji markers
    gy = df[df["Sig_GY"]]
    dr = df[df["Sig_DF"]]
    st = df[df["IsStd"]]
    if len(gy):
        fig_candle.add_trace(go.Scatter(
            x=gy["Date"].dt.strftime("%Y-%m-%d").tolist(),
            y=gy["High"].tolist(),
            name="Graveyard Doji", mode="markers",
            marker=dict(color=C_GY, size=7, symbol="triangle-down"),
        ))
    if len(dr):
        fig_candle.add_trace(go.Scatter(
            x=dr["Date"].dt.strftime("%Y-%m-%d").tolist(),
            y=dr["Low"].tolist(),
            name="Dragonfly Doji", mode="markers",
            marker=dict(color=C_DF, size=7, symbol="triangle-up"),
        ))
    if len(st):
        fig_candle.add_trace(go.Scatter(
            x=st["Date"].dt.strftime("%Y-%m-%d").tolist(),
            y=st["Close"].tolist(),
            name="Standard Doji", mode="markers",
            marker=dict(color=C_DOJI, size=5, symbol="diamond"),
        ))
    fig_candle.update_layout(
        height=500, template="plotly_white",
        xaxis_rangeslider_visible=False,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        yaxis_title="Price",
    )

    # ── Chart 2: Win rate bar chart by Doji type ──────────────────────────────
    labels = [r["type"] for r in stats_rows]
    wrs    = [r["win_rate"] * 100 for r in stats_rows]
    counts = [r["count"] for r in stats_rows]
    colors = [C_DF, C_GY, C_DOJI, C_DOJI]

    fig_wr = go.Figure()
    fig_wr.add_trace(go.Bar(
        x=labels, y=wrs,
        marker_color=colors,
        text=[f"{w:.1f}%<br>n={c}" for w, c in zip(wrs, counts)],
        textposition="outside",
        name="Win Rate",
    ))
    fig_wr.add_hline(y=50, line_dash="dash", line_color="#9E9E9E", annotation_text="50 %")
    fig_wr.update_layout(
        height=380, template="plotly_white",
        yaxis_title="Win Rate (%)", yaxis_range=[0, 100],
    )

    # ── Chart 3: BB confirmation comparison ──────────────────────────────────
    bb_labels = [r["type"] for r in bb_stats]
    bb_wrs    = [r["win_rate"] * 100 for r in bb_stats]
    bb_counts = [r["count"] for r in bb_stats]
    bb_colors = [C_DF, "#90A4AE", C_GY, "#90A4AE"]

    fig_bb = go.Figure()
    fig_bb.add_trace(go.Bar(
        x=bb_labels, y=bb_wrs,
        marker_color=bb_colors,
        text=[f"{w:.1f}%<br>n={c}" for w, c in zip(bb_wrs, bb_counts)],
        textposition="outside",
        name="Win Rate",
    ))
    fig_bb.add_hline(y=50, line_dash="dash", line_color="#9E9E9E", annotation_text="50 %")
    fig_bb.update_layout(
        height=360, template="plotly_white",
        yaxis_title="Win Rate (%)", yaxis_range=[0, 100],
        title_text="BB Confirmation vs No Confirmation",
    )

    doji_total = int(df["IsDoji"].sum())
    gy_total   = int(df["IsGraveyard"].sum())
    df_total   = int(df["IsDragonfly"].sum())
    std_total  = int(df["IsStd"].sum())

    return TabSpec(
        id="doji-detection",
        title="🕯️ Doji Detection",
        intro_md=_DOJI_GUIDE,
        metrics=[
            Metric(key="total_doji", label="Total Doji Days",   value=float(doji_total), format="number"),
            Metric(key="gy_count",   label="Graveyard Count",   value=float(gy_total),   format="number"),
            Metric(key="df_count",   label="Dragonfly Count",   value=float(df_total),   format="number"),
            Metric(key="std_count",  label="Standard Doji",     value=float(std_total),  format="number"),
        ],
        charts=[
            ChartSpec(
                id="doji-candle", title="Candlestick Chart with Doji Highlights",
                description=(
                    "Doji candles marked: ▼ Graveyard (bearish, after uptrend), "
                    "▲ Dragonfly (bullish, after downtrend), ◆ Standard. "
                    "Bollinger Bands overlaid (purple dashes)."
                ),
                figure=_fig_to_dict(fig_candle),
            ),
            ChartSpec(
                id="doji-winrate", title="Win Rate by Doji Type",
                description="Entry at next-day open, exit at next-day close. Trend-context filter applied.",
                figure=_fig_to_dict(fig_wr),
            ),
            ChartSpec(
                id="doji-bb", title="Bollinger Band Confirmation Effect",
                description="Does touching the outer BB band improve win rate? Comparing with vs without BB touch.",
                figure=_fig_to_dict(fig_bb),
            ),
        ],
        tables=[
            TableSpec(
                id="doji-stats", title="Signal Statistics by Doji Type",
                columns=[
                    ColumnSpec(key="type",     label="Type",        format="text",    align="left"),
                    ColumnSpec(key="count",    label="Signals",     format="number",  align="right"),
                    ColumnSpec(key="win_rate", label="Win Rate",    format="percent", align="right"),
                    ColumnSpec(key="avg_ret",  label="Avg Return",  format="percent", align="right"),
                    ColumnSpec(key="sharpe",   label="Sharpe",      format="ratio",   align="right"),
                ],
                rows=stats_rows + bb_stats,
            ),
        ],
    )


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 3 — SPREAD / MEAN-REVERSION SYSTEM
# ═══════════════════════════════════════════════════════════════════════════════


def _tab_pairs(df_raw: pd.DataFrame, params) -> TabSpec:
    lookback = params.pairs_lookback
    z_thresh = params.entry_z

    df = df_raw.copy()
    df["MA"]     = df["Close"].rolling(lookback).mean()
    df["Spread"] = df["Close"] - df["MA"]
    df["Sp_MA"]  = df["Spread"].rolling(lookback).mean()
    df["Sp_Std"] = df["Spread"].rolling(lookback).std()
    df["Z"]      = (df["Spread"] - df["Sp_MA"]) / df["Sp_Std"].replace(0, np.nan)

    df = df.dropna(subset=["Z"]).reset_index(drop=True)
    dates_str = df["Date"].dt.strftime("%Y-%m-%d").tolist()

    # Signal: long when Z < -threshold, short when Z > +threshold
    # Exit when Z crosses 0 (next-day close)
    df["Sig_Long"]  = df["Z"] < -z_thresh
    df["Sig_Short"] = df["Z"] >  z_thresh

    # Position: +1 long, -1 short, 0 flat
    position = 0.0
    pos_list = []
    for z in df["Z"]:
        if position == 0:
            if z < -z_thresh:
                position = 1.0
            elif z > z_thresh:
                position = -1.0
        else:
            # Exit when Z reverts to 0
            if position == 1.0 and z >= 0:
                position = 0.0
            elif position == -1.0 and z <= 0:
                position = 0.0
        pos_list.append(position)

    df["Position"] = pos_list
    df["DailyRet"] = df["Close"].pct_change()
    df["Ret_Pairs"] = df["Position"].shift(1).fillna(0) * df["DailyRet"]
    df["Ret_BH"]   = df["DailyRet"]

    strat_eq = _equity_from_returns(df["Ret_Pairs"])
    bh_eq    = _equity_from_returns(df["Ret_BH"])
    sharpe_strat = _sharpe(df["Ret_Pairs"])
    sharpe_bh    = _sharpe(df["Ret_BH"])
    mdd_strat = _max_dd(strat_eq)
    mdd_bh    = _max_dd(bh_eq)

    # Rolling correlation (Close vs MA — trivially high, shown for methodology)
    df["Roll_Corr"] = df["Close"].rolling(lookback).corr(df["MA"])

    # Mean-reversion test: regress ΔSpread on lagged Spread
    delta_sp = df["Spread"].diff().dropna()
    lag_sp   = df["Spread"].shift(1).dropna()
    common_idx = delta_sp.index.intersection(lag_sp.index)
    delta_sp = delta_sp.loc[common_idx]
    lag_sp   = lag_sp.loc[common_idx]
    # OLS: slope = cov(delta, lag) / var(lag)
    cov_dl   = float(np.cov(delta_sp, lag_sp)[0, 1])
    var_l    = float(np.var(lag_sp))
    slope    = cov_dl / var_l if var_l != 0 else 0.0
    half_life = -np.log(2) / slope if slope < 0 else float("nan")
    mr_text = (
        f"Mean-reversion coefficient: **{slope:.4f}** "
        f"({'mean-reverting ✓' if slope < 0 else 'no mean reversion detected ✗'}). "
        + (f"Half-life: **{half_life:.1f} days**." if slope < 0 and not np.isnan(half_life) else "")
    )

    # ── Charts ────────────────────────────────────────────────────────────────
    # Chart 1: Normalized prices (Close vs MA as proxy for "two instruments")
    norm_close = (df["Close"] / df["Close"].iloc[0] * 100).tolist()
    norm_ma    = (df["MA"]    / df["MA"].iloc[0]    * 100).tolist()

    fig_price = go.Figure()
    fig_price.add_trace(go.Scatter(
        x=dates_str, y=norm_close, name="Close (Series A)",
        line=dict(color=C_STRAT, width=1.5),
    ))
    fig_price.add_trace(go.Scatter(
        x=dates_str, y=norm_ma, name=f"MA({lookback}) (Series B)",
        line=dict(color=C_BH, width=1.5, dash="dash"),
    ))
    fig_price.update_layout(
        height=360, template="plotly_white",
        yaxis_title="Rebased to 100",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    )

    # Chart 2: Z-score with threshold lines and signal shading
    long_x  = [d for d, z in zip(dates_str, df["Z"]) if z < -z_thresh]
    short_x = [d for d, z in zip(dates_str, df["Z"]) if z >  z_thresh]

    fig_z = go.Figure()
    fig_z.add_trace(go.Scatter(
        x=dates_str, y=df["Z"].tolist(),
        name="Z-Score", line=dict(color=C_STRAT, width=1.3),
    ))
    fig_z.add_hline(y=z_thresh,  line_dash="dash", line_color=C_SHORT,
                    annotation_text=f"+{z_thresh} (Short)")
    fig_z.add_hline(y=-z_thresh, line_dash="dash", line_color=C_LONG,
                    annotation_text=f"−{z_thresh} (Long)")
    fig_z.add_hline(y=0, line_dash="dot", line_color="#9E9E9E")
    fig_z.update_layout(
        height=340, template="plotly_white",
        yaxis_title="Z-Score",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    )

    # Chart 3: Spread with rolling mean ± 2 std
    spread_mean = df["Sp_MA"].tolist()
    spread_hi   = (df["Sp_MA"] + z_thresh * df["Sp_Std"]).tolist()
    spread_lo   = (df["Sp_MA"] - z_thresh * df["Sp_Std"]).tolist()

    fig_spread = go.Figure()
    fig_spread.add_trace(go.Scatter(
        x=dates_str, y=df["Spread"].tolist(),
        name="Spread", line=dict(color=C_STRAT, width=1.2),
    ))
    fig_spread.add_trace(go.Scatter(
        x=dates_str, y=spread_hi,
        name=f"+{z_thresh}σ band", line=dict(color=C_SHORT, width=1, dash="dash"),
    ))
    fig_spread.add_trace(go.Scatter(
        x=dates_str, y=spread_lo,
        name=f"−{z_thresh}σ band", line=dict(color=C_LONG, width=1, dash="dash"),
        fill="tonexty", fillcolor="rgba(123,31,162,0.06)",
    ))
    fig_spread.add_trace(go.Scatter(
        x=dates_str, y=spread_mean,
        name="Rolling mean", line=dict(color="#546E7A", width=1, dash="dot"),
    ))
    fig_spread.update_layout(
        height=340, template="plotly_white",
        yaxis_title="Spread",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    )

    # Chart 4: Equity curve
    fig_eq = go.Figure()
    fig_eq.add_trace(go.Scatter(
        x=dates_str, y=strat_eq.tolist(),
        name="Spread Strategy", line=dict(color=C_STRAT, width=1.8),
    ))
    fig_eq.add_trace(go.Scatter(
        x=dates_str, y=bh_eq.tolist(),
        name="Buy & Hold", line=dict(color=C_BH, width=1.8),
    ))
    fig_eq.update_layout(
        height=360, template="plotly_white",
        yaxis_title="Equity (rebased 100)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    )

    return TabSpec(
        id="spread-system",
        title="📊 Spread System",
        intro_md=_PAIRS_GUIDE,
        metrics=[
            Metric(key="sharpe_strat", label="Strategy Sharpe", value=sharpe_strat, format="ratio"),
            Metric(key="sharpe_bh",    label="B&H Sharpe",      value=sharpe_bh,    format="ratio"),
            Metric(key="mdd_strat",    label="Strategy MDD",    value=mdd_strat,    format="percent"),
            Metric(key="mdd_bh",       label="B&H MDD",         value=mdd_bh,       format="percent"),
            Metric(key="slope",        label="MR Coefficient",  value=slope,        format="ratio"),
        ],
        charts=[
            ChartSpec(
                id="sp-price",  title="Normalized Price Series (Close vs Rolling Mean)",
                description=f"Both series rebased to 100. Lookback = {lookback} days.",
                figure=_fig_to_dict(fig_price),
            ),
            ChartSpec(
                id="sp-zscore", title="Z-Score with Entry Thresholds",
                description=(
                    f"Long when Z < −{z_thresh}, short when Z > +{z_thresh}, exit at Z = 0. "
                    + mr_text
                ),
                figure=_fig_to_dict(fig_z),
            ),
            ChartSpec(
                id="sp-spread", title="Spread with Rolling Mean ± Bands",
                description=f"Shaded region between ±{z_thresh}σ bands.",
                figure=_fig_to_dict(fig_spread),
            ),
            ChartSpec(
                id="sp-equity", title="Strategy Equity vs Buy & Hold",
                description=f"Sharpe: {sharpe_strat:.2f} (strategy) vs {sharpe_bh:.2f} (B&H). MDD: {mdd_strat:.1%} vs {mdd_bh:.1%}.",
                figure=_fig_to_dict(fig_eq),
            ),
        ],
        tables=[],
    )


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 4 — LONG-TERM DRAWDOWN ENTRY
# ═══════════════════════════════════════════════════════════════════════════════


def _tab_drawdown(df_raw: pd.DataFrame, params) -> TabSpec:
    tier1 = params.tier1_pct   # e.g. 0.25
    tier2 = params.tier2_pct   # e.g. 0.33

    df = df_raw.copy()
    df["Peak"] = df["Close"].cummax()
    df["DD"]   = (df["Close"] - df["Peak"]) / df["Peak"]

    df["InTier1"] = df["DD"] <= -tier1
    df["InTier2"] = df["DD"] <= -tier2

    # Current status
    last = df.iloc[-1]
    curr_dd   = float(last["DD"])
    to_tier1  = max(0.0, -tier1 - curr_dd)
    to_tier2  = max(0.0, -tier2 - curr_dd)

    # ── Build drawdown event table ─────────────────────────────────────────────
    # Identify distinct drawdown episodes (DD < -tier1 at some point)
    in_dd = False
    events = []
    ep_start = None
    ep_peak_price = None
    ep_peak_date  = None
    ep_trough_price = None
    ep_trough_date  = None
    ep_tier1_date   = None
    ep_tier1_price  = None
    ep_tier2_date   = None
    ep_tier2_price  = None

    for _, row in df.iterrows():
        dd = row["DD"]
        if not in_dd and dd <= -tier1:
            in_dd = True
            ep_start = row["Date"]
            ep_peak_price = row["Peak"]
            ep_trough_price = row["Close"]
            ep_trough_date = row["Date"]
            ep_tier1_date  = row["Date"] if row["InTier1"] else None
            ep_tier1_price = row["Close"] if row["InTier1"] else None
            ep_tier2_date  = row["Date"] if row["InTier2"] else None
            ep_tier2_price = row["Close"] if row["InTier2"] else None
        elif in_dd:
            if row["Close"] < ep_trough_price:
                ep_trough_price = row["Close"]
                ep_trough_date  = row["Date"]
            if ep_tier1_date is None and row["InTier1"]:
                ep_tier1_date  = row["Date"]
                ep_tier1_price = row["Close"]
            if ep_tier2_date is None and row["InTier2"]:
                ep_tier2_date  = row["Date"]
                ep_tier2_price = row["Close"]
            if row["Close"] >= ep_peak_price:
                # Recovery
                ret_t1 = (row["Close"] - ep_tier1_price) / ep_tier1_price if ep_tier1_price else None
                ret_t2 = (row["Close"] - ep_tier2_price) / ep_tier2_price if ep_tier2_price else None
                days_t1 = (row["Date"] - ep_tier1_date).days if ep_tier1_date else None
                days_t2 = (row["Date"] - ep_tier2_date).days if ep_tier2_date else None
                trough_dd = (ep_trough_price - ep_peak_price) / ep_peak_price
                events.append({
                    "start":        str(ep_start.date()),
                    "trough_date":  str(ep_trough_date.date()),
                    "recovery":     str(row["Date"].date()),
                    "trough_dd":    round(trough_dd, 4),
                    "tier1_date":   str(ep_tier1_date.date()) if ep_tier1_date else "—",
                    "ret_tier1":    round(ret_t1, 4) if ret_t1 is not None else None,
                    "days_tier1":   days_t1,
                    "tier2_date":   str(ep_tier2_date.date()) if ep_tier2_date else "—",
                    "ret_tier2":    round(ret_t2, 4) if ret_t2 is not None else None,
                    "days_tier2":   days_t2,
                })
                in_dd = False

    dates_str = df["Date"].dt.strftime("%Y-%m-%d").tolist()

    # ── Charts ────────────────────────────────────────────────────────────────
    # Chart 1: Price with drawdown shading
    fig_price = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        row_heights=[0.65, 0.35], vertical_spacing=0.03,
        subplot_titles=("Price (S&P 500 Futures)", "Drawdown from Peak"),
    )
    fig_price.add_trace(go.Scatter(
        x=dates_str, y=df["Close"].tolist(),
        name="Close", line=dict(color=C_BH, width=1.3),
    ), row=1, col=1)
    fig_price.add_trace(go.Scatter(
        x=dates_str, y=df["Peak"].tolist(),
        name="Rolling Peak", line=dict(color="#9E9E9E", width=1, dash="dot"),
    ), row=1, col=1)

    # Tier entry points on price chart
    tier1_entries = df[df["InTier1"] & ~df["InTier1"].shift(1).fillna(False)]
    tier2_entries = df[df["InTier2"] & ~df["InTier2"].shift(1).fillna(False)]
    if len(tier1_entries):
        fig_price.add_trace(go.Scatter(
            x=tier1_entries["Date"].dt.strftime("%Y-%m-%d").tolist(),
            y=tier1_entries["Close"].tolist(),
            name=f"Tier 1 Entry (−{tier1:.0%})",
            mode="markers", marker=dict(color=C_STRAT, size=8, symbol="triangle-up"),
        ), row=1, col=1)
    if len(tier2_entries):
        fig_price.add_trace(go.Scatter(
            x=tier2_entries["Date"].dt.strftime("%Y-%m-%d").tolist(),
            y=tier2_entries["Close"].tolist(),
            name=f"Tier 2 Entry (−{tier2:.0%})",
            mode="markers", marker=dict(color=C_SHORT, size=8, symbol="triangle-up"),
        ), row=1, col=1)

    dd_pct = (df["DD"] * 100).tolist()
    fig_price.add_trace(go.Scatter(
        x=dates_str, y=dd_pct,
        name="Drawdown %", fill="tozeroy",
        line=dict(color=C_SHORT, width=0.5),
        fillcolor="rgba(198,40,40,0.25)", showlegend=False,
    ), row=2, col=1)
    fig_price.add_hline(y=-tier1 * 100, row=2, col=1,
                        line_dash="dash", line_color=C_STRAT,
                        annotation_text=f"−{tier1:.0%} Tier 1")
    fig_price.add_hline(y=-tier2 * 100, row=2, col=1,
                        line_dash="dash", line_color=C_SHORT,
                        annotation_text=f"−{tier2:.0%} Tier 2")
    fig_price.update_layout(
        height=520, template="plotly_white",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    )

    # Chart 2: Returns from tier entries (bar chart per event)
    if events:
        ev_labels = [e["start"] for e in events]
        ev_ret1   = [e["ret_tier1"] * 100 if e["ret_tier1"] is not None else 0 for e in events]
        ev_ret2   = [e["ret_tier2"] * 100 if e["ret_tier2"] is not None else 0 for e in events]
        fig_ret = go.Figure()
        fig_ret.add_trace(go.Bar(
            x=ev_labels, y=ev_ret1,
            name=f"Tier 1 Return (−{tier1:.0%})",
            marker_color=C_STRAT,
        ))
        fig_ret.add_trace(go.Bar(
            x=ev_labels, y=ev_ret2,
            name=f"Tier 2 Return (−{tier2:.0%})",
            marker_color=C_SHORT,
        ))
        fig_ret.update_layout(
            height=360, template="plotly_white",
            yaxis_title="Return to Recovery (%)",
            barmode="group",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        )
    else:
        fig_ret = go.Figure()
        fig_ret.add_annotation(text="No completed drawdown events found in date range.",
                               xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False)

    # Avg return and days per tier
    tier1_rets  = [e["ret_tier1"]  for e in events if e["ret_tier1"]  is not None]
    tier2_rets  = [e["ret_tier2"]  for e in events if e["ret_tier2"]  is not None]
    tier1_days  = [e["days_tier1"] for e in events if e["days_tier1"] is not None]
    tier2_days  = [e["days_tier2"] for e in events if e["days_tier2"] is not None]
    avg_ret1    = float(np.mean(tier1_rets)) if tier1_rets else 0.0
    avg_ret2    = float(np.mean(tier2_rets)) if tier2_rets else 0.0
    avg_days1   = float(np.mean(tier1_days)) if tier1_days else 0.0
    avg_days2   = float(np.mean(tier2_days)) if tier2_days else 0.0

    # Table rows
    event_rows = []
    for e in events:
        event_rows.append({
            "start":      e["start"],
            "trough":     e["trough_date"],
            "recovery":   e["recovery"],
            "trough_dd":  e["trough_dd"],
            "tier1_date": e["tier1_date"],
            "ret_tier1":  e["ret_tier1"] if e["ret_tier1"] is not None else float("nan"),
            "days_tier1": e["days_tier1"] if e["days_tier1"] is not None else 0,
            "tier2_date": e["tier2_date"],
            "ret_tier2":  e["ret_tier2"] if e["ret_tier2"] is not None else float("nan"),
            "days_tier2": e["days_tier2"] if e["days_tier2"] is not None else 0,
        })

    return TabSpec(
        id="drawdown-entry",
        title="📉 Drawdown Entry",
        intro_md=_DD_GUIDE,
        metrics=[
            Metric(key="curr_dd",   label="Current Drawdown",   value=curr_dd,   format="percent"),
            Metric(key="to_tier1",  label="Distance to Tier 1", value=to_tier1,  format="percent"),
            Metric(key="to_tier2",  label="Distance to Tier 2", value=to_tier2,  format="percent"),
            Metric(key="avg_ret1",  label=f"Avg Return @ −{tier1:.0%}", value=avg_ret1, format="percent"),
            Metric(key="avg_ret2",  label=f"Avg Return @ −{tier2:.0%}", value=avg_ret2, format="percent"),
            Metric(key="avg_days1", label=f"Avg Days to Recovery (T1)", value=avg_days1, format="number"),
            Metric(key="avg_days2", label=f"Avg Days to Recovery (T2)", value=avg_days2, format="number"),
        ],
        charts=[
            ChartSpec(
                id="dd-price",  title="Price with Drawdown Shading and Tier Entry Points",
                description=(
                    f"Tier 1 = −{tier1:.0%} (orange triangles), Tier 2 = −{tier2:.0%} (red triangles). "
                    f"Bottom panel: drawdown depth with dashed tier lines."
                ),
                figure=_fig_to_dict(fig_price),
            ),
            ChartSpec(
                id="dd-returns", title="Return to Recovery per Drawdown Event",
                description=f"Avg return at Tier 1: {avg_ret1:.1%} over {avg_days1:.0f} days. Tier 2: {avg_ret2:.1%} over {avg_days2:.0f} days.",
                figure=_fig_to_dict(fig_ret),
            ),
        ],
        tables=[
            TableSpec(
                id="dd-events", title="Historical Drawdown Events (Tier-Breaching)",
                description="Each row is a drawdown episode that breached at least Tier 1.",
                columns=[
                    ColumnSpec(key="start",      label="DD Start",     format="date",    align="left"),
                    ColumnSpec(key="trough",     label="Trough Date",  format="date",    align="left"),
                    ColumnSpec(key="recovery",   label="Recovery",     format="date",    align="left"),
                    ColumnSpec(key="trough_dd",  label="Trough DD",    format="percent", align="right"),
                    ColumnSpec(key="tier1_date", label="T1 Entry",     format="date",    align="left"),
                    ColumnSpec(key="ret_tier1",  label="T1 Return",    format="percent", align="right"),
                    ColumnSpec(key="days_tier1", label="T1 Days",      format="number",  align="right"),
                    ColumnSpec(key="tier2_date", label="T2 Entry",     format="date",    align="left"),
                    ColumnSpec(key="ret_tier2",  label="T2 Return",    format="percent", align="right"),
                    ColumnSpec(key="days_tier2", label="T2 Days",      format="number",  align="right"),
                ],
                rows=event_rows,
            ),
        ],
    )


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 5 — RENKO
# ═══════════════════════════════════════════════════════════════════════════════


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    hi = df["High"]
    lo = df["Low"]
    pc = df["Close"].shift(1)
    tr = pd.concat([hi - lo, (hi - pc).abs(), (lo - pc).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def _build_renko(prices: list, dates: list, brick_size: float) -> pd.DataFrame:
    if len(prices) < 2:
        return pd.DataFrame()
    bricks = []
    current = prices[0]
    for i in range(1, len(prices)):
        p = prices[i]
        d = dates[i]
        # Up bricks
        while p >= current + brick_size:
            bricks.append({"date": d, "open": current, "close": current + brick_size, "dir": 1})
            current += brick_size
        # Down bricks
        while p <= current - brick_size:
            bricks.append({"date": d, "open": current, "close": current - brick_size, "dir": -1})
            current -= brick_size
    return pd.DataFrame(bricks) if bricks else pd.DataFrame()


def _tab_renko(df_raw: pd.DataFrame, params) -> TabSpec:
    brick_mode = params.brick_mode
    fixed_size = params.fixed_brick
    atr_period = params.atr_period
    min_bricks = params.min_bricks

    df = df_raw.copy()

    # Determine brick size
    if brick_mode == "atr":
        atr_series = _atr(df, atr_period).dropna()
        brick_size = float(atr_series.mean()) if len(atr_series) else fixed_size
    else:
        brick_size = fixed_size

    prices = df["Close"].tolist()
    dates  = df["Date"].tolist()

    bricks_df = _build_renko(prices, dates, brick_size)

    if bricks_df.empty:
        empty_tab = TabSpec(
            id="renko", title="🧱 Renko",
            intro_md=_RENKO_GUIDE,
            metrics=[],
            charts=[],
            tables=[],
        )
        return empty_tab

    # ── Counter-trend signals from Renko ──────────────────────────────────────
    bricks_df["date_str"] = pd.to_datetime(bricks_df["date"]).dt.strftime("%Y-%m-%d")
    bricks_df["idx"] = range(len(bricks_df))

    # Count consecutive bricks in same direction
    cons = [1]
    for k in range(1, len(bricks_df)):
        if bricks_df["dir"].iloc[k] == bricks_df["dir"].iloc[k - 1]:
            cons.append(cons[-1] + 1)
        else:
            cons.append(1)
    bricks_df["cons"] = cons

    # Signal: first reversal after ≥ min_bricks in opposite direction
    signals = []
    for k in range(1, len(bricks_df)):
        curr_dir = bricks_df["dir"].iloc[k]
        prev_dir = bricks_df["dir"].iloc[k - 1]
        prev_cons = bricks_df["cons"].iloc[k - 1]
        if curr_dir != prev_dir and prev_cons >= min_bricks:
            entry_px = bricks_df["close"].iloc[k]
            # Exit: next reversal brick
            exit_idx = None
            for j in range(k + 1, len(bricks_df)):
                if bricks_df["dir"].iloc[j] != curr_dir:
                    exit_idx = j
                    break
            if exit_idx is not None:
                exit_px = bricks_df["close"].iloc[exit_idx]
                ret = (exit_px - entry_px) / entry_px if curr_dir == 1 else (entry_px - exit_px) / entry_px
                signals.append({
                    "brick_idx":  k,
                    "date":       bricks_df["date_str"].iloc[k],
                    "direction":  "Long" if curr_dir == 1 else "Short",
                    "entry_px":   entry_px,
                    "exit_px":    exit_px,
                    "return":     ret,
                })

    sig_df = pd.DataFrame(signals) if signals else pd.DataFrame(columns=["brick_idx","date","direction","entry_px","exit_px","return"])
    n_sig  = len(sig_df)
    win_rate = float((sig_df["return"] > 0).mean()) if n_sig else 0.0
    avg_ret  = float(sig_df["return"].mean()) if n_sig else 0.0
    sharpe_r = _sharpe(sig_df["return"]) if n_sig > 1 else 0.0

    # ── Sensitivity sweep: min_bricks 2→8 ────────────────────────────────────
    sweep_n  = list(range(2, 9))
    sweep_sh = []
    sweep_sig = []
    for mn in sweep_n:
        s_sigs = []
        for k in range(1, len(bricks_df)):
            curr_d = bricks_df["dir"].iloc[k]
            prev_d = bricks_df["dir"].iloc[k - 1]
            prev_c = bricks_df["cons"].iloc[k - 1]
            if curr_d != prev_d and prev_c >= mn:
                ep = bricks_df["close"].iloc[k]
                for j in range(k + 1, len(bricks_df)):
                    if bricks_df["dir"].iloc[j] != curr_d:
                        xp = bricks_df["close"].iloc[j]
                        s_sigs.append((xp - ep) / ep if curr_d == 1 else (ep - xp) / ep)
                        break
        sweep_sh.append(_sharpe(pd.Series(s_sigs)) if len(s_sigs) > 1 else 0.0)
        sweep_sig.append(len(s_sigs))

    # ── Charts ────────────────────────────────────────────────────────────────
    # Chart 1: Renko chart (candlestick-style, one entry per brick)
    n_bricks = len(bricks_df)
    up_mask   = bricks_df["dir"] == 1
    dn_mask   = bricks_df["dir"] == -1

    # Map bricks to their date strings for x-axis
    brick_x   = bricks_df["date_str"].tolist()
    open_vals  = bricks_df["open"].tolist()
    close_vals = bricks_df["close"].tolist()
    high_vals  = [max(o, c) for o, c in zip(open_vals, close_vals)]
    low_vals   = [min(o, c) for o, c in zip(open_vals, close_vals)]

    fig_renko = go.Figure()
    fig_renko.add_trace(go.Candlestick(
        x=list(range(n_bricks)),
        open=open_vals, high=high_vals,
        low=low_vals,   close=close_vals,
        name="Renko Brick",
        increasing_fillcolor=C_LONG,  increasing_line_color=C_LONG,
        decreasing_fillcolor=C_SHORT, decreasing_line_color=C_SHORT,
        showlegend=True,
    ))
    # Mark signal entries
    if n_sig:
        long_sigs  = sig_df[sig_df["direction"] == "Long"]
        short_sigs = sig_df[sig_df["direction"] == "Short"]
        if len(long_sigs):
            fig_renko.add_trace(go.Scatter(
                x=long_sigs["brick_idx"].tolist(),
                y=[bricks_df["close"].iloc[i] for i in long_sigs["brick_idx"]],
                mode="markers", name="Long Signal",
                marker=dict(color=C_LONG, size=10, symbol="triangle-up"),
            ))
        if len(short_sigs):
            fig_renko.add_trace(go.Scatter(
                x=short_sigs["brick_idx"].tolist(),
                y=[bricks_df["close"].iloc[i] for i in short_sigs["brick_idx"]],
                mode="markers", name="Short Signal",
                marker=dict(color=C_SHORT, size=10, symbol="triangle-down"),
            ))
    fig_renko.update_layout(
        height=460, template="plotly_white",
        xaxis_title=f"Brick Index (brick size = {brick_size:.1f}, mode = {brick_mode})",
        yaxis_title="Price",
        xaxis_rangeslider_visible=False,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    )

    # Chart 2: Standard candlestick for same period (side-by-side context)
    dates_str = df["Date"].dt.strftime("%Y-%m-%d").tolist()
    fig_candle = go.Figure(go.Candlestick(
        x=dates_str,
        open=df["Open"].tolist(), high=df["High"].tolist(),
        low=df["Low"].tolist(),   close=df["Close"].tolist(),
        name="OHLC",
        increasing_line_color="#AEDAA9", decreasing_line_color="#F4AEAD",
    ))
    fig_candle.update_layout(
        height=400, template="plotly_white",
        xaxis_rangeslider_visible=False,
        yaxis_title="Price",
    )

    # Chart 3: Sensitivity (Sharpe & signals vs min bricks)
    fig_sens = make_subplots(specs=[[{"secondary_y": True}]])
    fig_sens.add_trace(go.Bar(
        x=sweep_n, y=sweep_sig,
        name="# Signals", marker_color="rgba(84,110,122,0.35)",
    ), secondary_y=True)
    fig_sens.add_trace(go.Scatter(
        x=sweep_n, y=sweep_sh,
        name="Sharpe", line=dict(color=C_STRAT, width=2.5),
        mode="lines+markers", marker=dict(size=8),
    ), secondary_y=False)
    fig_sens.update_xaxes(title_text="Min Consecutive Bricks Required")
    fig_sens.update_yaxes(title_text="Sharpe Ratio", secondary_y=False)
    fig_sens.update_yaxes(title_text="Signal Count", secondary_y=True)
    fig_sens.update_layout(
        height=380, template="plotly_white",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    )

    # Signal table rows
    sig_rows = []
    if n_sig:
        for _, r in sig_df.iterrows():
            sig_rows.append({
                "date":      r["date"],
                "direction": r["direction"],
                "entry_px":  round(float(r["entry_px"]), 2),
                "exit_px":   round(float(r["exit_px"]),  2),
                "return":    round(float(r["return"]),    5),
            })

    return TabSpec(
        id="renko",
        title="🧱 Renko",
        intro_md=_RENKO_GUIDE,
        metrics=[
            Metric(key="brick_size", label="Brick Size",       value=brick_size,  format="number"),
            Metric(key="n_bricks",   label="Total Bricks",     value=float(n_bricks), format="number"),
            Metric(key="n_signals",  label="CT Signals",       value=float(n_sig), format="number"),
            Metric(key="win_rate",   label="Win Rate",         value=win_rate,    format="percent"),
            Metric(key="avg_ret",    label="Avg Return / Trade",value=avg_ret,    format="percent"),
            Metric(key="sharpe",     label="Trade Sharpe",     value=sharpe_r,    format="ratio"),
        ],
        charts=[
            ChartSpec(
                id="renko-chart", title="Renko Chart",
                description=(
                    f"Brick size = {brick_size:.1f} ({brick_mode} mode). "
                    f"Green = up brick, red = down brick. "
                    f"Triangles = counter-trend signals (after ≥{min_bricks} consecutive bricks)."
                ),
                figure=_fig_to_dict(fig_renko),
            ),
            ChartSpec(
                id="renko-candle", title="Standard Candlestick (Same Period)",
                description="Reference chart showing the raw OHLC data before Renko noise filtering.",
                figure=_fig_to_dict(fig_candle),
            ),
            ChartSpec(
                id="renko-sensitivity", title="Sensitivity — Sharpe & Signals vs Min Brick Count",
                description="Higher minimum brick count → fewer signals, potentially better quality.",
                figure=_fig_to_dict(fig_sens),
            ),
        ],
        tables=[
            TableSpec(
                id="renko-signals", title="Counter-Trend Signal Log",
                columns=[
                    ColumnSpec(key="date",      label="Date",      format="date",    align="left"),
                    ColumnSpec(key="direction", label="Direction", format="text",    align="left"),
                    ColumnSpec(key="entry_px",  label="Entry",     format="number",  align="right"),
                    ColumnSpec(key="exit_px",   label="Exit",      format="number",  align="right"),
                    ColumnSpec(key="return",    label="Return",    format="percent", align="right"),
                ],
                rows=sig_rows,
            ),
        ],
    )


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 6 — ML SIGNAL ENHANCEMENT (PLACEHOLDER)
# ═══════════════════════════════════════════════════════════════════════════════


def _tab_ml(df_raw: pd.DataFrame) -> TabSpec:
    # Build a feature preview chart to show what inputs would feed the model
    df = df_raw.copy()
    df["Range"]   = df["High"] - df["Low"]
    df["Av20R"]   = df["Range"].rolling(20).mean()
    df["DailyRet"]= df["Close"].pct_change()
    df["Vol20"]   = df["DailyRet"].rolling(20).std() * np.sqrt(252)
    df["MA60"]    = df["Close"].rolling(60).mean()
    df["Spread"]  = df["Close"] - df["MA60"]
    df["Sp_Std"]  = df["Spread"].rolling(60).std()
    df["Z"]       = df["Spread"] / df["Sp_Std"].replace(0, np.nan)
    df["Peak"]    = df["Close"].cummax()
    df["DD"]      = (df["Close"] - df["Peak"]) / df["Peak"]
    df = df.dropna().reset_index(drop=True)

    dates_str = df["Date"].dt.strftime("%Y-%m-%d").tolist()

    fig_features = make_subplots(
        rows=3, cols=1, shared_xaxes=True,
        subplot_titles=("Z-Score (Spread)", "Drawdown from Peak", "Annualised Vol (20-day)"),
        vertical_spacing=0.05,
        row_heights=[0.34, 0.33, 0.33],
    )
    fig_features.add_trace(go.Scatter(
        x=dates_str, y=df["Z"].tolist(),
        name="Z-Score", line=dict(color=C_STRAT, width=1.2),
    ), row=1, col=1)
    fig_features.add_hline(y=2,  row=1, col=1, line_dash="dash", line_color=C_SHORT)
    fig_features.add_hline(y=-2, row=1, col=1, line_dash="dash", line_color=C_LONG)

    fig_features.add_trace(go.Scatter(
        x=dates_str, y=(df["DD"] * 100).tolist(),
        name="Drawdown %", fill="tozeroy",
        line=dict(color=C_SHORT, width=0.5),
        fillcolor="rgba(198,40,40,0.20)",
    ), row=2, col=1)

    fig_features.add_trace(go.Scatter(
        x=dates_str, y=(df["Vol20"] * 100).tolist(),
        name="Ann. Vol %", line=dict(color=C_DOJI, width=1.2),
    ), row=3, col=1)

    fig_features.update_layout(
        height=520, template="plotly_white",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    )

    feature_rows = [
        {"feature": "Z-score (Close vs MA60)",             "source": "Spread tab",          "type": "Continuous"},
        {"feature": "Drawdown depth (% from ATH)",         "source": "Drawdown tab",         "type": "Continuous"},
        {"feature": "Renko consecutive brick count",       "source": "Renko tab",            "type": "Integer"},
        {"feature": "Doji type classification",            "source": "Doji tab",             "type": "Categorical"},
        {"feature": "20-day average range (A)",            "source": "Range Exhaustion tab", "type": "Continuous"},
        {"feature": "Annualised vol (20-day)",             "source": "Derived",              "type": "Continuous"},
        {"feature": "5-day momentum",                      "source": "Derived",              "type": "Continuous"},
        {"feature": "20-day momentum",                     "source": "Derived",              "type": "Continuous"},
        {"feature": "Day of week",                         "source": "Derived",              "type": "Categorical"},
        {"feature": "Distance from 20-day high / low",     "source": "Derived",              "type": "Continuous"},
        {"feature": "Rolling 60-day correlation (spread)", "source": "Spread tab",           "type": "Continuous"},
    ]

    return TabSpec(
        id="ml-enhancement",
        title="🤖 ML Enhancement",
        intro_md=_ML_GUIDE,
        metrics=[],
        charts=[
            ChartSpec(
                id="ml-features", title="Sample Feature Panel — Inputs to the ML Model",
                description=(
                    "These three features (Z-score, drawdown depth, volatility) would be among the key "
                    "inputs. The model predicts: *did the counter-trend trade on this day produce a positive return?*"
                ),
                figure=_fig_to_dict(fig_features),
            ),
        ],
        tables=[
            TableSpec(
                id="ml-feature-list", title="Proposed Feature Set",
                description="Each feature is derived from the computation already done in other tabs.",
                columns=[
                    ColumnSpec(key="feature", label="Feature",     format="text", align="left"),
                    ColumnSpec(key="source",  label="Source",      format="text", align="left"),
                    ColumnSpec(key="type",    label="Type",        format="text", align="left"),
                ],
                rows=feature_rows,
            ),
        ],
    )


# ═══════════════════════════════════════════════════════════════════════════════
# STRATEGY PARAMS & CLASS
# ═══════════════════════════════════════════════════════════════════════════════


class CounterTrendParams(BaseModel):
    # Global date range
    date_start: date | None = None
    date_end:   date | None = None

    # Tab 1 — Range Exhaustion
    p_value: float = Field(default=2.2,  ge=0.5,  le=3.0,   description="Retrace multiplier P")

    # Tab 2 — Doji
    epsilon_oc:   float = Field(default=0.05, ge=0.01, le=0.25, description="Body/range ratio (Doji threshold)")
    epsilon_gw:   float = Field(default=0.10, ge=0.01, le=0.40, description="Lower-wick threshold for Graveyard")
    epsilon_df:   float = Field(default=0.10, ge=0.01, le=0.40, description="Upper-wick threshold for Dragonfly")
    trend_length: int   = Field(default=3,   ge=1,    le=10,    description="Prior days required for trend context")
    bb_window:    int   = Field(default=20,  ge=10,   le=60,    description="Bollinger Band window")
    bb_std:       float = Field(default=2.0, ge=1.0,  le=3.0,   description="Bollinger Band std dev multiplier")

    # Tab 3 — Spread
    pairs_lookback: int   = Field(default=60, ge=20, le=250, description="Rolling window for spread mean/std")
    entry_z:        float = Field(default=2.0, ge=0.5, le=4.0, description="Z-score entry threshold")

    # Tab 4 — Drawdown
    tier1_pct: float = Field(default=0.25, ge=0.05, le=0.60, description="Tier 1 drawdown threshold")
    tier2_pct: float = Field(default=0.33, ge=0.05, le=0.70, description="Tier 2 drawdown threshold")

    # Tab 5 — Renko
    brick_mode:  str   = Field(default="atr",   description="'fixed' or 'atr'")
    fixed_brick: float = Field(default=20.0,  ge=1.0,  le=500.0, description="Fixed brick size")
    atr_period:  int   = Field(default=14,    ge=5,    le=60,    description="ATR period for brick size")
    min_bricks:  int   = Field(default=3,     ge=2,    le=10,    description="Min consecutive bricks to qualify trend")


class CounterTrendStrategy(BaseStrategy):
    id: str = "counter-trend"
    name: str = "Counter Trend"
    description: str = (
        "Six counter-trend approaches: Range Exhaustion, Doji Detection, "
        "Spread Mean-Reversion, Drawdown Entry, Renko, and ML Enhancement. "
        "Data: S&P 500 futures 2003–2021."
    )
    instrument_kind = InstrumentKind.trend
    ParamsModel = CounterTrendParams
    has_summary: bool = False

    def compute(self, params: CounterTrendParams) -> StrategyResult:  # type: ignore[override]
        df_full = _load_ohlc()
        df = _filter_dates(df_full, params.date_start, params.date_end)

        if len(df) < 25:
            return StrategyResult(
                warnings=["Not enough data rows after date filtering (need ≥ 25)."],
                tabs=[],
            )

        tabs = [
            _tab_range_exhaustion(df, params),
            _tab_doji(df, params),
            _tab_pairs(df, params),
            _tab_drawdown(df, params),
            _tab_renko(df, params),
            _tab_ml(df),
        ]

        date_range = f"{df['Date'].min().date()} → {df['Date'].max().date()}"

        return StrategyResult(
            overview_md=(
                f"**Counter Trend — Strategy Learnings** · {date_range} · "
                f"{len(df):,} trading days\n\n"
                "Six tabs covering the full lecture curriculum on counter-trend and mean-reversion "
                "approaches. Each tab is self-contained: adjust the parameters in the sidebar and "
                "results update across all tabs simultaneously."
            ),
            tabs=tabs,
        )


STRATEGY = CounterTrendStrategy()
