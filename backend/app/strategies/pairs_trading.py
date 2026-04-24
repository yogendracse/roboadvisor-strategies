"""Pairs Trading strategy — Strategy Learnings section.

Eight tabs covering the full pairs-trading (spread-based) curriculum for two
instruments labelled Black and White:

  1. 🧪 Cointegration      — ΔDiff_t = α·Diff_{t-1} + ε   (Dickey-Fuller principle)
  2. 📶 Signal Construction — zdiff_N for N ∈ {5, 10, 20} with threshold overlay
  3. 🎛  Position Engine     — full state table (Signal, Age, Caps, Aged, Pos, fret)
  4. ⚖️  Position Sizing     — inverse-vol weights per leg (20-day trailing)
  5. 📈 Performance         — equity, drawdown, monthly heatmap, trade scatter
  6. 🔥 Parameter Sweep     — entry × holding × N heatmap, in-sample vs OOS
  7. ↔️  In-Sample vs OOS    — side-by-side table + split equity curves
  8. 🔎 Strategy in Action  — day-picker drill-down with 20-day zdiff context

Data: backend/data/pairs/Assignment_PAIRS_data.xlsx with two price columns
'Black' and 'White' (daily adjusted prices). Rows auto-detected; first 1,000
rows = in-sample, remainder = out-of-sample.
"""

from __future__ import annotations

import json
from datetime import date

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from pydantic import BaseModel, Field

from app.core.config import DATA_DIR
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

# ─── Constants ────────────────────────────────────────────────────────────────

PAIRS_XLSX = DATA_DIR / "pairs" / "Assignment_PAIRS_data.xlsx"

N_VALUES = (5, 10, 20)
IN_SAMPLE_ROWS = 1000
VOL_NORM_WINDOW = 60      # trailing window for zret normalisation
SIZE_VOL_WINDOW = 20      # trailing window for inverse-vol sizing
ANN_FACTOR = 252

C_BLACK = "#212121"
C_WHITE = "#90A4AE"
C_LONG  = "#2E7D32"
C_SHORT = "#C62828"
C_FLAT  = "#BDBDBD"
C_STRAT = PALETTE["strat"]
C_BH    = PALETTE["bh"]
C_DIFF  = "#6A1B9A"
C_ORANGE = "#E65100"


def _fig_to_dict(fig: go.Figure) -> dict:
    return json.loads(fig.to_json())


# ─── Data loading ─────────────────────────────────────────────────────────────


def _load_pairs() -> pd.DataFrame:
    """Load the Black/White price series from Assignment_PAIRS_data.xlsx.

    The assignment workbook is the full worksheet — several rows of parameter
    definitions precede the actual time-series header. We probe the first ~25
    rows to find the real header (one that has a 'date' cell plus columns
    referring to both instruments), then prefer the close-price columns.
    """
    if not PAIRS_XLSX.exists():
        raise FileNotFoundError(
            f"Expected pairs data at {PAIRS_XLSX}. "
            "Drop Assignment_PAIRS_data.xlsx into backend/data/pairs/ and retry."
        )

    # Prefer a sheet called 'data' if present, else the first sheet.
    xl = pd.ExcelFile(PAIRS_XLSX)
    sheet = "data" if "data" in xl.sheet_names else xl.sheet_names[0]

    probe = pd.read_excel(PAIRS_XLSX, sheet_name=sheet, header=None, nrows=25)
    header_row = None
    for i in range(len(probe)):
        cells = [str(x).strip().lower() for x in probe.iloc[i].tolist()]
        has_date  = any(c == "date" for c in cells)
        has_white = any("white" in c for c in cells)
        has_black = any("black" in c for c in cells)
        if has_date and has_white and has_black:
            header_row = i
            break
    if header_row is None:
        raise ValueError(
            "Could not locate a header row containing Date + Black + White columns."
        )

    raw = pd.read_excel(PAIRS_XLSX, sheet_name=sheet, header=header_row)
    cols = {str(c).strip().lower(): c for c in raw.columns}

    # Prefer *close* columns (closeBLACK / closeWHITE) over other Black/White-
    # named columns (zBLACK5, BLACK_ret10, etc.).
    def _pick(token: str) -> object | None:
        for key in cols:
            if "close" in key and token in key:
                return cols[key]
        for key in cols:
            if key.endswith(token) or key == token:
                return cols[key]
        for key in cols:
            if token in key:
                return cols[key]
        return None

    white_key = _pick("white")
    black_key = _pick("black")
    date_key = next((cols[k] for k in cols if k == "date" or "date" in k), None)

    if black_key is None or white_key is None:
        raise ValueError(
            f"Could not find Black/White price columns in {list(raw.columns)[:20]}…"
        )

    out = pd.DataFrame()
    if date_key is not None:
        out["Date"] = pd.to_datetime(raw[date_key], errors="coerce")
    else:
        out["Date"] = pd.bdate_range("2000-01-03", periods=len(raw))

    out["Black"] = pd.to_numeric(raw[black_key], errors="coerce")
    out["White"] = pd.to_numeric(raw[white_key], errors="coerce")
    out = out.dropna(subset=["Black", "White"]).reset_index(drop=True)
    if out["Date"].isna().any():
        out["Date"] = pd.bdate_range("2000-01-03", periods=len(out))
    return out


# ─── Metric helpers ───────────────────────────────────────────────────────────


def _sharpe(returns: pd.Series, ann: int = ANN_FACTOR) -> float:
    r = pd.Series(returns).dropna()
    if len(r) < 2 or r.std(ddof=1) == 0:
        return 0.0
    return float(r.mean() / r.std(ddof=1) * np.sqrt(ann))


def _max_dd(equity: pd.Series) -> float:
    e = pd.Series(equity).dropna()
    if e.empty:
        return 0.0
    peak = e.cummax()
    return float(((e - peak) / peak).min())


def _ann_return(equity: pd.Series, ann: int = ANN_FACTOR) -> float:
    e = pd.Series(equity).dropna()
    if len(e) < 2 or e.iloc[0] <= 0:
        return 0.0
    total = e.iloc[-1] / e.iloc[0]
    if total <= 0:
        return 0.0
    return float(total ** (ann / len(e)) - 1)


def _ann_vol(returns: pd.Series, ann: int = ANN_FACTOR) -> float:
    r = pd.Series(returns).dropna()
    if len(r) < 2:
        return 0.0
    return float(r.std(ddof=1) * np.sqrt(ann))


def _equity(rets: pd.Series, start: float = 100.0) -> pd.Series:
    return (1 + pd.Series(rets).fillna(0)).cumprod() * start


# ─── Dickey-Fuller test (no scipy) ────────────────────────────────────────────
# MacKinnon (2010) critical values for the DF-tau no-constant statistic, N → ∞.
# We approximate the p-value by linear interpolation between these anchors.
_DF_TAU_ANCHORS = [
    (-2.565, 0.01),
    (-1.941, 0.05),
    (-1.617, 0.10),
    (-0.500, 0.50),
    ( 0.000, 0.70),
    ( 1.000, 0.90),
]


def _df_pvalue(tau: float) -> float:
    """Rough DF p-value from the t-statistic (one-sided, left-tail)."""
    xs = [a[0] for a in _DF_TAU_ANCHORS]
    ys = [a[1] for a in _DF_TAU_ANCHORS]
    if tau <= xs[0]:
        return 0.005
    if tau >= xs[-1]:
        return 0.99
    return float(np.interp(tau, xs, ys))


def _dickey_fuller(diff: pd.Series) -> dict:
    """Run ΔDiff_t = α · Diff_{t-1} + ε, return {alpha, t_stat, p_value, ...}.

    This is the simple DF form the assignment asks for (no constant, no lags).
    """
    s = pd.Series(diff).dropna().reset_index(drop=True)
    lag  = s.shift(1).iloc[1:].to_numpy()
    delta = s.diff().iloc[1:].to_numpy()
    n = len(delta)
    if n < 10:
        return {"alpha": 0.0, "t_stat": 0.0, "p_value": 1.0, "n": n,
                "stationary": False, "se": 0.0}
    # OLS slope (no intercept): α = Σ(lag·Δ) / Σ(lag²)
    xx = float(np.sum(lag * lag))
    xy = float(np.sum(lag * delta))
    if xx == 0:
        return {"alpha": 0.0, "t_stat": 0.0, "p_value": 1.0, "n": n,
                "stationary": False, "se": 0.0}
    alpha = xy / xx
    resid = delta - alpha * lag
    # Residual variance (degrees of freedom = n - 1 since no intercept)
    sigma2 = float(np.sum(resid * resid) / max(1, n - 1))
    se = float(np.sqrt(sigma2 / xx))
    tau = alpha / se if se > 0 else 0.0
    pval = _df_pvalue(tau)
    return {
        "alpha": alpha,
        "t_stat": tau,
        "p_value": pval,
        "n": n,
        "se": se,
        "stationary": bool(tau < -1.941),   # reject at 5 %
    }


