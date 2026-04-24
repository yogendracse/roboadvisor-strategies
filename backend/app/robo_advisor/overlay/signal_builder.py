"""
signal_builder.py
-----------------
Converts raw Polymarket token price histories into named signals with a
uniform output schema.

Two signal types (matching polymarket_markets.yaml):

  binary
      Signal value = YES token probability directly.
      Example: recession_prob = P(recession by end of 2026)

  multi_outcome_expected_value
      E[X] = sum(midpoint_i * P_yes_i) / sum(P_yes_i)
      The denominator normalises for market probabilities that don't sum to 1
      (rounding, stale quotes, illiquid buckets).
      Example: fed_cuts_expected = probability-weighted number of 2026 cuts

Output schema (all signals):
    date         datetime.date
    signal_name  str
    value        float           (probability for binary; level for EV)
    source       str             always "polymarket"
    confidence   float           always 1.0
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).parents[4] / "config" / "polymarket_markets.yaml"
_OUTPUT_COLS = ["date", "signal_name", "value", "source", "confidence"]


# ── Public API ─────────────────────────────────────────────────────────────────

def build_signals(
    token_histories: dict[str, pd.DataFrame],
    config_path: Path = _CONFIG_PATH,
) -> pd.DataFrame:
    """Build all configured signals from raw token histories.

    Parameters
    ----------
    token_histories:
        Mapping of yes_token_id → DataFrame[date, probability].
        Tokens absent from this dict or with empty histories produce NaN rows.
    config_path:
        Path to polymarket_markets.yaml.

    Returns
    -------
    pd.DataFrame with columns: date, signal_name, value, source, confidence.
    Missing data for a date = NaN value (not dropped), so callers can detect gaps.
    """
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


# ── Binary ─────────────────────────────────────────────────────────────────────

def _build_binary(
    signal_name: str,
    spec: dict[str, Any],
    token_histories: dict[str, pd.DataFrame],
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


# ── Multi-outcome expected value ───────────────────────────────────────────────

def _build_ev(
    signal_name: str,
    spec: dict[str, Any],
    token_histories: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    """E[X] = sum(midpoint_i * P_yes_i) / sum(P_yes_i)"""
    outcomes = spec["outcomes"]
    value_key = "cuts" if "cuts" in outcomes[0] else "midpoint"

    # Align all outcome series to a common date index
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

    # Outer-join on date so we keep the full date union
    aligned = pd.concat(series_list, axis=1)
    weights_arr = np.array(weights)

    # Row-wise: E[X] = sum(w_i * p_i) / sum(p_i), ignoring NaN columns per row
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


# ── Helpers ────────────────────────────────────────────────────────────────────

def _load_config(path: Path) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)
