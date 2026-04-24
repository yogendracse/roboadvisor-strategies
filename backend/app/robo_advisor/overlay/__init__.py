from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from .constructor import apply_overlay
from .mapping import compute_tilts
from .rules import apply_circuit_breakers
from .signal_builder import build_portfolio_state, build_signals

_CONFIG_PATH = Path(__file__).parents[3] / "config" / "overlay.yaml"


@dataclass
class OverlayPreview:
    core_weights: dict[str, float]
    signals: dict[str, dict[str, float | str]]
    raw_tilts: dict[str, float]
    tilts: dict[str, float]
    active_circuit_breakers: list[str]
    final_weights: dict[str, float]
    overlay_budget_used: float
    overlay_budget_limit: float
    warnings: list[str]


def build_overlay_preview(
    as_of_date: date,
    core_weights: dict[str, float],
    config_path: Path = _CONFIG_PATH,
) -> OverlayPreview:
    portfolio_state = build_portfolio_state(as_of_date, config_path=config_path)
    signals = portfolio_state["signals"]
    raw_tilts = compute_tilts(signals, config_path=config_path)
    adjusted_tilts = apply_circuit_breakers(raw_tilts, portfolio_state, config_path=config_path)
    final_weights = apply_overlay(core_weights, adjusted_tilts, config_path=config_path)

    return OverlayPreview(
        core_weights={asset: float(weight) for asset, weight in core_weights.items()},
        signals=signals,
        raw_tilts={asset: float(tilt) for asset, tilt in raw_tilts.items()},
        tilts={asset: float(tilt) for asset, tilt in adjusted_tilts.items()},
        active_circuit_breakers=list(portfolio_state.get("active_circuit_breakers", [])),
        final_weights={asset: float(weight) for asset, weight in final_weights.items()},
        overlay_budget_used=float(portfolio_state.get("overlay_budget_used", 0.0)),
        overlay_budget_limit=float(portfolio_state.get("overlay_budget_limit", 0.30)),
        warnings=list(portfolio_state.get("warnings", [])),
    )


class OverlayStrategy:
    def __init__(self, core_strategy: Any, config_path: Path = _CONFIG_PATH) -> None:
        self.core_strategy = core_strategy
        self.config_path = config_path
        self.preview_history: dict[date, OverlayPreview] = {}

    def compute_target_weights(
        self,
        as_of_date: date,
        universe: list[str],
        price_data: pd.DataFrame,
    ) -> dict[str, float]:
        core_weights = self.core_strategy.compute_target_weights(as_of_date, universe, price_data)
        preview = build_overlay_preview(as_of_date, core_weights, config_path=self.config_path)
        self.preview_history[as_of_date] = preview
        return preview.final_weights


__all__ = [
    "OverlayPreview",
    "OverlayStrategy",
    "apply_overlay",
    "build_overlay_preview",
    "build_portfolio_state",
    "build_signals",
    "compute_tilts",
    "apply_circuit_breakers",
]