# ─── Core pipeline (shared across tabs) ───────────────────────────────────────


def _build_core(df_in: pd.DataFrame) -> pd.DataFrame:
    """Add columns needed across modules: returns, diffs, zdiff_N for each N."""
    df = df_in.copy()
    df["ret_B"] = df["Black"].pct_change()
    df["ret_W"] = df["White"].pct_change()
    df["Diff"] = df["White"] - df["Black"]
    df["dDiff"] = df["Diff"].diff()

    for N in N_VALUES:
        rw = df["White"].pct_change(periods=N)
        rb = df["Black"].pct_change(periods=N)
        std_rw = rw.rolling(VOL_NORM_WINDOW).std(ddof=1)
        std_rb = rb.rolling(VOL_NORM_WINDOW).std(ddof=1)
        df[f"retN_W_{N}"] = rw
        df[f"retN_B_{N}"] = rb
        df[f"zret_W_{N}"] = rw / std_rw.replace(0, np.nan)
        df[f"zret_B_{N}"] = rb / std_rb.replace(0, np.nan)
        df[f"zdiff_{N}"] = df[f"zret_W_{N}"] - df[f"zret_B_{N}"]

    # Trailing vols for inverse-vol sizing
    df["vol_B"] = df["ret_B"].rolling(SIZE_VOL_WINDOW).std(ddof=1)
    df["vol_W"] = df["ret_W"].rolling(SIZE_VOL_WINDOW).std(ddof=1)
    inv_b = 1.0 / df["vol_B"].replace(0, np.nan)
    inv_w = 1.0 / df["vol_W"].replace(0, np.nan)
    df["w_W"] = inv_w / (inv_w + inv_b)
    df["w_B"] = 1.0 - df["w_W"]
    return df


# ─── Position engine ──────────────────────────────────────────────────────────


def _run_positions(
    df: pd.DataFrame,
    N: int,
    long_entry: float,
    short_entry: float,
    long_exit_cap: float,
    short_exit_cap: float,
    holding_period: int,
    size_aware: bool = True,
) -> pd.DataFrame:
    """Run the position engine for one N value.

    Columns returned:
      signal, lcap, scap, age, aged, pos, fret1
    Signal = raw (long < -entry, short > +entry, else flat). Pos = active
    position after exit logic. fret1 = position × sized_forward_return.
    """
    z = df[f"zdiff_{N}"].to_numpy()
    ret_w_next = df["ret_W"].shift(-1).to_numpy()
    ret_b_next = df["ret_B"].shift(-1).to_numpy()
    ww = df["w_W"].to_numpy()
    wb = df["w_B"].to_numpy()
    n = len(df)

    signal = np.zeros(n, dtype=float)
    pos    = np.zeros(n, dtype=float)
    age    = np.zeros(n, dtype=int)
    aged   = np.zeros(n, dtype=int)
    lcap   = np.zeros(n, dtype=int)
    scap   = np.zeros(n, dtype=int)

    for i, zi in enumerate(z):
        if np.isnan(zi):
            signal[i] = 0
            continue
        if zi <= long_entry:
            signal[i] = +1
        elif zi >= short_entry:
            signal[i] = -1

    curr = 0.0
    curr_age = 0
    for i in range(n):
        zi = z[i]
        sig = signal[i]

        # Exit checks against the *current* held position
        exit_reason = None
        if curr == +1:
            if not np.isnan(zi) and zi >= long_exit_cap:
                lcap[i] = 1
                exit_reason = "cap"
        elif curr == -1:
            if not np.isnan(zi) and zi <= short_exit_cap:
                scap[i] = 1
                exit_reason = "cap"

        if curr != 0 and curr_age >= holding_period:
            aged[i] = 1
            if exit_reason is None:
                exit_reason = "aged"

        if exit_reason is not None:
            curr = 0.0
            curr_age = 0

        # Flip or open on opposite / fresh signal (higher priority after exit)
        if curr == 0:
            if sig != 0 and not np.isnan(zi):
                curr = sig
                curr_age = 1
        else:
            # Active position — if signal flips, rotate immediately
            if sig != 0 and sig != curr:
                curr = sig
                curr_age = 1
            else:
                curr_age += 1

        pos[i] = curr
        age[i] = curr_age

    # Forward 1-day return attribution (position held today → earn t+1 return)
    if size_aware:
        leg = ww * ret_w_next - wb * ret_b_next
    else:
        leg = ret_w_next - ret_b_next
    fret1 = pos * leg

    out = pd.DataFrame({
        "signal": signal,
        "lcap":   lcap,
        "scap":   scap,
        "age":    age,
        "aged":   aged,
        "pos":    pos,
        "fret1":  fret1,
    }, index=df.index)
    return out


def _extract_trades(df: pd.DataFrame, pos_df: pd.DataFrame, N: int) -> pd.DataFrame:
    """Compact trade ledger from pos_df. One row per trade."""
    pos = pos_df["pos"].to_numpy()
    fret = pos_df["fret1"].to_numpy()
    z = df[f"zdiff_{N}"].to_numpy()
    dates = df["Date"].to_numpy()

    trades = []
    i = 0
    while i < len(pos):
        if pos[i] != 0 and (i == 0 or pos[i - 1] != pos[i]):
            side = pos[i]
            entry_i = i
            entry_z = z[i] if not np.isnan(z[i]) else 0.0
            cum_r = 0.0
            j = i
            while j < len(pos) and pos[j] == side:
                cum_r += fret[j] if not np.isnan(fret[j]) else 0.0
                j += 1
            trades.append({
                "entry_date": pd.Timestamp(dates[entry_i]).date().isoformat(),
                "exit_date":  pd.Timestamp(dates[min(j, len(pos) - 1)]).date().isoformat(),
                "side":       "LONG" if side > 0 else "SHORT",
                "entry_z":    float(entry_z),
                "bars":       int(j - entry_i),
                "pnl":        float(cum_r),
            })
            i = j
        else:
            i += 1
    return pd.DataFrame(trades)


# ─── Markdown guides ──────────────────────────────────────────────────────────

_COINT_GUIDE = """
## Cointegration — Why this matters

A pairs trade only works if the price difference **mean-reverts** instead of
drifting forever. The Dickey-Fuller principle makes this testable.

We regress the daily *change* in the spread against the previous day's spread:
```
ΔDiff_t = α · Diff_{t-1} + ε
```
- If **α is significantly negative**, yesterday's level predicts today's move
  *back towards the mean* → the spread is stationary → pairs trade is viable.
- If α ≈ 0 or positive, the spread behaves like a random walk → no signal.

The **t-statistic** on α is compared against Dickey-Fuller critical values,
not the usual Normal table, because under the null hypothesis α = 0 the
regressor is non-stationary.

| Critical (N→∞) | t-stat |
|---|---|
| 1 % | −2.57 |
| 5 % | −1.94 |
| 10 % | −1.62 |

Reject at 5 % (t < −1.94) = suitable for pairs trading.
"""

_SIGNAL_GUIDE = """
## Signal Construction — Three time horizons

For each N ∈ {5, 10, 20} we compute:
```
Ret_N(asset) = asset.pct_change(N)
zret_N       = Ret_N / StdDev(past 60 days of Ret_N)
zdiff_N      = zret_N(White) − zret_N(Black)
```
The **zdiff** is the normalised spread of returns — how much more White has
outperformed Black over the last N days, scaled by recent noise.

| zdiff vs threshold | Signal |
|---|---|
| `zdiff > +entry` | Short spread → short White, long Black (−1) |
| `zdiff < −entry` | Long spread → long White, short Black (+1) |
| otherwise | Flat (0) |

Shorter N reacts faster but generates more whipsaws; longer N is cleaner but
slower. Running three in parallel lets you see how the horizon affects
signal frequency.
"""

_POSITION_GUIDE = """
## Position Engine — From raw signals to held positions

A raw signal is just an opinion. The **position engine** turns opinions into
actual held positions by applying exit logic:

1. **Profit cap hit** (zdiff crossed the cap threshold) → exit now
2. **Holding period reached** (age ≥ max) → force exit
3. **Opposite signal generated** → flip
4. Otherwise → hold

Columns mirror the spreadsheet convention: `Signal_N` (raw), `Lcap_N`/`Scap_N`
(cap hits), `Age_N` (days in trade), `Aged_N` (age limit flag), `Pos_N`
(actual active position), `fret1_zN` (attributed 1-day forward return).
"""

