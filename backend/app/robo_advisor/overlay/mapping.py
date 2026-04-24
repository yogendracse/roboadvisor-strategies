from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

_CONFIG_PATH = Path(__file__).parents[3] / "config" / "overlay.yaml"


def compute_tilts(
    signals: dict[str, dict[str, float | str]],
    config_path: Path = _CONFIG_PATH,
) -> dict[str, float]:
    config = _load_config(config_path)
    tilts: dict[str, float] = {}

    for signal_name, signal_payload in signals.items():
        spec = config.get("signals", {}).get(signal_name, {})
        sensitivities = spec.get("sensitivities", {})
        deviation = float(signal_payload.get("deviation", 0.0))
        for asset, sensitivity in sensitivities.items():
            tilts[asset] = tilts.get(asset, 0.0) + float(sensitivity) * deviation

    return {asset: float(tilt) for asset, tilt in tilts.items()}


@lru_cache(maxsize=4)
def _load_config(path: Path) -> dict[str, Any]:
    with open(path) as f:
        return yaml.safe_load(f)
