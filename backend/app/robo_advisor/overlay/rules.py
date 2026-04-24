from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

_CONFIG_PATH = Path(__file__).parents[3] / "config" / "overlay.yaml"


def apply_circuit_breakers(
    tilts: dict[str, float],
    portfolio_state: dict[str, Any],
    config_path: Path = _CONFIG_PATH,
) -> dict[str, float]:
    cfg = _load_config(config_path)["circuit_breakers"]
    adjusted = {asset: float(tilt) for asset, tilt in tilts.items()}
    active: list[str] = []

    signals = portfolio_state.get("signals", {})
    recession = signals.get("recession_prob", {})
    recession_value = float(recession.get("value", 0.0))
    recession_baseline = float(recession.get("baseline", 0.0))
    recession_deviation = float(recession.get("deviation", 0.0))
    vix_zscore = float(portfolio_state.get("vix_zscore", 0.0))

    derisk_threshold = recession_baseline + float(cfg["derisk_recession_threshold_pp"])
    derisk_active = (
        recession_deviation > 0
        and recession_value > derisk_threshold
        and vix_zscore > float(cfg["derisk_vix_zscore"])
    )

    if derisk_active:
        active.append("derisk_recession")
    elif recession_deviation > 0:
        adjusted = {asset: 0.0 for asset in adjusted}
        if any(abs(tilt) > 1e-12 for tilt in tilts.values()):
            active.append("awaiting_derisk_confirmation")

    if _is_recession_declining(
        portfolio_state.get("recession_history"),
        weeks=int(cfg["rerisk_weeks_declining"]),
    ):
        adjusted = {asset: tilt * 0.5 for asset, tilt in adjusted.items()}
        active.append("rerisk_recession")

    max_asset_tilt = float(cfg["max_asset_tilt"])
    clipped = {
        asset: max(min(tilt, max_asset_tilt), -max_asset_tilt)
        for asset, tilt in adjusted.items()
    }
    if clipped != adjusted:
        active.append("cap_asset_tilt")
    adjusted = clipped

    budget = float(cfg["max_overlay_budget"])
    total_abs = sum(abs(tilt) for tilt in adjusted.values())
    if total_abs > budget and total_abs > 1e-12:
        scale = budget / total_abs
        adjusted = {asset: tilt * scale for asset, tilt in adjusted.items()}
        active.append("overlay_budget_cap")
        total_abs = budget

    portfolio_state["active_circuit_breakers"] = active
    portfolio_state["overlay_budget_used"] = total_abs
    portfolio_state["overlay_budget_limit"] = budget
    return adjusted


def _is_recession_declining(history: Any, weeks: int) -> bool:
    if history is None:
        return False
    df = pd.DataFrame(history).copy()
    if df.empty or "date" not in df or "value" not in df:
        return False

    df["date"] = pd.to_datetime(df["date"])
    weekly = (
        df.set_index("date")["value"]
        .sort_index()
        .resample("W-FRI")
        .last()
        .ffill()
        .dropna()
    )
    needed = weeks + 1
    if len(weekly) < needed:
        return False
    tail = weekly.iloc[-needed:]
    return bool((tail.diff().dropna() < 0).all())


@lru_cache(maxsize=4)
def _load_config(path: Path) -> dict[str, Any]:
    with open(path) as f:
        return yaml.safe_load(f)