_SIZE_GUIDE = """
## Position Sizing — Why inverse vol

A naive pairs trade holds 1 unit of each leg. If White is twice as volatile as
Black, most of your P&L comes from White and the 'pair' is a misnomer. So we
scale each leg inversely to its recent volatility:

```
vol_x    = StdDev(last 20 days of ret_x)
w_White  = (1/vol_White) / (1/vol_White + 1/vol_Black)
w_Black  = 1 − w_White
```
Forward return of the position:
```
fret1 = Pos × (w_White × ret_White[t+1] − w_Black × ret_Black[t+1])
```
When White is the quieter leg, it gets a bigger weight and vice-versa. The
weight chart shows how these shift through time.
"""

_PERF_GUIDE = """
## Performance — Equity, drawdown, and the shape of trades

The **equity curve** tells you whether the strategy *makes money*.
The **drawdown** tells you how much pain it inflicts to get there.
The **monthly heatmap** tells you whether returns are evenly distributed or
concentrated in a few lucky months.
The **trade scatter** tells you whether the profitable trades were actually
the ones the entry threshold tried to catch, or whether the edge is noise.
The **rolling Sharpe** tells you if the pattern is stable or decaying.

A vertical line on each equity chart marks the split between the first 1,000
days (in-sample) and the remainder (out-of-sample).
"""

_SWEEP_GUIDE = """
## Parameter Sweep — *Should* you optimise?

This is the central question in systematic trading. We iterate over every
combination of `entry ∈ [0.5, 2.5]`, `holding ∈ [3, 15]` and `N ∈ {5, 10, 20}`
on the in-sample data and record the Sharpe ratio. The heatmap shows which
combinations worked.

Then we **repeat the exact same sweep on the out-of-sample data** — and
typically the heatmap looks nothing like the first. This is the overfitting
trap: the 'best' in-sample parameters rarely survive out of sample, because
what you're optimising is largely noise.

**The honest answer**: pick parameters that are sensible *ex ante* (N ≈ 10,
entry ≈ 1σ, hold ≈ 5 days) and only accept deviation if there's a *reason* —
not because the Sharpe went up.
"""

_SPLIT_GUIDE = """
## In-Sample vs Out-of-Sample

The hold-out sample is the only honest test of whether a strategy is
**robust** or merely **fit**. We train on the first 1,000 days, freeze the
parameters, and evaluate on the remainder.

- If Sharpe drops **a lot**, the strategy was overfit. Walk away.
- If Sharpe drops **a little**, that's normal — markets evolve.
- If Sharpe improves, you probably got lucky in the second period; don't
  mistake luck for edge.
"""

_ACTION_GUIDE = """
## Strategy in Action — What happened on *this* day?

Pick a date from the dropdown to see the full trade context:
- What was the zdiff value?
- Did it cross an entry or exit threshold?
- What position were we holding, and for how long?
- What exit (if any) triggered?
- What return did we earn that day?

This is how you read the engine — not from the aggregate numbers, but from
individual days where all the pieces line up.
"""


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 1 — COINTEGRATION (DICKEY-FULLER)
# ═══════════════════════════════════════════════════════════════════════════════


