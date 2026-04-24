from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from app.robo_advisor.data.loaders.fred_loader import MacroLoader
from app.robo_advisor.data.loaders.harmonizer import SignalHarmonizer

logger = logging.getLogger(__name__)

_POLYMARKET_CONFIG_PATH = Path(__file__).parents[3] / "config" / "polymarket_markets.yaml"
_OVERLAY_CONFIG_PATH = Path(__file__).parents[3] / "config" / "overlay.yaml"
_DATA_DIR = Path(__file__).parents[3] / "data" / "robo_advisor"
_SIGNALS_PARQUET = _DATA_DIR / "signals.parquet"
_SIGNALS_CSV = _DATA_DIR / "signals.csv"
_OUTPUT_COLS = ["date", "signal_name", "value", "source", "confidence"]


def build_signals(
    arg: Mapping[str, pd.DataFrame] | str | date | pd.Timestamp | None = None,
    config_path: Path | None = None,
) -> pd.DataFrame | dict[str, dict[str, float | str]]:
    """Dual-purpose signal builder.

    - `build_signals(token_histories, config_path=...)` preserves the M1 backfill path
      and returns a DataFrame of harmonized Polymarket signal history.
    - `build_signals(as_of_date)` returns the M6 overlay signal snapshot for one date.
    """
    if isinstance(arg, Mapping):
        return build_signal_history(arg, config_path=config_path or _POLYMARKET_CONFIG_PATH)
    return build_signal_snapshot(as_of_date=arg, config_path=config_path or _OVERLAY_CONFIG_PATH)


def build_signal_snapshot(
    as_of_date: str | date | pd.Timestamp | None = None,
    config_path: Path = _OVERLAY_CONFIG_PATH,
) -> dict[str, dict[str, float | str]]:
    as_of = _coerce_date(as_of_date)
    overlay_cfg = _load_config(config_path)
    history = _load_signal_history(as_of)
    if history.empty:
        return {}

    snapshots: dict[str, dict[str, float | str]] = {}
    for signal_name, spec in overlay_cfg.get("signals", {}).items():
        signal_df = (
            history[history["signal_name"] == signal_name]
            .sort_values("date")
            .reset_index(drop=True)
        )
        if signal_df.empty:
            continue

        window_days = int(spec.get("baseline_window_days", 90))
        trailing = signal_df[signal_df["date"] >= as_of - timedelta(days=window_days)]
        if trailing.empty:
            trailing = signal_df.tail(window_days)

        current_row = signal_df.iloc[-1]
        current = float(current_row["value"])
        baseline = float(trailing["value"].median())
        mean = float(trailing["value"].mean())
        std = float(trailing["value"].std(ddof=0))
        deviation = current - baseline
        z_score = 0.0 if std <= 1e-12 or np.isnan(std) else float((current - mean) / std)

        snapshots[signal_name] = {
            "value": current,
            "baseline": baseline,
            "deviation": deviation,
            "z": z_score,
            "rolling_mean": mean,
            "rolling_std": std,
            "source": str(current_row.get("source", "unknown")),
            "confidence": float(current_row.get("confidence", 1.0)),
            "as_of_date": as_of.isoformat(),
        }

    return snapshots


def build_portfolio_state(
    as_of_date: str | date | pd.Timestamp | None = None,
    config_path: Path = _OVERLAY_CONFIG_PATH,
) -> dict[str, Any]:
    as_of = _coerce_date(as_of_date)
    signals = build_signal_snapshot(as_of, config_path=config_path)
    history = _load_signal_history(as_of)

    recession_history = (
        history[history["signal_name"] == "recession_prob"][["date", "value"]]
        .sort_values("date")
        .reset_index(drop=True)
    )

    macro = MacroLoader()
    vix_zscore = 0.0
    if macro.path.exists():
        try:
            vix = macro.load("VIXCLS")[["date", "value"]].copy()
            vix = vix[vix["date"] <= as_of].sort_values("date")
            trailing = vix[vix["date"] >= as_of - timedelta(days=90)]
            if trailing.empty:
                trailing = vix.tail(90)
            if not trailing.empty:
                current = float(trailing["value"].iloc[-1])
                mean = float(trailing["value"].mean())
                std = float(trailing["value"].std(ddof=0))
                vix_zscore = 0.0 if std <= 1e-12 or np.isnan(std) else float((current - mean) / std)
        except Exception as exc:
            logger.debug("Unable to compute VIX z-score: %s", exc)

    uses_proxy = any(str(sig.get("source")) != "polymarket" for sig in signals.values())
    warnings: list[str] = []
    if uses_proxy:
        warnings.append(
            "One or more overlay signals are using FRED proxies (confidence 0.70) "
            "because Polymarket history is unavailable before September 2025."
        )

    return {
        "as_of_date": as_of.isoformat(),
        "signals": signals,
        "signal_history": history,
        "recession_history": recession_history,
        "vix_zscore": vix_zscore,
        "warnings": warnings,
    }


