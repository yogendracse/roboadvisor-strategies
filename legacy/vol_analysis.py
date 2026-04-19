"""
Systematic Volatility Analysis (VOL)
Lead-Lag relationship between normalized market volatility and future equity returns.
Data: S&P 500 daily closes (1960-01-04 to 2000-12-29)
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

# ─────────────────────────────────────────────────────────────────────────────
# PHASE 1 – DATA INGESTION & PREPROCESSING
# ─────────────────────────────────────────────────────────────────────────────

DATA_PATH = "SP data.xlsx"
WINDOW    = 20    # trading days ≈ 1 month
NORM_WIN  = 250   # trading days ≈ 1 year (Z-score window)

df = pd.read_excel(DATA_PATH, usecols=["Date", "Close"])
df = df.sort_values("Date").reset_index(drop=True)

# Daily returns
df["ret1"] = df["Close"].pct_change()

# ─────────────────────────────────────────────────────────────────────────────
# PHASE 2 – INDICATOR ENGINEERING
# ─────────────────────────────────────────────────────────────────────────────

# vol20: 20-day rolling std of daily returns (annualised for readability)
df["vol20"] = df["ret1"].rolling(WINDOW).std()

# ret20: 20-day trailing (historical) compounded return
df["ret20"] = df["Close"].pct_change(periods=WINDOW)

# fret20: 20-day LEADING (future) compounded return  → shift(-20)
df["fret20"] = df["ret20"].shift(-WINDOW)

# ─────────────────────────────────────────────────────────────────────────────
# PHASE 3 – NORMALISATION (Z-SCORE)
# ─────────────────────────────────────────────────────────────────────────────

def rolling_zscore(series: pd.Series, window: int) -> pd.Series:
    """Z-score each observation relative to a trailing 'window' of history."""
    rm  = series.rolling(window).mean()
    rs  = series.rolling(window).std(ddof=1)
    return (series - rm) / rs

df["zvol20"]  = rolling_zscore(df["vol20"],  NORM_WIN)
df["zret20"]  = rolling_zscore(df["ret20"],  NORM_WIN)
df["zfret20"] = rolling_zscore(df["fret20"], NORM_WIN)

# ─────────────────────────────────────────────────────────────────────────────
# CLEANUP – drop "burned" rows
# First (WINDOW + NORM_WIN) = 270 rows have NaN from look-back.
# Last WINDOW = 20 rows have NaN fret20 from look-ahead.
# ─────────────────────────────────────────────────────────────────────────────

df_clean = df.dropna(subset=["zvol20", "zret20", "zfret20"]).copy()
df_clean.reset_index(drop=True, inplace=True)

print(f"Total rows in source   : {len(df):,}")
print(f"Rows after cleanup     : {len(df_clean):,}")
print(f"Date range (clean)     : {df_clean['Date'].iloc[0].date()} → {df_clean['Date'].iloc[-1].date()}")
print(f"zvol20  → mean={df_clean['zvol20'].mean():.4f}  std={df_clean['zvol20'].std():.4f}")
print(f"zret20  → mean={df_clean['zret20'].mean():.4f}  std={df_clean['zret20'].std():.4f}")
print(f"zfret20 → mean={df_clean['zfret20'].mean():.4f}  std={df_clean['zfret20'].std():.4f}")

# ─────────────────────────────────────────────────────────────────────────────
# PHASE 4 – QUINTILE BUCKETING
# Sort by zvol20, assign quintile labels 1 (lowest vol) … 5 (highest vol)
# ─────────────────────────────────────────────────────────────────────────────

df_sorted = df_clean.sort_values("zvol20").reset_index(drop=True)
df_sorted["quintile"] = pd.qcut(df_sorted["zvol20"], q=5, labels=[1, 2, 3, 4, 5])

quintile_summary = (
    df_sorted.groupby("quintile", observed=True)
    .agg(
        count       = ("zvol20",  "count"),
        avg_zvol20  = ("zvol20",  "mean"),
        avg_zret20  = ("zret20",  "mean"),   # concurrent
        avg_zfret20 = ("zfret20", "mean"),   # lead-lag
    )
    .reset_index()
)
quintile_summary["quintile"] = quintile_summary["quintile"].astype(int)

print("\n── Quintile Summary ──────────────────────────────────────────────────")
print(quintile_summary.to_string(index=False))

# ─────────────────────────────────────────────────────────────────────────────
# PHASE 5 – STRATEGY EVALUATION
#
# Data-driven finding (Phase 4):
#   Q1 (low vol)  → concurrent returns POSITIVE but FUTURE returns NEGATIVE
#   Q5 (high vol) → concurrent returns NEGATIVE but FUTURE returns POSITIVE
#
# This is a mean-reversion signal.
#
# Mean-Reversion strategy  : Long Q5 (high vol → positive fret), Short Q1
# Original hypothesis test : Long Q1 (low vol), Short Q5 — tested for contrast
#
# IR formula: (Mean_daily_return × 252) / (Std_daily_return × √252)
# ─────────────────────────────────────────────────────────────────────────────

df_strat = df_clean.copy()
df_strat["quintile"] = pd.qcut(df_strat["zvol20"], q=5, labels=[1, 2, 3, 4, 5])
df_strat["quintile"] = df_strat["quintile"].astype(int)

def calc_ir(signal_series, ret_series):
    """Annualised Information Ratio for a strategy."""
    strat_ret = signal_series * ret_series
    active    = strat_ret[signal_series != 0]
    mean_ann  = active.mean() * 252
    std_ann   = active.std()  * np.sqrt(252)
    ir_val    = mean_ann / std_ann if std_ann != 0 else np.nan
    return active, mean_ann, std_ann, ir_val

# ── Strategy A: Mean-Reversion (data-supported) ──
sig_mr   = np.where(df_strat["quintile"] == 5,  1,    # long high-vol
           np.where(df_strat["quintile"] == 1, -1, 0)) # short low-vol
df_strat["sig_mr"] = sig_mr
active_mr, mean_mr, std_mr, ir_mr = calc_ir(pd.Series(sig_mr), df_strat["fret20"])

# ── Strategy B: Original hypothesis (momentum / high-vol short) ──
sig_orig = np.where(df_strat["quintile"] == 1,  1,    # long low-vol
           np.where(df_strat["quintile"] == 5, -1, 0)) # short high-vol
df_strat["sig_orig"] = sig_orig
active_orig, mean_orig, std_orig, ir_orig = calc_ir(pd.Series(sig_orig), df_strat["fret20"])

print("\n── Strategy A: Mean-Reversion  (Long Q5 / Short Q1) ─────────────────")
print(f"  Active observations  : {len(active_mr):,}")
print(f"  Mean ann. return     : {mean_mr*100:.2f}%")
print(f"  Ann. std of returns  : {std_mr*100:.2f}%")
print(f"  Information Ratio    : {ir_mr:.4f}")

print("\n── Strategy B: Original Hypothesis (Long Q1 / Short Q5) ─────────────")
print(f"  Active observations  : {len(active_orig):,}")
print(f"  Mean ann. return     : {mean_orig*100:.2f}%")
print(f"  Ann. std of returns  : {std_orig*100:.2f}%")
print(f"  Information Ratio    : {ir_orig:.4f}")

# Use Strategy A for the chart annotation
ir = ir_mr

# ─────────────────────────────────────────────────────────────────────────────
# PLOTS
# ─────────────────────────────────────────────────────────────────────────────

fig, axes = plt.subplots(1, 3, figsize=(16, 6))
fig.suptitle("Systematic Volatility Analysis – S&P 500\n(Z-scored indicators, 250-day normalisation window)",
             fontsize=13, fontweight="bold")

qs     = quintile_summary["quintile"]
colors = ["#2196F3", "#64B5F6", "#90CAF9", "#EF9A9A", "#F44336"]

def bar_chart(ax, values, title, ylabel, color_list):
    bars = ax.bar(qs, values, color=color_list, edgecolor="white", linewidth=0.8)
    ax.axhline(0, color="black", linewidth=0.8, linestyle="--")
    ax.set_title(title, fontsize=11, fontweight="bold")
    ax.set_xlabel("Volatility Quintile  (1 = Low, 5 = High)", fontsize=9)
    ax.set_ylabel(ylabel, fontsize=9)
    ax.set_xticks(qs)
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.2f"))
    for bar, val in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width() / 2,
                bar.get_height() + (0.02 if val >= 0 else -0.05),
                f"{val:.3f}", ha="center", va="bottom", fontsize=8)

bar_chart(axes[0],
          quintile_summary["avg_zvol20"],
          "Average Z-Vol (zvol20)\nby Quintile",
          "Z-score", colors)

bar_chart(axes[1],
          quintile_summary["avg_zret20"],
          "Concurrent Return (zret20)\nby Vol Quintile",
          "Z-score", colors)

bar_chart(axes[2],
          quintile_summary["avg_zfret20"],
          "Future 20-Day Return (zfret20)\nby Vol Quintile  [Lead-Lag]",
          "Z-score", colors)

# Annotate lead-lag chart with IR
axes[2].annotate(f"Mean-Reversion IR (L Q5 / S Q1): {ir:.3f}",
                 xy=(0.5, 0.02), xycoords="axes fraction",
                 ha="center", fontsize=8.5,
                 bbox=dict(boxstyle="round,pad=0.3", fc="#FFF9C4", ec="#F9A825"))

plt.tight_layout()
out_path = "vol_analysis_results.png"
plt.savefig(out_path, dpi=150, bbox_inches="tight")
print(f"\nPlot saved → {out_path}")
plt.show()