def _tab_cointegration(df: pd.DataFrame, split_idx: int) -> TabSpec:
    diff = df["Diff"]
    full  = _dickey_fuller(diff)
    in_s  = _dickey_fuller(diff.iloc[:split_idx])
    out_s = _dickey_fuller(diff.iloc[split_idx:])

    dates = df["Date"].dt.strftime("%Y-%m-%d").tolist()
    diff_mean = float(diff.mean())
    diff_std  = float(diff.std(ddof=1))

    # ── Chart 1: Price series ────────────────────────────────────────────────
    fig_price = go.Figure()
    fig_price.add_trace(go.Scatter(
        x=dates, y=df["Black"].tolist(),
        name="Black", line=dict(color=C_BLACK, width=1.3),
    ))
    fig_price.add_trace(go.Scatter(
        x=dates, y=df["White"].tolist(),
        name="White", line=dict(color=C_WHITE, width=1.3),
    ))
    split_x = dates[split_idx - 1] if split_idx - 1 < len(dates) else dates[-1]
    fig_price.add_vline(x=split_x, line_dash="dash", line_color="#9E9E9E")
    fig_price.add_annotation(
        x=split_x, y=1.0, yref="paper",
        text="IS / OOS split", showarrow=False,
        yshift=-10, bgcolor="rgba(255,255,255,0.8)",
    )
    fig_price.update_layout(
        height=360, template="plotly_white",
        yaxis_title="Price",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    )

    # ── Chart 2: Spread with mean / ±1σ band ─────────────────────────────────
    fig_diff = go.Figure()
    fig_diff.add_trace(go.Scatter(
        x=dates, y=diff.tolist(),
        name="White − Black", line=dict(color=C_DIFF, width=1.2),
    ))
    fig_diff.add_hline(y=diff_mean, line_dash="dot", line_color="#546E7A",
                       annotation_text=f"mean = {diff_mean:.2f}")
    fig_diff.add_hline(y=diff_mean + diff_std, line_dash="dash", line_color="#9E9E9E")
    fig_diff.add_hline(y=diff_mean - diff_std, line_dash="dash", line_color="#9E9E9E",
                       annotation_text=f"±1σ (σ={diff_std:.2f})")
    fig_diff.update_layout(
        height=320, template="plotly_white",
        yaxis_title="Diff (White − Black)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    )

    # ── Regression result table ──────────────────────────────────────────────
    def _label(d: dict) -> str:
        if d["t_stat"] < -2.565:
            return "Reject H₀ at 1 %"
        if d["t_stat"] < -1.941:
            return "Reject H₀ at 5 %"
        if d["t_stat"] < -1.617:
            return "Reject H₀ at 10 %"
        return "Fail to reject H₀"

    verdict_full = _label(full)
    suitable = full["stationary"]
    verdict_md = (
        f"**Regression result**: α = `{full['alpha']:+.5f}`, "
        f"t-stat = `{full['t_stat']:+.3f}`, p ≈ `{full['p_value']:.3f}` "
        f"(n = {full['n']:,}). {verdict_full}. "
        + ("**This pair appears suitable for pairs trading** — the spread "
           "shows statistically significant mean reversion."
           if suitable else
           "**This pair does *not* appear suitable** — the spread behaves "
           "too much like a random walk for the signal to have an edge.")
    )

    reg_rows = [
        {"scope": "Full sample", **{k: round(full[k], 4) if isinstance(full[k], float) else full[k]
                                    for k in ("alpha", "t_stat", "p_value", "n")},
         "verdict": _label(full)},
        {"scope": "In-sample (first 1k)", **{k: round(in_s[k], 4) if isinstance(in_s[k], float) else in_s[k]
                                             for k in ("alpha", "t_stat", "p_value", "n")},
         "verdict": _label(in_s)},
        {"scope": "Out-of-sample (remainder)", **{k: round(out_s[k], 4) if isinstance(out_s[k], float) else out_s[k]
                                                  for k in ("alpha", "t_stat", "p_value", "n")},
         "verdict": _label(out_s)},
    ]

    return TabSpec(
        id="cointegration",
        title="🧪 Cointegration",
        intro_md=_COINT_GUIDE,
        metrics=[
            Metric(key="alpha",   label="α (slope)",    value=full["alpha"],   format="ratio"),
            Metric(key="t_stat",  label="t-statistic",  value=full["t_stat"],  format="ratio"),
            Metric(key="p_value", label="p-value (≈)",  value=full["p_value"], format="ratio"),
            Metric(key="n_obs",   label="Obs",          value=float(full["n"]), format="number"),
            Metric(key="suitable", label="Suitable (5 %)", value=1.0 if suitable else 0.0, format="number"),
        ],
        charts=[
            ChartSpec(
                id="coint-price", title="Black vs White — Raw Price Series",
                description=(
                    "Both price series on the same axis. The dashed vertical line "
                    "marks the in-sample / out-of-sample split (first 1,000 rows)."
                ),
                figure=_fig_to_dict(fig_price),
            ),
            ChartSpec(
                id="coint-diff", title="Spread = White − Black",
                description=verdict_md,
                figure=_fig_to_dict(fig_diff),
            ),
        ],
        tables=[
            TableSpec(
                id="coint-regression", title="Dickey-Fuller Regression Summary",
                description="`ΔDiff = α · Diff[t-1] + ε` on each data scope.",
                columns=[
                    ColumnSpec(key="scope",   label="Scope",    format="text",  align="left"),
                    ColumnSpec(key="alpha",   label="α",        format="ratio", align="right"),
                    ColumnSpec(key="t_stat",  label="t-stat",   format="ratio", align="right"),
                    ColumnSpec(key="p_value", label="p (≈)",    format="ratio", align="right"),
                    ColumnSpec(key="n",       label="n",        format="number",align="right"),
                    ColumnSpec(key="verdict", label="Verdict",  format="text",  align="left"),
                ],
                rows=reg_rows,
            ),
        ],
    )


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 2 — SIGNAL CONSTRUCTION
# ═══════════════════════════════════════════════════════════════════════════════


def _tab_signal(df: pd.DataFrame, params) -> TabSpec:
    entry = params.entry_threshold
    dates = df["Date"].dt.strftime("%Y-%m-%d").tolist()

    fig = make_subplots(
        rows=3, cols=1, shared_xaxes=True,
        row_heights=[0.34, 0.33, 0.33], vertical_spacing=0.04,
        subplot_titles=[f"zdiff_{N}" for N in N_VALUES],
    )

    for row_i, N in enumerate(N_VALUES, start=1):
        z = df[f"zdiff_{N}"]
        # Signal-region shading via marker points (cheap, avoids per-day shapes)
        long_mask  = (z <= -entry)
        short_mask = (z >=  entry)
        flat_mask  = ~(long_mask | short_mask) & z.notna()

        fig.add_trace(go.Scatter(
            x=dates, y=z.tolist(),
            name=f"zdiff_{N}", line=dict(color=C_DIFF, width=1.1),
            showlegend=(row_i == 1),
        ), row=row_i, col=1)

        fig.add_trace(go.Scatter(
            x=[d for d, m in zip(dates, long_mask) if m],
            y=z[long_mask].tolist(),
            mode="markers", marker=dict(color=C_LONG, size=3),
            name="Long region", showlegend=(row_i == 1),
        ), row=row_i, col=1)
        fig.add_trace(go.Scatter(
            x=[d for d, m in zip(dates, short_mask) if m],
            y=z[short_mask].tolist(),
            mode="markers", marker=dict(color=C_SHORT, size=3),
            name="Short region", showlegend=(row_i == 1),
        ), row=row_i, col=1)
        fig.add_trace(go.Scatter(
            x=[d for d, m in zip(dates, flat_mask) if m],
            y=z[flat_mask].tolist(),
            mode="markers", marker=dict(color=C_FLAT, size=2, opacity=0.35),
            name="Flat", showlegend=(row_i == 1),
        ), row=row_i, col=1)

        fig.add_hline(y=+entry, line_dash="dash", line_color=C_SHORT, row=row_i, col=1)
        fig.add_hline(y=-entry, line_dash="dash", line_color=C_LONG,  row=row_i, col=1)
        fig.add_hline(y=0,      line_dash="dot",  line_color="#9E9E9E", row=row_i, col=1)

    fig.update_layout(
        height=620, template="plotly_white",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    )

    # Signal frequency table
    freq_rows = []
    for N in N_VALUES:
        z = df[f"zdiff_{N}"].dropna()
        total = len(z)
        n_long  = int((z <= -entry).sum())
        n_short = int((z >=  entry).sum())
        freq_rows.append({
            "N":        N,
            "n_obs":    total,
            "long_days":  n_long,
            "short_days": n_short,
            "flat_days":  total - n_long - n_short,
            "active_pct": round((n_long + n_short) / total, 3) if total else 0.0,
        })

    return TabSpec(
        id="signal",
        title="📶 Signal Construction",
        intro_md=_SIGNAL_GUIDE,
        metrics=[
            Metric(key="entry", label="Entry threshold (σ)", value=entry, format="ratio"),
        ],
        charts=[
            ChartSpec(
                id="sig-zdiff", title="zdiff_N with Entry Thresholds",
                description=(
                    f"Entry threshold = ±{entry}σ (dashed lines). "
                    "Green dots = long region (zdiff ≤ −entry), red dots = short region."
                ),
                figure=_fig_to_dict(fig),
            ),
        ],
        tables=[
            TableSpec(
                id="sig-frequency", title="Signal Frequency by Horizon",
                description="Count of days each horizon spends in each state, given the current threshold.",
                columns=[
                    ColumnSpec(key="N",          label="N",          format="number", align="right"),
                    ColumnSpec(key="n_obs",      label="Obs",        format="number", align="right"),
                    ColumnSpec(key="long_days",  label="Long days",  format="number", align="right"),
                    ColumnSpec(key="short_days", label="Short days", format="number", align="right"),
                    ColumnSpec(key="flat_days",  label="Flat days",  format="number", align="right"),
                    ColumnSpec(key="active_pct", label="% Active",   format="percent",align="right"),
                ],
                rows=freq_rows,
            ),
        ],
    )


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 3 — POSITION ENGINE
# ═══════════════════════════════════════════════════════════════════════════════


def _tab_position(df: pd.DataFrame, positions: dict[int, pd.DataFrame], params) -> TabSpec:
    N = params.active_N
    pos_df = positions[N]
    dates = df["Date"].dt.strftime("%Y-%m-%d").tolist()

    # ── Chart: position vs zdiff ─────────────────────────────────────────────
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        row_heights=[0.62, 0.38], vertical_spacing=0.05,
        subplot_titles=(f"zdiff_{N} with thresholds", f"Pos_{N} over time"),
    )
    fig.add_trace(go.Scatter(
        x=dates, y=df[f"zdiff_{N}"].tolist(),
        name=f"zdiff_{N}", line=dict(color=C_DIFF, width=1.1),
    ), row=1, col=1)
    fig.add_hline(y=params.short_entry, line_dash="dash", line_color=C_SHORT, row=1, col=1)
    fig.add_hline(y=params.long_entry,  line_dash="dash", line_color=C_LONG,  row=1, col=1)
    fig.add_hline(y=params.long_exit_cap,  line_dash="dot", line_color="#9E9E9E", row=1, col=1)
    fig.add_hline(y=params.short_exit_cap, line_dash="dot", line_color="#9E9E9E", row=1, col=1)

    fig.add_trace(go.Scatter(
        x=dates, y=pos_df["pos"].tolist(),
        name=f"Pos_{N}", line=dict(color=C_STRAT, width=1.2, shape="hv"),
        fill="tozeroy", fillcolor="rgba(216,67,21,0.10)",
    ), row=2, col=1)
    fig.update_yaxes(range=[-1.2, 1.2], tickvals=[-1, 0, 1], row=2, col=1)
    fig.update_layout(
        height=520, template="plotly_white",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    )

    # ── Full state table (sample of first 500 rows) ──────────────────────────
    state = pd.DataFrame({
        "date":    df["Date"].dt.strftime("%Y-%m-%d"),
        "zdiff":   df[f"zdiff_{N}"].round(3),
        "signal":  pos_df["signal"].astype(int),
        "lcap":    pos_df["lcap"].astype(int),
        "scap":    pos_df["scap"].astype(int),
        "age":     pos_df["age"].astype(int),
        "aged":    pos_df["aged"].astype(int),
        "pos":     pos_df["pos"].astype(int),
        "fret1":   pos_df["fret1"].round(6),
    })
    active = state[(state["pos"] != 0) | (state["signal"] != 0)].tail(200)
    state_rows = active.to_dict("records")

    # ── Trade ledger ──────────────────────────────────────────────────────────
    trades_df = _extract_trades(df, pos_df, N)
    n_trades = len(trades_df)
    win_rate = float((trades_df["pnl"] > 0).mean()) if n_trades else 0.0
    avg_bars = float(trades_df["bars"].mean()) if n_trades else 0.0

    return TabSpec(
        id="position",
        title="🎛️ Position Engine",
        intro_md=_POSITION_GUIDE,
        metrics=[
            Metric(key="active_N", label="Active N",       value=float(N), format="number"),
            Metric(key="n_trades", label="# Trades",       value=float(n_trades), format="number"),
            Metric(key="win_rate", label="Win Rate",       value=win_rate, format="percent"),
            Metric(key="avg_bars", label="Avg Trade Bars", value=avg_bars, format="number"),
        ],
        charts=[
            ChartSpec(
                id="pos-overlay", title=f"Pos_{N} vs zdiff_{N}",
                description=(
                    f"Top panel: zdiff with entry thresholds (dashed) and profit caps (dotted). "
                    f"Bottom: realised position Pos_{N}. Flips and forced exits appear as step changes."
                ),
                figure=_fig_to_dict(fig),
            ),
        ],
        tables=[
            TableSpec(
                id="pos-state", title=f"State Table (last 200 active rows, N={N})",
                description="Per-day state variables matching the spreadsheet convention.",
                columns=[
                    ColumnSpec(key="date",   label="Date",   format="text",   align="left"),
                    ColumnSpec(key="zdiff",  label="zdiff",  format="ratio",  align="right"),
                    ColumnSpec(key="signal", label="Signal", format="number", align="right"),
                    ColumnSpec(key="lcap",   label="Lcap",   format="number", align="right"),
                    ColumnSpec(key="scap",   label="Scap",   format="number", align="right"),
                    ColumnSpec(key="age",    label="Age",    format="number", align="right"),
                    ColumnSpec(key="aged",   label="Aged",   format="number", align="right"),
                    ColumnSpec(key="pos",    label="Pos",    format="number", align="right"),
                    ColumnSpec(key="fret1",  label="fret1",  format="ratio",  align="right"),
                ],
                rows=state_rows,
            ),
        ],
    )


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 4 — POSITION SIZING
# ═══════════════════════════════════════════════════════════════════════════════