def build_signal_history(
    token_histories: Mapping[str, pd.DataFrame],
    config_path: Path = _POLYMARKET_CONFIG_PATH,
) -> pd.DataFrame:
    config = _load_config(config_path)
    frames: list[pd.DataFrame] = []

    for signal_name, spec in config["signals"].items():
        sig_type = spec["type"]
        logger.info("Building signal '%s' (type=%s)", signal_name, sig_type)

        if sig_type == "binary":
            df = _build_binary(signal_name, spec, token_histories)
        elif sig_type == "multi_outcome_expected_value":
            df = _build_ev(signal_name, spec, token_histories)
        else:
            logger.warning("Unknown signal type '%s' for '%s', skipping", sig_type, signal_name)
            continue

        frames.append(df)

    if not frames:
        return pd.DataFrame(columns=_OUTPUT_COLS)

    combined = (
        pd.concat(frames, ignore_index=True)
        .sort_values(["signal_name", "date"])
        .reset_index(drop=True)
    )
    combined["date"] = pd.to_datetime(combined["date"]).dt.date
    return combined[_OUTPUT_COLS]


def _build_binary(
    signal_name: str,
    spec: dict[str, Any],
    token_histories: Mapping[str, pd.DataFrame],
) -> pd.DataFrame:
    token_id = spec["yes_token_id"]
    hist = token_histories.get(token_id, pd.DataFrame(columns=["date", "probability"]))

    if hist.empty:
        logger.warning("  '%s': no history for token %s…", signal_name, token_id[:12])
        return pd.DataFrame(columns=_OUTPUT_COLS)

    df = hist[["date", "probability"]].copy()
    df = df.rename(columns={"probability": "value"})
    df["signal_name"] = signal_name
    df["source"] = "polymarket"
    df["confidence"] = 1.0
    return df[_OUTPUT_COLS]


def _build_ev(
    signal_name: str,
    spec: dict[str, Any],
    token_histories: Mapping[str, pd.DataFrame],
) -> pd.DataFrame:
    outcomes = spec["outcomes"]
    value_key = "cuts" if "cuts" in outcomes[0] else "midpoint"

    series_list: list[pd.Series] = []
    weights: list[float] = []
    empty_tokens: list[str] = []

    for outcome in outcomes:
        token_id = outcome["yes_token_id"]
        weight = float(outcome[value_key])
        hist = token_histories.get(token_id, pd.DataFrame(columns=["date", "probability"]))

        if hist.empty:
            empty_tokens.append(token_id)
            logger.warning(
                "  '%s': empty history for token %s… (weight=%s)",
                signal_name, token_id[:12], weight,
            )
            continue

        s = hist.set_index("date")["probability"].rename(token_id)
        series_list.append(s)
        weights.append(weight)

    if empty_tokens:
        logger.warning(
            "  '%s': %d / %d tokens had no data",
            signal_name, len(empty_tokens), len(outcomes),
        )

    if not series_list:
        logger.error("  '%s': all tokens empty, cannot compute EV", signal_name)
        return pd.DataFrame(columns=_OUTPUT_COLS)

    aligned = pd.concat(series_list, axis=1)
    weights_arr = np.array(weights)

    def _ev_row(row: pd.Series) -> float:
        valid = ~row.isna()
        if not valid.any():
            return float("nan")
        p = row[valid].values
        w = weights_arr[valid.values]
        denom = p.sum()
        return float((w * p).sum() / denom) if denom > 0 else float("nan")

    ev = aligned.apply(_ev_row, axis=1)

    df = ev.reset_index()
    df.columns = ["date", "value"]
    df["signal_name"] = signal_name
    df["source"] = "polymarket"
    df["confidence"] = 1.0
    return df[_OUTPUT_COLS]


@lru_cache(maxsize=4)
def _load_config(path: Path) -> dict[str, Any]:
    with open(path) as f:
        return yaml.safe_load(f)


@lru_cache(maxsize=32)
def _load_signal_history(as_of_date: date) -> pd.DataFrame:
    harmonizer = SignalHarmonizer()
    df = harmonizer.as_dataframe(end=as_of_date)
    if df.empty:
        return pd.DataFrame(columns=_OUTPUT_COLS)
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df = df.sort_values(["signal_name", "date"]).dropna(subset=["value"])
    return df.reset_index(drop=True)


def _coerce_date(value: str | date | pd.Timestamp | None) -> date:
    if value is None:
        if _SIGNALS_PARQUET.exists():
            df = pd.read_parquet(_SIGNALS_PARQUET, columns=["date"])
            return pd.to_datetime(df["date"]).dt.date.max()
        if _SIGNALS_CSV.exists():
            df = pd.read_csv(_SIGNALS_CSV, parse_dates=["date"])
            return df["date"].dt.date.max()
        return pd.Timestamp.today().date()
    return pd.Timestamp(value).date()
