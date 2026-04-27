"""OLS sensitivity regression: estimate empirical β for each signal × asset pair."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
import scipy.stats.mstats as mstats
import yaml

_BACKEND_ROOT = Path(__file__).parents[1]
_DATA_DIR = _BACKEND_ROOT / "data" / "robo_advisor"
_CONFIG_DIR = _BACKEND_ROOT / "config"
_REPORTS_DIR = _BACKEND_ROOT / "reports" / "regression"

ASSETS = ["SPY", "QQQ", "TLT", "IEF", "GLD", "DBC", "VNQ", "VXUS"]
SIGNALS = ["recession_prob", "fed_cuts_expected", "sp500_close_expected"]

_FRED_WINDOW_START = "2015-01-01"
_FRED_WINDOW_END = "2025-08-31"
_PM_WINDOW_START = "2025-09-01"

LOW_N_THRESHOLD = 60
LOW_N_WARNING = "Insufficient data — treat with caution"


@dataclass
class RegressionResult:
    asset: str
    signal: str
    excess_return_beta: float | None
    alpha: float | None
    r_squared: float | None
    p_value_hc3: float | None
    conf_interval_low: float | None
    conf_interval_high: float | None
    n_observations: int
    data_source: str
    period: str
    warning: str | None = None

    @property
    def significant(self) -> bool:
        return self.p_value_hc3 is not None and self.p_value_hc3 < 0.05

    def to_dict(self) -> dict[str, Any]:
        return {
            "excess_return_beta": self.excess_return_beta,
            "alpha": self.alpha,
            "r_squared": self.r_squared,
            "p_value_hc3": self.p_value_hc3,
            "conf_interval": [self.conf_interval_low, self.conf_interval_high],
            "n_observations": self.n_observations,
            "significant": self.significant,
            "data_source": self.data_source,
            "period": self.period,
            "warning": self.warning,
        }


class SensitivityRegressor:
    def __init__(self, overlay_cfg: dict | None = None) -> None:
        self._overlay_cfg = overlay_cfg or {}

    def configured_sensitivity(self, signal: str, asset: str) -> float | None:
        return (
            self._overlay_cfg.get("signals", {})
            .get(signal, {})
            .get("sensitivities", {})
            .get(asset)
        )

    # ── Data helpers ──────────────────────────────────────────────────────────

    def _load_prices_wide(self) -> pd.DataFrame:
        prices = pd.read_csv(_DATA_DIR / "prices.csv", parse_dates=["date"])
        pivot = prices.pivot_table(index="date", columns="ticker", values="adj_close")
        available = [a for a in ASSETS if a in pivot.columns]
        return pivot[available]

    def _prepare_polymarket(
        self, signal_name: str, start: str, end: str
    ) -> pd.DataFrame:
        """Daily Δsignal + daily ETF returns aligned on date."""
        signals = pd.read_csv(_DATA_DIR / "signals.csv", parse_dates=["date"])
        sig = (
            signals[
                (signals["signal_name"] == signal_name)
                & (signals["source"] == "polymarket")
            ]
            .set_index("date")["value"]
            .sort_index()
        )
        mask = (sig.index >= pd.Timestamp(start))
        if end:
            mask &= sig.index <= pd.Timestamp(end)
        sig = sig[mask]
        if sig.empty:
            return pd.DataFrame()

        delta = sig.diff().dropna()
        delta.name = "delta_signal"

        prices_wide = self._load_prices_wide()
        returns = prices_wide.pct_change().dropna(how="all")
        returns.columns = [f"{c}_ret" for c in returns.columns]

        df = delta.to_frame().join(returns, how="inner").dropna()
        df.index.name = "date"
        return df

    def _prepare_fred(self, signal_name: str, start: str, end: str) -> pd.DataFrame:
        """Monthly Δsignal + monthly ETF returns aligned on month-end."""
        macro = pd.read_csv(_DATA_DIR / "macro.csv", parse_dates=["date"])

        if signal_name == "recession_prob":
            series = macro[macro["series_id"] == "RECPROUSM156N"].set_index("date")["value"]
            series = series / 100.0
        elif signal_name == "fed_cuts_expected":
            # FEDFUNDS monthly change as proxy for fed policy expectations
            # A cut = FEDFUNDS drops ~0.25pp; each -0.25pp ≈ +1 expected cut
            series = macro[macro["series_id"] == "FEDFUNDS"].set_index("date")["value"]
        elif signal_name == "sp500_close_expected":
            return pd.DataFrame()  # No reliable FRED proxy for SPX level
        else:
            return pd.DataFrame()

        series = series.sort_index()
        series = series.resample("ME").last()
        mask = (series.index >= pd.Timestamp(start))
        if end:
            mask &= series.index <= pd.Timestamp(end)
        series = series[mask]
        if series.empty:
            return pd.DataFrame()

        delta = series.diff().dropna()
        delta.name = "delta_signal"

        prices_wide = self._load_prices_wide()
        monthly_prices = prices_wide.resample("ME").last()
        returns = monthly_prices.pct_change().dropna(how="all")
        returns.columns = [f"{c}_ret" for c in returns.columns]
        ret_mask = (returns.index >= pd.Timestamp(start))
        if end:
            ret_mask &= returns.index <= pd.Timestamp(end)
        returns = returns[ret_mask]

        df = delta.to_frame().join(returns, how="inner").dropna()
        df.index.name = "date"
        return df

    def prepare_data(
        self,
        signal_name: str,
        lookback_start: str,
        lookback_end: str,
        window: str = "fred_proxy",
    ) -> pd.DataFrame:
        if window == "polymarket":
            return self._prepare_polymarket(signal_name, lookback_start, lookback_end)
        return self._prepare_fred(signal_name, lookback_start, lookback_end)

    # ── OLS regression ────────────────────────────────────────────────────────

    def run_regression(
        self,
        signal_name: str,
        asset: str,
        data: pd.DataFrame,
        data_source: str,
        period: str,
    ) -> RegressionResult:
        col = f"{asset}_ret"
        base = RegressionResult(
            asset=asset,
            signal=signal_name,
            excess_return_beta=None,
            alpha=None,
            r_squared=None,
            p_value_hc3=None,
            conf_interval_low=None,
            conf_interval_high=None,
            n_observations=0,
            data_source=data_source,
            period=period,
        )

        if data.empty or col not in data.columns or "delta_signal" not in data.columns:
            return base

        if asset != "SPY" and "SPY_ret" in data.columns:
            cols_to_drop = ["delta_signal", col, "SPY_ret"]
            clean = data[cols_to_drop].dropna()
            y_raw = clean[col].values - clean["SPY_ret"].values
        else:
            cols_to_drop = ["delta_signal", col]
            clean = data[cols_to_drop].dropna()
            y_raw = clean[col].values

        n = len(clean)
        base.n_observations = n

        if n < 10:
            return base

        # Check sample size constraints
        if data_source == "polymarket" and n < 60:
            base.warning = "Insufficient data (N < 60) for Polymarket"
            return base
        elif data_source == "fred_proxy" and n < 252:
            base.warning = "Insufficient data (N < 252) for FRED proxy"
            return base

        x_raw = clean["delta_signal"].values
        if np.std(x_raw) < 1e-10:
            return base

        # Winsorize 1% and 99%
        x = mstats.winsorize(x_raw, limits=[0.01, 0.01]).data
        y = mstats.winsorize(y_raw, limits=[0.01, 0.01]).data

        X = sm.add_constant(x)
        try:
            model = sm.OLS(y, X).fit(cov_type="HC3")
        except Exception:
            return base

        ci = model.conf_int(alpha=0.05)
        base.excess_return_beta = float(model.params[1])
        base.alpha = float(model.params[0])
        base.r_squared = float(model.rsquared)
        base.p_value_hc3 = float(model.pvalues[1])
        base.conf_interval_low = float(ci[1, 0])
        base.conf_interval_high = float(ci[1, 1])
        return base

    # ── Run all 3×8 ──────────────────────────────────────────────────────────

    def run_all(
        self,
        lookback_start: str,
        lookback_end: str,
        window: str = "fred_proxy",
    ) -> dict[str, dict[str, RegressionResult]]:
        if window == "fred_proxy":
            data_source = "fred_proxy"
            period = f"{lookback_start[:4]}–{lookback_end[:4]} (FRED)"
        else:
            data_source = "polymarket"
            period = "Sep 2025–present (Polymarket)"

        results: dict[str, dict[str, RegressionResult]] = {}
        for signal in SIGNALS:
            results[signal] = {}
            data = self.prepare_data(signal, lookback_start, lookback_end, window)
            for asset in ASSETS:
                results[signal][asset] = self.run_regression(
                    signal, asset, data, data_source, period
                )
        return results

    # ── Comparison table ─────────────────────────────────────────────────────

    def compare_to_configured(
        self, results: dict[str, dict[str, RegressionResult]]
    ) -> pd.DataFrame:
        rows = []
        for signal, asset_results in results.items():
            for asset, r in asset_results.items():
                configured = self.configured_sensitivity(signal, asset)
                sign_conflict = False
                if configured is not None and r.excess_return_beta is not None and r.significant:
                    sign_conflict = (configured * r.excess_return_beta < 0)

                # Determine action
                action = "Wait for Data"
                if r.significant:
                    if sign_conflict:
                        action = "Alert (Conflict)"
                    else:
                        action = "Confirm"

                rows.append(
                    {
                        "signal": signal,
                        "asset": asset,
                        "configured_sensitivity": configured,
                        "empirical_beta": r.excess_return_beta,
                        "difference": (
                            (r.excess_return_beta - configured)
                            if configured is not None and r.excess_return_beta is not None
                            else None
                        ),
                        "p_value": r.p_value_hc3,
                        "r_squared": r.r_squared,
                        "significant": r.significant,
                        "sign_conflict": sign_conflict,
                        "n_observations": r.n_observations,
                        "warning": r.warning,
                        "action": action,
                    }
                )
        return pd.DataFrame(rows)

    # ── Report & plots ────────────────────────────────────────────────────────

    def generate_report(
        self,
        fred_results: dict[str, dict[str, RegressionResult]],
        pm_results: dict[str, dict[str, RegressionResult]],
    ) -> str:
        """Write markdown report and PNG plots to _REPORTS_DIR. Returns report text."""
        _REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        plot_dir = _REPORTS_DIR / "regression_plots"
        plot_dir.mkdir(exist_ok=True)

        fred_df = self.compare_to_configured(fred_results)
        pm_df = self.compare_to_configured(pm_results)

        lines: list[str] = []
        lines.append("# Sensitivity Regression Report\n")
        lines.append(f"Generated: {date.today()}\n")

        for label, df, results in [
            ("FRED Proxy — Long History (2015–2025)", fred_df, fred_results),
            ("Polymarket — Live Window (Sep 2025–present)", pm_df, pm_results),
        ]:
            lines.append(f"\n## {label}\n")
            sig_count = df["significant"].sum()
            conflict_count = df["sign_conflict"].sum()
            lines.append(
                f"**Significant (p < 0.05):** {sig_count} / {len(df)}  "
                f"**Sign conflicts:** {conflict_count}\n"
            )

            lines.append("\n| Signal | Asset | Configured | Empirical α Beta | 95% CI | p-value | N | Action |")
            lines.append("|--------|-------|-----------|-----------------|--------|---------|---|--------|")
            for _, row in df.iterrows():
                cfg = f"{row['configured_sensitivity']:.3f}" if row['configured_sensitivity'] is not None else "—"
                beta = f"{row['empirical_beta']:.4f}" if row['empirical_beta'] is not None else "—"
                r = results.get(row["signal"], {}).get(row["asset"])
                if r and r.conf_interval_low is not None:
                    ci = f"[{r.conf_interval_low:.3f}, {r.conf_interval_high:.3f}]"
                else:
                    ci = "—"
                pval = f"{row['p_value']:.4f}" if row['p_value'] is not None else "—"
                action_str = row['action']
                if action_str == "Alert (Conflict)":
                    action_str = "⚠️ " + action_str
                lines.append(
                    f"| {row['signal']} | {row['asset']} | {cfg} | {beta} | {ci} | {pval} | {row['n_observations']} | {action_str} |"
                )

        # Recommendations
        lines.append("\n## Recommendations\n")
        all_conflicts = []
        all_significant_updates = []
        for df, label in [(fred_df, "FRED"), (pm_df, "Polymarket")]:
            for _, row in df.iterrows():
                if row["sign_conflict"]:
                    all_conflicts.append(
                        f"- **{row['signal']} / {row['asset']}** [{label}]: "
                        f"configured={row['configured_sensitivity']:.3f}, "
                        f"empirical β={row['empirical_beta']:.4f} — OPPOSITE SIGN, overlay tilts wrong direction"
                    )
                elif row["significant"] and row["configured_sensitivity"] is not None:
                    all_significant_updates.append(
                        f"- {row['signal']} / {row['asset']} [{label}]: "
                        f"{row['configured_sensitivity']:.3f} → {row['empirical_beta']:.4f}"
                    )

        if all_conflicts:
            lines.append("### ⚠️ Update Immediately — Sign Conflicts\n")
            lines.extend(all_conflicts)
        if all_significant_updates:
            lines.append("\n### Consider Updating — Significant Empirical Betas\n")
            lines.extend(all_significant_updates)

        not_significant = fred_df[~fred_df["significant"]]
        if len(not_significant):
            lines.append("\n### Leave Unchanged — Not Statistically Significant\n")
            for _, row in not_significant.iterrows():
                if row["configured_sensitivity"] is not None:
                    pval_str = f"{row['p_value']:.3f}" if row['p_value'] is not None else "N/A"
                    lines.append(
                        f"- {row['signal']} / {row['asset']}: p={pval_str} — needs more data"
                    )

        report_text = "\n".join(lines)
        (_REPORTS_DIR / "sensitivity_regression_report.md").write_text(report_text)

        # Generate plots
        self._make_plots(fred_results, pm_results, plot_dir)

        return report_text

    def _make_plots(
        self,
        fred_results: dict[str, dict[str, RegressionResult]],
        pm_results: dict[str, dict[str, RegressionResult]],
        plot_dir: Path,
    ) -> None:
        signal_titles = {
            "recession_prob": "Recession Probability Sensitivities",
            "fed_cuts_expected": "Fed Cuts Expected Sensitivities",
            "sp500_close_expected": "S&P 500 Close Expected Sensitivities",
        }
        filenames = {
            "recession_prob": "recession_prob_betas.png",
            "fed_cuts_expected": "fed_cuts_betas.png",
            "sp500_close_expected": "sp500_close_betas.png",
        }

        for signal in SIGNALS:
            fig, axes = plt.subplots(1, 2, figsize=(14, 5), sharey=True)
            fig.suptitle(signal_titles[signal], fontsize=13, fontweight="bold")

            for ax, (results, window_label) in zip(
                axes,
                [
                    (fred_results, "FRED Proxy (2015–2025)"),
                    (pm_results, "Polymarket (Sep 2025+)"),
                ],
            ):
                betas, ci_lows, ci_highs, colors, configured_vals = [], [], [], [], []
                for asset in ASSETS:
                    r = results[signal][asset]
                    b = r.excess_return_beta if r.excess_return_beta is not None else 0.0
                    betas.append(b)
                    ci_lows.append(abs(b - r.conf_interval_low) if r.conf_interval_low is not None else 0)
                    ci_highs.append(abs(r.conf_interval_high - b) if r.conf_interval_high is not None else 0)
                    
                    configured_vals.append(self.configured_sensitivity(signal, asset))

                x = np.arange(len(ASSETS))
                bar_colors = []
                for i, r in enumerate(results[signal].values()):
                    cfg = configured_vals[i]
                    if r.significant and cfg is not None and r.excess_return_beta is not None and cfg * r.excess_return_beta < 0:
                        bar_colors.append("#ef4444")
                    elif r.significant:
                        bar_colors.append("#22c55e")
                    else:
                        bar_colors.append("#a1a1aa")

                ax.bar(x, betas, color=bar_colors, alpha=0.8, zorder=2)
                ax.errorbar(
                    x, betas,
                    yerr=[ci_lows, ci_highs],
                    fmt="none", color="#374151", capsize=4, linewidth=1.2, zorder=3,
                )
                # Configured sensitivity dots
                for i, cfg in enumerate(configured_vals):
                    if cfg is not None:
                        ax.plot(x[i], cfg, "o", color="#7c3aed", markersize=7, zorder=4, label="configured" if i == 0 else "")

                ax.axhline(0, color="#374151", linewidth=0.8, linestyle="--")
                ax.set_xticks(x)
                ax.set_xticklabels(ASSETS, fontsize=9)
                ax.set_title(window_label, fontsize=10)
                ax.set_ylabel("β (sensitivity)")
                ax.grid(axis="y", alpha=0.3)
                if any(c is not None for c in configured_vals):
                    ax.legend(fontsize=8)

            plt.tight_layout()
            plt.savefig(plot_dir / filenames[signal], dpi=120, bbox_inches="tight")
            plt.close(fig)


def run_both_windows(overlay_cfg: dict | None = None) -> tuple[
    dict[str, dict[str, RegressionResult]],
    dict[str, dict[str, RegressionResult]],
]:
    """Convenience: run FRED + Polymarket windows, return (fred_results, pm_results)."""
    reg = SensitivityRegressor(overlay_cfg)
    fred = reg.run_all(_FRED_WINDOW_START, _FRED_WINDOW_END, window="fred_proxy")
    pm = reg.run_all(_PM_WINDOW_START, date.today().isoformat(), window="polymarket")
    return fred, pm


def build_api_response(
    fred_results: dict[str, dict[str, RegressionResult]],
    pm_results: dict[str, dict[str, RegressionResult]],
    reg: SensitivityRegressor,
    window: str = "both",
) -> dict[str, Any]:
    """Serialize results into the API response shape."""

    def _serialize_window(results: dict[str, dict[str, RegressionResult]]) -> dict:
        out: dict = {}
        for signal, asset_map in results.items():
            out[signal] = {}
            for asset, r in asset_map.items():
                cfg = reg.configured_sensitivity(signal, asset)
                sign_conflict = (
                    cfg is not None
                    and r.excess_return_beta is not None
                    and r.significant
                    and (cfg * r.excess_return_beta < 0)
                )
                out[signal][asset] = {
                    **r.to_dict(),
                    "configured_sensitivity": cfg,
                    "sign_conflict": sign_conflict,
                }
        return out

    def _summary(fred: dict, pm: dict) -> dict:
        total = 0
        sig = 0
        conflicts = 0
        for window_data in [fred, pm]:
            for signal_data in window_data.values():
                for asset_data in signal_data.values():
                    total += 1
                    if asset_data.get("significant"):
                        sig += 1
                    if asset_data.get("sign_conflict"):
                        conflicts += 1
        recommend_update = sig
        return {
            "total_regressions": total,
            "significant_count": sig,
            "sign_conflicts": conflicts,
            "recommendation": (
                f"Update {recommend_update} sensitivities. {conflicts} have sign conflicts."
            ),
        }

    fred_ser = _serialize_window(fred_results)
    pm_ser = _serialize_window(pm_results)

    resp: dict[str, Any] = {}
    if window in ("fred_proxy", "both"):
        resp["fred_proxy"] = fred_ser
    if window in ("polymarket", "both"):
        resp["polymarket"] = pm_ser
    resp["summary"] = _summary(fred_ser, pm_ser)
    return resp