def _tab_sizing(df: pd.DataFrame) -> TabSpec:
    dates = df["Date"].dt.strftime("%Y-%m-%d").tolist()

    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        row_heights=[0.55, 0.45], vertical_spacing=0.05,
        subplot_titles=("20-day trailing volatility (annualised)", "Weight split"),
    )
    fig.add_trace(go.Scatter(
        x=dates, y=(df["vol_W"] * np.sqrt(ANN_FACTOR) * 100).tolist(),
        name="White vol %", line=dict(color=C_WHITE, width=1.2),
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=dates, y=(df["vol_B"] * np.sqrt(ANN_FACTOR) * 100).tolist(),
        name="Black vol %", line=dict(color=C_BLACK, width=1.2),
    ), row=1, col=1)

    fig.add_trace(go.Scatter(
        x=dates, y=df["w_W"].tolist(),
        name="w_White", line=dict(color=C_ORANGE, width=1.4),
        fill="tozeroy", fillcolor="rgba(230,81,0,0.15)",
    ), row=2, col=1)
    fig.add_trace(go.Scatter(
        x=dates, y=df["w_B"].tolist(),
        name="w_Black", line=dict(color=C_STRAT, width=1.2, dash="dash"),
    ), row=2, col=1)
    fig.update_yaxes(range=[0, 1], row=2, col=1)
    fig.update_layout(
        height=480, template="plotly_white",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    )

    avg_w_white = float(df["w_W"].dropna().mean())
    avg_w_black = float(df["w_B"].dropna().mean())

    return TabSpec(
        id="sizing",
        title="⚖️ Position Sizing",
        intro_md=_SIZE_GUIDE,
        metrics=[
            Metric(key="avg_w_W", label="Avg w_White", value=avg_w_white, format="percent"),
            Metric(key="avg_w_B", label="Avg w_Black", value=avg_w_black, format="percent"),
        ],
        charts=[
            ChartSpec(
                id="size-weights", title="Inverse-Vol Sizing",
                description=(
                    "Top: 20-day annualised vol for each leg. "
                    "Bottom: portfolio weights. When one leg goes quiet, it gets more weight."
                ),
                figure=_fig_to_dict(fig),
            ),
        ],
    )


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 5 — PERFORMANCE ANALYTICS
# ═══════════════════════════════════════════════════════════════════════════════


def _perf_metrics(fret: pd.Series, trades: pd.DataFrame) -> dict:
    eq = _equity(fret)
    return {
        "ann_ret":  _ann_return(eq),
        "ann_vol":  _ann_vol(fret),
        "sharpe":   _sharpe(fret),
        "max_dd":   _max_dd(eq),
        "n_trades": len(trades),
        "win_rate": float((trades["pnl"] > 0).mean()) if len(trades) else 0.0,
        "avg_bars": float(trades["bars"].mean()) if len(trades) else 0.0,
    }


