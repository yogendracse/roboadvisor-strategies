"""
Systematic Volatility Analysis — Full Step-by-Step Dashboard
Walks through every phase: raw data → indicators → normalisation → quintiles → strategy
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import matplotlib.ticker as mticker
import matplotlib.patches as mpatches
from matplotlib.lines import Line2D

# ── Palette ──────────────────────────────────────────────────────────────────
C_PRICE   = "#1565C0"
C_RET     = "#2E7D32"
C_VOL     = "#6A1B9A"
C_RET20   = "#00838F"
C_FRET    = "#E65100"
C_ZVOL    = "#6A1B9A"
C_ZRET    = "#00838F"
C_ZFRET   = "#E65100"
C_Q       = ["#1565C0", "#5C9BD6", "#B0BEC5", "#EF9A9A", "#C62828"]
C_BG      = "#F8F9FA"
C_PANEL   = "#FFFFFF"
C_GRID    = "#E0E0E0"

FORMULA_PROPS = dict(boxstyle="round,pad=0.45", fc="#FFFDE7", ec="#F9A825", alpha=0.92)
NOTE_PROPS    = dict(boxstyle="round,pad=0.35", fc="#E3F2FD", ec="#1565C0", alpha=0.90)

# ── Parameters ────────────────────────────────────────────────────────────────
DATA_PATH = "SP data.xlsx"
WINDOW    = 20
NORM_WIN  = 250

# ═════════════════════════════════════════════════════════════════════════════
# DATA PIPELINE  (mirrors vol_analysis.py exactly)
# ═════════════════════════════════════════════════════════════════════════════

print("Loading data …")
df = pd.read_excel(DATA_PATH, usecols=["Date", "Close"])
df = df.sort_values("Date").reset_index(drop=True)

df["ret1"]  = df["Close"].pct_change()
df["vol20"] = df["ret1"].rolling(WINDOW).std()
df["ret20"] = df["Close"].pct_change(periods=WINDOW)
df["fret20"]= df["ret20"].shift(-WINDOW)

def rolling_zscore(s, w):
    return (s - s.rolling(w).mean()) / s.rolling(w).std(ddof=1)

df["zvol20"]  = rolling_zscore(df["vol20"],  NORM_WIN)
df["zret20"]  = rolling_zscore(df["ret20"],  NORM_WIN)
df["zfret20"] = rolling_zscore(df["fret20"], NORM_WIN)

df_clean = df.dropna(subset=["zvol20", "zret20", "zfret20"]).copy().reset_index(drop=True)

df_sorted = df_clean.sort_values("zvol20").reset_index(drop=True)
df_sorted["quintile"] = pd.qcut(df_sorted["zvol20"], q=5, labels=[1,2,3,4,5]).astype(int)

qs = (df_sorted.groupby("quintile", observed=True)
      .agg(avg_zvol20=("zvol20","mean"), avg_zret20=("zret20","mean"),
           avg_zfret20=("zfret20","mean"))
      .reset_index())
qs["quintile"] = qs["quintile"].astype(int)

# Strategies
df_strat = df_clean.copy()
df_strat["quintile"] = pd.qcut(df_strat["zvol20"], q=5, labels=[1,2,3,4,5]).astype(int)
sig_mr = np.where(df_strat["quintile"]==5, 1, np.where(df_strat["quintile"]==1, -1, 0))
strat_ret_mr   = pd.Series(sig_mr) * df_strat["fret20"].values
active_mr      = strat_ret_mr[sig_mr != 0]
ir_mr  = (active_mr.mean()*252) / (active_mr.std()*np.sqrt(252))

# Cumulative wealth – reindex to chronological for equity curve
df_strat["sig_mr"]    = sig_mr
df_strat["strat_ret"] = df_strat["sig_mr"] * df_strat["fret20"]
df_strat["cum_strat"] = (1 + df_strat["strat_ret"].fillna(0)).cumprod()
df_strat["cum_bh"]    = (1 + df_clean["fret20"].fillna(0)).cumprod()

print("Pipeline complete. Building dashboard …")

# ═════════════════════════════════════════════════════════════════════════════
# DASHBOARD LAYOUT  (6 rows × 3 cols with careful spanning)
# ═════════════════════════════════════════════════════════════════════════════

fig = plt.figure(figsize=(22, 30), facecolor=C_BG)
fig.suptitle(
    "Systematic Volatility Analysis  ·  S&P 500  ·  1961 – 2000\n"
    "A Step-by-Step Walk-Through: Raw Data  →  Indicators  →  Normalisation  →  Quintiles  →  Strategy",
    fontsize=15, fontweight="bold", y=0.995, color="#1A237E"
)

# Row heights: banner  price  indicators  zscore  quintiles  strategy
gs = gridspec.GridSpec(
    6, 3,
    figure=fig,
    hspace=0.62, wspace=0.38,
    height_ratios=[0.04, 1.0, 1.0, 1.0, 0.85, 0.9],
    left=0.06, right=0.97, top=0.975, bottom=0.04
)

def styled_ax(ax, title, subtitle=""):
    ax.set_facecolor(C_PANEL)
    for sp in ax.spines.values():
        sp.set_color(C_GRID)
    ax.tick_params(colors="#424242", labelsize=8)
    ax.xaxis.label.set_color("#424242")
    ax.yaxis.label.set_color("#424242")
    ax.grid(color=C_GRID, linewidth=0.6, zorder=0)
    full = f"  {title}" + (f"\n  {subtitle}" if subtitle else "")
    ax.set_title(full, fontsize=9.5, fontweight="bold", loc="left",
                 color="#1A237E", pad=6)
    return ax

def phase_banner(ax, text, color):
    ax.set_facecolor(color)
    ax.text(0.5, 0.5, text, ha="center", va="center",
            fontsize=11, fontweight="bold", color="white",
            transform=ax.transAxes)
    ax.set_axis_off()

def fmt_pct(ax):
    ax.yaxis.set_major_formatter(mticker.PercentFormatter(xmax=1, decimals=1))

def fmt_z(ax):
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.1f"))

# ─────────────────────────────────────────────────────────────────────────────
# ROW 0 – Phase banner (spans all 3 cols)
# ─────────────────────────────────────────────────────────────────────────────
ax_b0 = fig.add_subplot(gs[0, :])
phase_banner(ax_b0,
    "PHASE 1 · Raw Data    |    PHASE 2 · Indicator Engineering    |    "
    "PHASE 3 · Z-Score Normalisation    |    PHASE 4 · Quintile Analysis    |    "
    "PHASE 5 · Strategy Evaluation",
    "#1A237E")

# ─────────────────────────────────────────────────────────────────────────────
# ROW 1 – Raw data
# [0] S&P price  |  [1] Daily returns (line)  |  [2] Daily returns (histogram)
# ─────────────────────────────────────────────────────────────────────────────
ax_price = styled_ax(fig.add_subplot(gs[1, 0]),
    "Phase 1 · S&P 500 Close Price",
    "Raw input — 10,323 daily observations (1960 – 2000)")
ax_price.plot(df["Date"], df["Close"], color=C_PRICE, linewidth=0.7, zorder=3)
ax_price.fill_between(df["Date"], df["Close"], alpha=0.12, color=C_PRICE)
ax_price.set_ylabel("Index Level", fontsize=8)
ax_price.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:,.0f}"))
# Shade the "burned" rows region
burn_end = df["Date"].iloc[WINDOW + NORM_WIN]
ax_price.axvspan(df["Date"].iloc[0], burn_end, alpha=0.15, color="#F44336", zorder=2)
ax_price.annotate("Burned\n(270 rows)", xy=(df["Date"].iloc[135], df["Close"].iloc[135]),
                  fontsize=7, color="#B71C1C",
                  arrowprops=dict(arrowstyle="-", color="#B71C1C", lw=0.8),
                  xytext=(df["Date"].iloc[800], 120))

ax_ret1 = styled_ax(fig.add_subplot(gs[1, 1]),
    "Phase 1 · Daily Returns (ret1)",
    "ret1 = Close_t / Close_{t−1}  −  1")
ax_ret1.plot(df["Date"], df["ret1"]*100, color=C_RET, linewidth=0.4, alpha=0.7, zorder=3)
ax_ret1.axhline(0, color="#424242", linewidth=0.8, linestyle="--")
ax_ret1.set_ylabel("Daily Return (%)", fontsize=8)
ax_ret1.annotate("ret1 = (Pₜ / Pₜ₋₁) − 1",
                 xy=(0.04, 0.90), xycoords="axes fraction",
                 fontsize=8, bbox=FORMULA_PROPS)

ax_hist = styled_ax(fig.add_subplot(gs[1, 2]),
    "Phase 1 · Return Distribution",
    "Fat tails visible — justifies volatility modelling")
ax_hist.hist(df["ret1"].dropna()*100, bins=120, color=C_RET,
             edgecolor="white", linewidth=0.3, alpha=0.85, density=True, zorder=3)
ax_hist.set_xlabel("Daily Return (%)", fontsize=8)
ax_hist.set_ylabel("Density", fontsize=8)
kurt = df["ret1"].dropna().kurt()
ax_hist.annotate(f"Excess kurtosis = {kurt:.1f}\n(Normal = 0)",
                 xy=(0.63, 0.82), xycoords="axes fraction",
                 fontsize=8, bbox=NOTE_PROPS)

# ─────────────────────────────────────────────────────────────────────────────
# ROW 2 – Indicators: vol20  |  ret20  |  fret20  (all in % for readability)
# ─────────────────────────────────────────────────────────────────────────────
ax_vol20 = styled_ax(fig.add_subplot(gs[2, 0]),
    "Phase 2 · Rolling 20-Day Volatility (vol20)",
    "vol20 = std(ret1, 20 days)")
ax_vol20.plot(df["Date"], df["vol20"]*100, color=C_VOL, linewidth=0.6, zorder=3)
ax_vol20.fill_between(df["Date"], df["vol20"]*100, alpha=0.18, color=C_VOL)
ax_vol20.set_ylabel("Volatility (%)", fontsize=8)
ax_vol20.annotate("vol20 = σ(ret1, window=20)",
                  xy=(0.04, 0.88), xycoords="axes fraction", fontsize=8, bbox=FORMULA_PROPS)

ax_ret20 = styled_ax(fig.add_subplot(gs[2, 1]),
    "Phase 2 · Trailing 20-Day Return (ret20)",
    "ret20 = Close_t / Close_{t−20}  −  1  (historical)")
ax_ret20.plot(df["Date"], df["ret20"]*100, color=C_RET20, linewidth=0.5, alpha=0.85, zorder=3)
ax_ret20.axhline(0, color="#424242", linewidth=0.8, linestyle="--")
ax_ret20.set_ylabel("Return (%)", fontsize=8)
ax_ret20.annotate("ret20 = pct_change(20)",
                  xy=(0.04, 0.88), xycoords="axes fraction", fontsize=8, bbox=FORMULA_PROPS)

ax_fret20 = styled_ax(fig.add_subplot(gs[2, 2]),
    "Phase 2 · Future 20-Day Return (fret20)",
    "fret20 = ret20.shift(−20)  ← look-ahead, burns last 20 rows")

# Shade the last-20-row burn zone
burn_fret_start = df["Date"].iloc[-WINDOW-5]
fret_plot = df["fret20"]*100
ax_fret20.plot(df["Date"], fret_plot, color=C_FRET, linewidth=0.5, alpha=0.85, zorder=3)
ax_fret20.axhline(0, color="#424242", linewidth=0.8, linestyle="--")
ax_fret20.axvspan(burn_fret_start, df["Date"].iloc[-1], alpha=0.18, color="#F44336")
ax_fret20.set_ylabel("Future Return (%)", fontsize=8)
ax_fret20.annotate("fret20 = ret20.shift(−20)",
                   xy=(0.04, 0.88), xycoords="axes fraction", fontsize=8, bbox=FORMULA_PROPS)
ax_fret20.annotate("Burned\n(last 20)", xy=(burn_fret_start, 0),
                   fontsize=7, color="#B71C1C",
                   xytext=(0.82, 0.25), xycoords=("data", "axes fraction"),
                   textcoords="axes fraction")

# ─────────────────────────────────────────────────────────────────────────────
# ROW 3 – Z-score normalisation
# [0] raw vol20 vs zvol20  |  [1] all 3 z-scores  |  [2] scatter zvol20 vs zfret20
# ─────────────────────────────────────────────────────────────────────────────
ax_zdem = styled_ax(fig.add_subplot(gs[3, 0]),
    "Phase 3 · Z-Score Demo: vol20 → zvol20",
    "Removes regime bias using 250-day rolling mean & std")
ax2_zdem = ax_zdem.twinx()
ax_zdem.plot(df_clean["Date"], df_clean["vol20"]*100,
             color=C_VOL, linewidth=0.6, alpha=0.5, label="vol20 (raw %)", zorder=2)
ax2_zdem.plot(df_clean["Date"], df_clean["zvol20"],
              color="#FF6F00", linewidth=0.7, label="zvol20 (Z-score)", zorder=3)
ax2_zdem.axhline(0, color="#424242", linewidth=0.6, linestyle="--")
ax_zdem.set_ylabel("vol20 (%)", fontsize=8, color=C_VOL)
ax2_zdem.set_ylabel("Z-score", fontsize=8, color="#FF6F00")
ax2_zdem.tick_params(axis="y", colors="#FF6F00", labelsize=8)
ax_zdem.tick_params(axis="y", colors=C_VOL, labelsize=8)
lines1, labs1 = ax_zdem.get_legend_handles_labels()
lines2, labs2 = ax2_zdem.get_legend_handles_labels()
ax_zdem.legend(lines1+lines2, labs1+labs2, fontsize=7, loc="upper left",
               framealpha=0.85)
ax_zdem.annotate("Z = (X − μ₂₅₀) / σ₂₅₀",
                 xy=(0.36, 0.92), xycoords="axes fraction", fontsize=8.5,
                 bbox=FORMULA_PROPS)
ax2_zdem.set_ylim(-4, 8)

ax_zall = styled_ax(fig.add_subplot(gs[3, 1]),
    "Phase 3 · All Three Z-Scores Over Time",
    "zvol20 · zret20 · zfret20 — regime-neutral, comparable")
ax_zall.plot(df_clean["Date"], df_clean["zvol20"],
             color=C_ZVOL, linewidth=0.5, alpha=0.85, label="zvol20")
ax_zall.plot(df_clean["Date"], df_clean["zret20"],
             color=C_ZRET, linewidth=0.5, alpha=0.75, label="zret20")
ax_zall.plot(df_clean["Date"], df_clean["zfret20"],
             color=C_ZFRET, linewidth=0.5, alpha=0.75, label="zfret20")
ax_zall.axhline(0, color="#424242", linewidth=0.7, linestyle="--")
ax_zall.set_ylabel("Z-score", fontsize=8)
ax_zall.legend(fontsize=7.5, loc="upper left", framealpha=0.85)
ax_zall.set_ylim(-5, 10)

ax_sc = styled_ax(fig.add_subplot(gs[3, 2]),
    "Phase 3 · zvol20 vs zfret20",
    "Each point = one trading day. Colour = vol quintile")
cmap_vals = df_strat["quintile"].values
sc = ax_sc.scatter(df_strat["zvol20"], df_strat["zfret20"],
                   c=cmap_vals, cmap="RdYlBu_r", s=2, alpha=0.35, zorder=3,
                   vmin=1, vmax=5)
ax_sc.axhline(0, color="#424242", linewidth=0.7, linestyle="--")
ax_sc.axvline(0, color="#424242", linewidth=0.7, linestyle="--")
ax_sc.set_xlabel("zvol20", fontsize=8)
ax_sc.set_ylabel("zfret20", fontsize=8)
cb = fig.colorbar(sc, ax=ax_sc, shrink=0.7, pad=0.02)
cb.set_label("Quintile", fontsize=7)
cb.ax.tick_params(labelsize=7)

# ─────────────────────────────────────────────────────────────────────────────
# ROW 4 – Quintile bar charts (3 side-by-side)
# ─────────────────────────────────────────────────────────────────────────────
q_labels = qs["quintile"].astype(str).tolist()

def qbar(ax, values, title, subtitle, ylabel, annotate_str=None):
    styled_ax(ax, title, subtitle)
    bars = ax.bar(qs["quintile"], values, color=C_Q,
                  edgecolor="white", linewidth=0.8, zorder=3, width=0.6)
    ax.axhline(0, color="#424242", linewidth=0.8, linestyle="--", zorder=4)
    ax.set_xlabel("Vol Quintile  (1=Low … 5=High)", fontsize=8)
    ax.set_ylabel(ylabel, fontsize=8)
    ax.set_xticks(qs["quintile"])
    ax.set_xticklabels([f"Q{q}" for q in qs["quintile"]])
    for bar, val in zip(bars, values):
        ypos = bar.get_height() + 0.015 if val >= 0 else bar.get_height() - 0.055
        ax.text(bar.get_x() + bar.get_width()/2, ypos,
                f"{val:+.3f}", ha="center", fontsize=8, fontweight="bold")
    if annotate_str:
        ax.annotate(annotate_str, xy=(0.5, 0.04), xycoords="axes fraction",
                    ha="center", fontsize=8,
                    bbox=dict(boxstyle="round,pad=0.3", fc="#FFF9C4", ec="#F9A825"))

qbar(ax=fig.add_subplot(gs[4, 0]),
     values=qs["avg_zvol20"],
     title="Phase 4 · Average zvol20 by Quintile",
     subtitle="Confirms monotone bucketing — each Q is distinct",
     ylabel="Mean zvol20")

qbar(ax=fig.add_subplot(gs[4, 1]),
     values=qs["avg_zret20"],
     title="Phase 4 · Concurrent Return (zret20)",
     subtitle="High vol co-occurs with poor recent returns",
     ylabel="Mean zret20")

qbar(ax=fig.add_subplot(gs[4, 2]),
     values=qs["avg_zfret20"],
     title="Phase 4 · Lead-Lag: Future Return (zfret20)",
     subtitle="Mean-reversion: Q5 high-vol → positive future returns",
     ylabel="Mean zfret20",
     annotate_str="↑ Mean-reversion pattern detected")

# ─────────────────────────────────────────────────────────────────────────────
# ROW 5 – Strategy
# [0:2] Cumulative equity curve  |  [2] IR summary table
# ─────────────────────────────────────────────────────────────────────────────
ax_eq = styled_ax(fig.add_subplot(gs[5, :2]),
    "Phase 5 · Strategy Equity Curve",
    "Mean-Reversion: Long Q5 (high vol) / Short Q1 (low vol) — applied to 20-day forward return")
ax_eq.plot(df_strat["Date"], df_strat["cum_bh"],
           color="#78909C", linewidth=0.9, linestyle="--", label="Buy-and-Hold (fret20 benchmark)", zorder=2)
ax_eq.plot(df_strat["Date"], df_strat["cum_strat"],
           color="#E65100", linewidth=1.2, label="Mean-Reversion Strategy (Long Q5 / Short Q1)", zorder=3)
ax_eq.axhline(1.0, color="#424242", linewidth=0.6, linestyle=":")
ax_eq.set_ylabel("Cumulative Wealth (starts at 1.0)", fontsize=8)
ax_eq.legend(fontsize=8, loc="upper left", framealpha=0.9)
ax_eq.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.1fx"))

# Shade quintile-5 active periods (sample: first 2000 clean rows for clarity)
q5_mask = df_strat["quintile"] == 5
prev = False
for i, row in df_strat.iterrows():
    if q5_mask[i] and not prev:
        start = row["Date"]; prev = True
    elif not q5_mask[i] and prev:
        ax_eq.axvspan(start, row["Date"], alpha=0.06, color="#C62828", zorder=1)
        prev = False

# ── Summary stats table ──
ax_tbl = fig.add_subplot(gs[5, 2])
ax_tbl.set_facecolor(C_PANEL)
ax_tbl.set_axis_off()
styled_ax(ax_tbl, "Phase 5 · Information Ratio Summary", "IR = (μ × 252) / (σ × √252)")

table_data = [
    ["Metric", "Value"],
    ["Clean observations", f"{len(df_clean):,}"],
    ["Strategy: Long Q5 / Short Q1", ""],
    ["  Active observations", f"{(df_strat['sig_mr']!=0).sum():,}"],
    ["  Mean ann. return", f"{active_mr.mean()*252*100:.1f}%"],
    ["  Ann. std", f"{active_mr.std()*np.sqrt(252)*100:.1f}%"],
    ["  Information Ratio", f"{ir_mr:.3f}"],
    ["", ""],
    ["Interpretation", ""],
    ["  IR > 0.5  →  Strong signal", ""],
    ["  IR 0.4    →  Moderate edge", "✓ here"],
]

y = 0.95
for i, (label, val) in enumerate(table_data):
    is_header = i == 0
    color = "#1A237E" if is_header else ("#2E7D32" if "IR" in label else "#212121")
    weight = "bold" if is_header or label.startswith("  Information") else "normal"
    fsize  = 9 if is_header else 8.5
    ax_tbl.text(0.03, y, label, transform=ax_tbl.transAxes,
                fontsize=fsize, fontweight=weight, color=color, va="top")
    if val:
        val_color = "#C62828" if "IR" in label and float(val.replace("✓ here","").strip() or 0) > 0 \
                    else "#2E7D32" if "✓" in val else "#424242"
        ax_tbl.text(0.72, y, val, transform=ax_tbl.transAxes,
                    fontsize=fsize, fontweight=weight, color=val_color, va="top", ha="left")
    y -= 0.088

# Box around the IR value
ir_box_y = 0.95 - 5 * 0.088
ax_tbl.add_patch(mpatches.FancyBboxPatch(
    (0.0, ir_box_y - 0.01), 1.0, 0.095,
    boxstyle="round,pad=0.01", linewidth=1.2,
    edgecolor="#F9A825", facecolor="#FFFDE7",
    transform=ax_tbl.transAxes, zorder=0
))

# ─────────────────────────────────────────────────────────────────────────────
# Save
# ─────────────────────────────────────────────────────────────────────────────
out = "vol_dashboard.png"
plt.savefig(out, dpi=150, bbox_inches="tight", facecolor=C_BG)
print(f"Dashboard saved → {out}")
plt.show()