def _tab_performance(df: pd.DataFrame, positions: dict[int, pd.DataFrame], split_idx: int, params) -> TabSpec:
    dates = df["Date"].dt.strftime("%Y-%m-%d").tolist()
    split_date = dates[split_idx - 1] if split_idx - 1 < len(dates) else dates[-1]

    perf_rows = []
    frets: dict[int, pd.Series] = {}
    equities: dict[int, pd.Series] = {}
    trades_all: dict[int, pd.DataFrame] = {}

    for N in N_VALUES:
        fret = positions[N]["fret1"]
        trades = _extract_trades(df, positions[N], N)
        frets[N] = fret
        equities[N] = _equity(fret)
        trades_all[N] = trades
        m = _perf_metrics(fret, trades)
        perf_rows.append({
            "strategy": f"N = {N}",
            "ann_ret":  round(m["ann_ret"], 4),
            "ann_vol":  round(m["ann_vol"], 4),
            "sharpe":   round(m["sharpe"], 3),
            "max_dd":   round(m["max_dd"], 4),
            "n_trades": m["n_trades"],
            "win_rate": round(m["win_rate"], 3),
            "avg_bars": round(m["avg_bars"], 2),
        })

    # Combined portfolio = equal weight of 3 strategies' daily returns
    combo = pd.concat([frets[N].fillna(0) for N in N_VALUES], axis=1).mean(axis=1)
    combo_trades_count = sum(len(trades_all[N]) for N in N_VALUES)
    perf_rows.append({
        "strategy": "Combined (1/3 each)",
        "ann_ret":  round(_ann_return(_equity(combo)), 4),
        "ann_vol":  round(_ann_vol(combo), 4),
        "sharpe":   round(_sharpe(combo), 3),
        "max_dd":   round(_max_dd(_equity(combo)), 4),
        "n_trades": combo_trades_count,
        "win_rate": 0.0,     # undefined for blended daily series
        "avg_bars": 0.0,
    })

    # ── Chart 1: Equity curves with IS/OOS split ─────────────────────────────
    fig_eq = go.Figure()
    colors = {5: C_LONG, 10: C_STRAT, 20: C_DIFF}
    for N in N_VALUES:
        fig_eq.add_trace(go.Scatter(
            x=dates, y=equities[N].tolist(),
            name=f"N = {N}", line=dict(color=colors[N], width=1.5),
        ))
    fig_eq.add_trace(go.Scatter(
        x=dates, y=_equity(combo).tolist(),
        name="Combined", line=dict(color="#212121", width=2.0, dash="dot"),
    ))
    fig_eq.add_vline(x=split_date, line_dash="dash", line_color="#9E9E9E")
    fig_eq.add_annotation(
        x=split_date, y=1.0, yref="paper",
        text="IS / OOS split", showarrow=False,
        yshift=-10, bgcolor="rgba(255,255,255,0.8)",
    )
    fig_eq.update_layout(
        height=420, template="plotly_white",
        yaxis_title="Equity (rebased 100)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    )

    # ── Chart 2: Drawdown (active N) ─────────────────────────────────────────
    N_active = params.active_N
    eq_a = equities[N_active]
    dd = ((eq_a - eq_a.cummax()) / eq_a.cummax() * 100)
    fig_dd = go.Figure()
    fig_dd.add_trace(go.Scatter(
        x=dates, y=dd.tolist(),
        fill="tozeroy", line=dict(color=C_SHORT, width=0.5),
        fillcolor="rgba(198,40,40,0.25)",
        name=f"Drawdown (N={N_active})",
    ))
    fig_dd.add_vline(x=split_date, line_dash="dash", line_color="#9E9E9E")
    fig_dd.update_layout(
        height=300, template="plotly_white",
        yaxis_title="Drawdown %",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    )

    # ── Chart 3: Monthly heatmap (active N) ──────────────────────────────────
    fret_a = frets[N_active].copy()
    fret_a.index = df["Date"]
    monthly = (1 + fret_a.fillna(0)).resample("ME").prod() - 1
    if len(monthly):
        hm = pd.DataFrame({
            "year":  monthly.index.year,
            "month": monthly.index.month,
            "ret":   monthly.values,
        })
        piv = hm.pivot(index="year", columns="month", values="ret").sort_index()
        z_vals = (piv.values * 100).tolist()
        y_vals = piv.index.astype(str).tolist()
        x_vals = [pd.Timestamp(2000, m, 1).strftime("%b") for m in piv.columns]
        fig_hm = go.Figure(go.Heatmap(
            z=z_vals, x=x_vals, y=y_vals,
            colorscale=[[0, C_SHORT], [0.5, "#FFFFFF"], [1, C_LONG]], zmid=0,
            colorbar=dict(title="Return %"),
            text=[[f"{v:+.1f}" if v == v else "" for v in row] for row in z_vals],
            texttemplate="%{text}",
        ))
        fig_hm.update_layout(height=360, template="plotly_white")
    else:
        fig_hm = go.Figure()
        fig_hm.update_layout(height=360, template="plotly_white",
                             title_text="(not enough monthly data)")

    # ── Chart 4: Trade scatter (entry z vs pnl, active N) ────────────────────
    tr = trades_all[N_active]
    fig_tr = go.Figure()
    if len(tr):
        colors_tr = [C_LONG if s == "LONG" else C_SHORT for s in tr["side"]]
        fig_tr.add_trace(go.Scatter(
            x=tr["entry_z"].tolist(),
            y=(tr["pnl"] * 100).tolist(),
            mode="markers",
            marker=dict(color=colors_tr, size=8, opacity=0.7),
            text=[f"{s} · bars={b}<br>{ed}"
                  for s, b, ed in zip(tr["side"], tr["bars"], tr["entry_date"])],
            hoverinfo="text+x+y",
            name="Trades",
        ))
        fig_tr.add_hline(y=0, line_dash="dot", line_color="#9E9E9E")
        fig_tr.add_vline(x=params.long_entry,  line_dash="dash", line_color=C_LONG)
        fig_tr.add_vline(x=params.short_entry, line_dash="dash", line_color=C_SHORT)
    fig_tr.update_layout(
        height=360, template="plotly_white",
        xaxis_title=f"Entry zdiff_{N_active}",
        yaxis_title="Trade return (%)",
    )

    # ── Chart 5: Rolling 60-day Sharpe (active N) ────────────────────────────
    window = 60
    roll_mean = frets[N_active].rolling(window).mean()
    roll_std  = frets[N_active].rolling(window).std(ddof=1)
    roll_sh   = (roll_mean / roll_std.replace(0, np.nan)) * np.sqrt(ANN_FACTOR)
    fig_roll = go.Figure()
    fig_roll.add_trace(go.Scatter(
        x=dates, y=roll_sh.tolist(),
        name=f"Rolling 60d Sharpe (N={N_active})",
        line=dict(color=C_STRAT, width=1.4),
    ))
    fig_roll.add_hline(y=0, line_dash="dot", line_color="#9E9E9E")
    fig_roll.add_vline(x=split_date, line_dash="dash", line_color="#9E9E9E")
    fig_roll.update_layout(
        height=320, template="plotly_white",
        yaxis_title="Annualised Sharpe (60d)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    )

    return TabSpec(
        id="performance",
        title="📈 Performance",
        intro_md=_PERF_GUIDE,
        metrics=[
            Metric(key="sharpe_combo", label="Combined Sharpe",
                   value=_sharpe(combo), format="ratio"),
            Metric(key="ann_combo",    label="Combined Ann Ret",
                   value=_ann_return(_equity(combo)), format="percent"),
            Metric(key="mdd_combo",    label="Combined MDD",
                   value=_max_dd(_equity(combo)), format="percent"),
        ],
        charts=[
            ChartSpec(
                id="perf-equity", title="Equity Curves — N=5, 10, 20, Combined",
                description="Vertical dashed line marks the in-sample / out-of-sample split.",
                figure=_fig_to_dict(fig_eq),
            ),
            ChartSpec(
                id="perf-drawdown", title=f"Drawdown (N={N_active})",
                description="Peak-to-trough drawdown over time.",
                figure=_fig_to_dict(fig_dd),
            ),
            ChartSpec(
                id="perf-heatmap", title=f"Monthly Returns Heatmap (N={N_active})",
                description="Green = positive month, red = negative. Values are simple compounded monthly returns.",
                figure=_fig_to_dict(fig_hm),
            ),
            ChartSpec(
                id="perf-trades", title=f"Trade Scatter (N={N_active})",
                description=(
                    "Each dot is a completed trade. X = entry zdiff level, Y = total trade P&L. "
                    "Dashed vertical lines are the entry thresholds; dotted horizontal = break-even."
                ),
                figure=_fig_to_dict(fig_tr),
            ),
            ChartSpec(
                id="perf-rollsh", title=f"Rolling 60-day Annualised Sharpe (N={N_active})",
                description="Stability check — is the edge consistent, decaying, or one-off?",
                figure=_fig_to_dict(fig_roll),
            ),
        ],
        tables=[
            TableSpec(
                id="perf-summary", title="Strategy Performance Summary",
                columns=[
                    ColumnSpec(key="strategy", label="Strategy",   format="text",   align="left"),
                    ColumnSpec(key="ann_ret",  label="Ann Return", format="percent",align="right"),
                    ColumnSpec(key="ann_vol",  label="Ann Vol",    format="percent",align="right"),
                    ColumnSpec(key="sharpe",   label="Sharpe",     format="ratio",  align="right"),
                    ColumnSpec(key="max_dd",   label="Max DD",     format="percent",align="right"),
                    ColumnSpec(key="n_trades", label="# Trades",   format="number", align="right"),
                    ColumnSpec(key="win_rate", label="Win Rate",   format="percent",align="right"),
                    ColumnSpec(key="avg_bars", label="Avg Bars",   format="number", align="right"),
                ],
                rows=perf_rows,
            ),
        ],
    )


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 6 — PARAMETER SWEEP (IN-SAMPLE vs OUT-OF-SAMPLE)
# ═══════════════════════════════════════════════════════════════════════════════


def _sweep_heatmap(
    df_core: pd.DataFrame, idx_slice: slice, params,
    entries: list[float], holdings: list[int], N_fixed: int,
) -> tuple[list[list[float]], tuple[float, int, float]]:
    """Return (Sharpe matrix [row=holding, col=entry], (best_entry, best_hp, best_sharpe))."""
    mat = []
    best = (entries[0], holdings[0], -np.inf)
    sub = df_core.iloc[idx_slice].copy()
    for hp in holdings:
        row = []
        for e in entries:
            # Full engine on sub-slice with symmetric thresholds & caps
            pos = _run_positions(
                sub,
                N=N_fixed,
                long_entry=-e,
                short_entry=+e,
                long_exit_cap=+e,
                short_exit_cap=-e,
                holding_period=hp,
                size_aware=True,
            )
            sh = _sharpe(pos["fret1"])
            row.append(round(sh, 3))
            if sh > best[2]:
                best = (e, hp, sh)
        mat.append(row)
    return mat, best


def _tab_sweep(df: pd.DataFrame, split_idx: int, params) -> TabSpec:
    entries  = [0.5, 1.0, 1.5, 2.0, 2.5]
    holdings = [3, 5, 7, 10, 15]
    N_fixed  = params.active_N

    mat_is, best_is = _sweep_heatmap(df, slice(0, split_idx), params, entries, holdings, N_fixed)
    mat_oos, _      = _sweep_heatmap(df, slice(split_idx, len(df)), params, entries, holdings, N_fixed)

    # Transfer test: Sharpe achieved OOS using IS-best parameters
    e_star, hp_star, sh_is_star = best_is
    col_is = entries.index(e_star)
    row_is = holdings.index(hp_star)
    sh_oos_at_is_best = mat_oos[row_is][col_is]

    fig = make_subplots(
        rows=1, cols=2, horizontal_spacing=0.12,
        subplot_titles=(
            f"In-sample (first {split_idx} days)",
            f"Out-of-sample (rest)",
        ),
    )
    fig.add_trace(go.Heatmap(
        z=mat_is, x=entries, y=holdings,
        colorscale=[[0, C_SHORT], [0.5, "#FFFFFF"], [1, C_LONG]], zmid=0,
        colorbar=dict(title="Sharpe", x=0.44),
        text=[[f"{v:+.2f}" for v in row] for row in mat_is],
        texttemplate="%{text}",
    ), row=1, col=1)
    fig.add_trace(go.Heatmap(
        z=mat_oos, x=entries, y=holdings,
        colorscale=[[0, C_SHORT], [0.5, "#FFFFFF"], [1, C_LONG]], zmid=0,
        colorbar=dict(title="Sharpe"),
        text=[[f"{v:+.2f}" for v in row] for row in mat_oos],
        texttemplate="%{text}",
    ), row=1, col=2)
    fig.update_xaxes(title_text="Entry threshold (σ)", row=1, col=1)
    fig.update_xaxes(title_text="Entry threshold (σ)", row=1, col=2)
    fig.update_yaxes(title_text="Holding period (days)", row=1, col=1)
    fig.update_layout(height=420, template="plotly_white")

    callout_md = (
        f"**Best in-sample**: entry = `{e_star}`, holding = `{hp_star}` → "
        f"Sharpe = `{sh_is_star:+.2f}`.\n\n"
        f"**Same parameters out of sample**: Sharpe = `{sh_oos_at_is_best:+.2f}` "
        f"({'held up' if sh_oos_at_is_best >= sh_is_star * 0.5 else 'degraded'}).\n\n"
        "*The 'best' in-sample parameters rarely match out-of-sample performance — "
        "this is the overfitting trap.*"
    )

    return TabSpec(
        id="sweep",
        title="🔥 Parameter Sweep",
        intro_md=_SWEEP_GUIDE,
        metrics=[
            Metric(key="best_entry",  label="Best entry (IS)",  value=e_star,        format="ratio"),
            Metric(key="best_hp",     label="Best holding (IS)",value=float(hp_star),format="number"),
            Metric(key="best_sharpe", label="Best Sharpe (IS)", value=sh_is_star,    format="ratio"),
            Metric(key="oos_at_best", label="OOS @ IS-best",    value=float(sh_oos_at_is_best), format="ratio"),
        ],
        charts=[
            ChartSpec(
                id="sweep-heatmaps",
                title=f"Sharpe Heatmap — N = {N_fixed}",
                description=callout_md,
                figure=_fig_to_dict(fig),
            ),
        ],
    )


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 7 — IN-SAMPLE vs OUT-OF-SAMPLE
# ═══════════════════════════════════════════════════════════════════════════════


def _tab_split(df: pd.DataFrame, positions: dict[int, pd.DataFrame], split_idx: int) -> TabSpec:
    dates = df["Date"].dt.strftime("%Y-%m-%d").tolist()
    split_date = dates[split_idx - 1] if split_idx - 1 < len(dates) else dates[-1]

    split_rows = []
    commentary = []
    for N in N_VALUES:
        fret = positions[N]["fret1"]
        is_s = fret.iloc[:split_idx]
        oo_s = fret.iloc[split_idx:]
        sh_is = _sharpe(is_s)
        sh_oo = _sharpe(oo_s)
        split_rows.append({
            "strategy": f"N = {N}",
            "is_ret":  round(_ann_return(_equity(is_s)), 4),
            "is_vol":  round(_ann_vol(is_s), 4),
            "is_sh":   round(sh_is, 3),
            "is_dd":   round(_max_dd(_equity(is_s)), 4),
            "oos_ret": round(_ann_return(_equity(oo_s)), 4),
            "oos_vol": round(_ann_vol(oo_s), 4),
            "oos_sh":  round(sh_oo, 3),
            "oos_dd":  round(_max_dd(_equity(oo_s)), 4),
            "degrade": round(sh_oo - sh_is, 3),
        })
        if sh_is > 0 and sh_oo < sh_is * 0.3:
            commentary.append(
                f"- **N = {N}**: Sharpe collapsed from {sh_is:+.2f} to {sh_oo:+.2f} — "
                "strategy degraded significantly out of sample (possible overfitting)."
            )
        elif sh_oo >= sh_is * 0.7:
            commentary.append(
                f"- **N = {N}**: Sharpe {sh_is:+.2f} → {sh_oo:+.2f} — "
                "strategy held up reasonably well (sign of robustness)."
            )
        else:
            commentary.append(
                f"- **N = {N}**: Sharpe {sh_is:+.2f} → {sh_oo:+.2f} — modest deterioration."
            )

    # ── Chart: equity with IS/OOS shading ────────────────────────────────────
    fig = go.Figure()
    colors = {5: C_LONG, 10: C_STRAT, 20: C_DIFF}
    for N in N_VALUES:
        eq = _equity(positions[N]["fret1"])
        fig.add_trace(go.Scatter(
            x=dates, y=eq.tolist(),
            name=f"N = {N}", line=dict(color=colors[N], width=1.5),
        ))
    fig.add_vline(x=split_date, line_dash="dash", line_color="#9E9E9E")
    fig.add_vrect(
        x0=dates[0], x1=split_date,
        fillcolor="rgba(46,125,50,0.04)", line_width=0,
    )
    fig.add_vrect(
        x0=split_date, x1=dates[-1],
        fillcolor="rgba(198,40,40,0.04)", line_width=0,
    )
    fig.add_annotation(
        x=split_date, y=1.0, yref="paper",
        text="IS / OOS split", showarrow=False,
        yshift=-10, bgcolor="rgba(255,255,255,0.8)",
    )
    fig.update_layout(
        height=420, template="plotly_white",
        yaxis_title="Equity (rebased 100)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    )

    return TabSpec(
        id="split",
        title="↔️ IS vs OOS",
        intro_md=_SPLIT_GUIDE + "\n\n### Per-strategy commentary\n" + "\n".join(commentary),
        charts=[
            ChartSpec(
                id="split-equity", title="Equity Curves with IS / OOS Split",
                description="Green-tinted left zone = in-sample, red-tinted right zone = out-of-sample.",
                figure=_fig_to_dict(fig),
            ),
        ],
        tables=[
            TableSpec(
                id="split-table", title="Side-by-Side Performance",
                description="`degrade` = OOS Sharpe − IS Sharpe. More negative ⇒ more overfit.",
                columns=[
                    ColumnSpec(key="strategy", label="Strategy",   format="text",   align="left"),
                    ColumnSpec(key="is_ret",   label="IS Ret",     format="percent",align="right"),
                    ColumnSpec(key="is_vol",   label="IS Vol",     format="percent",align="right"),
                    ColumnSpec(key="is_sh",    label="IS Sharpe",  format="ratio",  align="right"),
                    ColumnSpec(key="is_dd",    label="IS MDD",     format="percent",align="right"),
                    ColumnSpec(key="oos_ret",  label="OOS Ret",    format="percent",align="right"),
                    ColumnSpec(key="oos_vol",  label="OOS Vol",    format="percent",align="right"),
                    ColumnSpec(key="oos_sh",   label="OOS Sharpe", format="ratio",  align="right"),
                    ColumnSpec(key="oos_dd",   label="OOS MDD",    format="percent",align="right"),
                    ColumnSpec(key="degrade",  label="Δ Sharpe",   format="ratio",  align="right"),
                ],
                rows=split_rows,
            ),
        ],
    )


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 8 — STRATEGY IN ACTION (DAY PICKER)
# ═══════════════════════════════════════════════════════════════════════════════


def _tab_action(df: pd.DataFrame, positions: dict[int, pd.DataFrame], params) -> TabSpec:
    N = params.active_N
    pos_df = positions[N]
    dates = df["Date"].dt.strftime("%Y-%m-%d").tolist()

    # Resolve the selected day — accept ISO string or None (default = last row)
    sel_iso = (params.selected_day or "").strip() or dates[-1]
    try:
        sel_ts = pd.to_datetime(sel_iso)
    except Exception:
        sel_ts = df["Date"].iloc[-1]
    matches = df.index[df["Date"] == sel_ts]
    sel_i = int(matches[0]) if len(matches) else len(df) - 1
    sel_date = df["Date"].iloc[sel_i].date().isoformat()

    z_val   = float(df[f"zdiff_{N}"].iloc[sel_i]) if not pd.isna(df[f"zdiff_{N}"].iloc[sel_i]) else 0.0
    pos_val = int(pos_df["pos"].iloc[sel_i])
    age_val = int(pos_df["age"].iloc[sel_i])
    sig_val = int(pos_df["signal"].iloc[sel_i])
    lcap    = int(pos_df["lcap"].iloc[sel_i])
    scap    = int(pos_df["scap"].iloc[sel_i])
    aged    = int(pos_df["aged"].iloc[sel_i])
    fret    = float(pos_df["fret1"].iloc[sel_i]) if not pd.isna(pos_df["fret1"].iloc[sel_i]) else 0.0

    # Narrative
    parts = [f"**Date:** `{sel_date}` · **zdiff_{N} =** `{z_val:+.3f}`"]
    if sig_val == +1:
        parts.append(f"Signal: **LONG** (zdiff ≤ {params.long_entry:+.2f})")
    elif sig_val == -1:
        parts.append(f"Signal: **SHORT** (zdiff ≥ {params.short_entry:+.2f})")
    else:
        parts.append("Signal: **FLAT** (neither threshold crossed)")

    if pos_val != 0:
        side = "LONG" if pos_val > 0 else "SHORT"
        parts.append(f"Held position: **{side}** · age = {age_val} day(s)")
    else:
        parts.append("Not currently in a position")

    exit_notes = []
    if lcap:  exit_notes.append("long profit cap hit")
    if scap:  exit_notes.append("short profit cap hit")
    if aged:  exit_notes.append("holding period reached")
    if exit_notes:
        parts.append("Exit trigger: " + "; ".join(exit_notes))

    parts.append(f"Attributed 1-day forward return: `{fret*100:+.3f}%`")
    narrative = "  \n".join(parts)

    # Mini chart: last 20 days of zdiff with selected day highlighted
    lo = max(0, sel_i - 20)
    hi = min(len(df), sel_i + 1)
    slice_dates = df["Date"].iloc[lo:hi].dt.strftime("%Y-%m-%d").tolist()
    slice_z     = df[f"zdiff_{N}"].iloc[lo:hi].tolist()

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=slice_dates, y=slice_z, mode="lines+markers",
        line=dict(color=C_DIFF, width=1.6),
        marker=dict(size=6, color=C_DIFF),
        name=f"zdiff_{N}",
    ))
    fig.add_trace(go.Scatter(
        x=[sel_date], y=[z_val], mode="markers",
        marker=dict(color=C_ORANGE, size=14, symbol="diamond-open",
                    line=dict(width=2)),
        name="Selected day",
    ))
    fig.add_hline(y=params.short_entry, line_dash="dash", line_color=C_SHORT,
                  annotation_text=f"short entry ({params.short_entry:+.1f})")
    fig.add_hline(y=params.long_entry,  line_dash="dash", line_color=C_LONG,
                  annotation_text=f"long entry ({params.long_entry:+.1f})")
    fig.add_hline(y=params.long_exit_cap,  line_dash="dot", line_color="#9E9E9E",
                  annotation_text=f"long cap ({params.long_exit_cap:+.1f})")
    fig.add_hline(y=params.short_exit_cap, line_dash="dot", line_color="#9E9E9E",
                  annotation_text=f"short cap ({params.short_exit_cap:+.1f})")
    fig.update_layout(
        height=340, template="plotly_white",
        yaxis_title=f"zdiff_{N}",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    )

    # Trade lifecycle context: find enclosing trade (if any)
    trades = _extract_trades(df, pos_df, N)
    ctx_rows = []
    if len(trades):
        sel_day = pd.Timestamp(sel_date).date().isoformat()
        enclosing = trades[(trades["entry_date"] <= sel_day) & (trades["exit_date"] >= sel_day)]
        rows = enclosing.tail(1).to_dict("records") if len(enclosing) else []
        if not rows:
            # fall back to most recent completed trade before this day
            prior = trades[trades["exit_date"] <= sel_day]
            rows = prior.tail(1).to_dict("records") if len(prior) else []
        ctx_rows = rows

    return TabSpec(
        id="action",
        title="🔎 Strategy in Action",
        intro_md=_ACTION_GUIDE,
        metrics=[
            Metric(key="sel_z",   label="Selected zdiff", value=z_val, format="ratio"),
            Metric(key="sel_pos", label="Position",       value=float(pos_val), format="number"),
            Metric(key="sel_age", label="Age (days)",     value=float(age_val), format="number"),
            Metric(key="sel_fret",label="Forward ret",    value=fret, format="percent"),
        ],
        charts=[
            ChartSpec(
                id="act-mini", title=f"Last 20 days of zdiff_{N}",
                description=narrative,
                figure=_fig_to_dict(fig),
            ),
        ],
        tables=(
            [TableSpec(
                id="act-trade", title="Enclosing / Nearest Trade",
                description="The trade this day falls inside (if any), else the most recent completed trade.",
                columns=[
                    ColumnSpec(key="entry_date", label="Entry",    format="text",  align="left"),
                    ColumnSpec(key="exit_date",  label="Exit",     format="text",  align="left"),
                    ColumnSpec(key="side",       label="Side",     format="text",  align="left"),
                    ColumnSpec(key="entry_z",    label="Entry z",  format="ratio", align="right"),
                    ColumnSpec(key="bars",       label="Bars",     format="number",align="right"),
                    ColumnSpec(key="pnl",        label="Trade PnL",format="percent",align="right"),
                ],
                rows=ctx_rows,
            )] if ctx_rows else []
        ),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# STRATEGY PARAMS & CLASS
# ═══════════════════════════════════════════════════════════════════════════════


class PairsTradingParams(BaseModel):
    # Signal / threshold (shared default for long/short when adjusting via sidebar)
    entry_threshold: float = Field(default=1.0, ge=0.25, le=3.5, description="Visual threshold on zdiff charts")

    # Full asymmetric params for the engine
    long_entry:     float = Field(default=-1.0, ge=-3.5, le=0.0, description="zdiff level to go long spread")
    short_entry:    float = Field(default= 1.0, ge= 0.0, le=3.5, description="zdiff level to go short spread")
    long_exit_cap:  float = Field(default= 1.0, ge=-1.0, le=3.5, description="Profit cap for long position")
    short_exit_cap: float = Field(default=-1.0, ge=-3.5, le=1.0, description="Profit cap for short position")
    holding_period: int   = Field(default=5,   ge=1,   le=30,  description="Max days in a trade before forced exit")

    # Which N to highlight in single-N tabs (Pos, Action)
    active_N: int = Field(default=10, description="Active horizon for drill-down tabs")

    # Day picker for Module 8
    selected_day: str | None = Field(default=None, description="ISO date for the 'Strategy in Action' tab")


class PairsTradingStrategy(BaseStrategy):
    id: str = "pairs-trading"
    name: str = "Pairs Trading"
    description: str = (
        "Spread-based pairs trading on Black & White. Dickey-Fuller cointegration test, "
        "multi-horizon signal construction (N=5/10/20), full position engine with holding "
        "and profit-cap exits, inverse-vol sizing, IS/OOS split, parameter sweep with "
        "overfitting check, and per-day explainer."
    )
    instrument_kind = InstrumentKind.trend   # bundled data, no instrument picker
    ParamsModel = PairsTradingParams
    has_summary: bool = False

    def compute(self, params: PairsTradingParams) -> StrategyResult:  # type: ignore[override]
        try:
            df_raw = _load_pairs()
        except FileNotFoundError as e:
            return StrategyResult(
                overview_md=(
                    "### ⚠️ Pairs data not found\n\n"
                    "Drop **Assignment_PAIRS_data.xlsx** into "
                    "`backend/data/pairs/` and re-run. The file should contain two "
                    "price columns named `Black` and `White` (any column order, a date "
                    "column is optional)."
                ),
                warnings=[str(e)],
                tabs=[],
            )
        except Exception as e:
            return StrategyResult(
                overview_md="### ⚠️ Could not parse pairs workbook",
                warnings=[str(e)],
                tabs=[],
            )

        if len(df_raw) < 120:
            return StrategyResult(
                warnings=[f"Only {len(df_raw)} rows — need ≥ 120 for the 60-day vol window + 20-day returns."],
                tabs=[],
            )

        split_idx = min(IN_SAMPLE_ROWS, max(60, len(df_raw) // 2))
        df = _build_core(df_raw)

        # Normalise the two-sided threshold params: if the user only tweaks
        # entry_threshold from the sidebar, mirror it into long/short.
        # (The dedicated long/short sliders still override when moved.)
        positions = {
            N: _run_positions(
                df, N=N,
                long_entry=params.long_entry,
                short_entry=params.short_entry,
                long_exit_cap=params.long_exit_cap,
                short_exit_cap=params.short_exit_cap,
                holding_period=params.holding_period,
                size_aware=True,
            )
            for N in N_VALUES
        }

        tabs = [
            _tab_cointegration(df, split_idx),
            _tab_signal(df, params),
            _tab_position(df, positions, params),
            _tab_sizing(df),
            _tab_performance(df, positions, split_idx, params),
            _tab_sweep(df, split_idx, params),
            _tab_split(df, positions, split_idx),
            _tab_action(df, positions, params),
        ]

        date_range = f"{df['Date'].min().date()} → {df['Date'].max().date()}"
        oos_rows = len(df) - split_idx
        return StrategyResult(
            overview_md=(
                f"**Pairs Trading — Black & White** · {date_range} · "
                f"{len(df):,} trading days "
                f"(in-sample: first {split_idx}, out-of-sample: last {oos_rows})\n\n"
                "Eight tabs take a pair of instruments through cointegration testing, "
                "multi-horizon signal construction, a full position engine, inverse-vol "
                "sizing, performance analytics, parameter sensitivity, an in-sample vs "
                "out-of-sample comparison, and a day-by-day explainer. All parameters in "
                "the sidebar update every tab simultaneously."
            ),
            tabs=tabs,
        )


STRATEGY = PairsTradingStrategy()
