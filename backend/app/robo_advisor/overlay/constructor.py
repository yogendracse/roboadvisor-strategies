from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import yaml

_CONFIG_PATH = Path(__file__).parents[3] / "config" / "overlay.yaml"

try:
    import cvxpy as cp
except ModuleNotFoundError:  # pragma: no cover - exercised in runtime fallback
    cp = None


def apply_overlay(
    core_weights: dict[str, float],
    tilts: dict[str, float],
    config_path: Path = _CONFIG_PATH,
) -> dict[str, float]:
    with open(config_path) as f:
        overlay_cfg: dict[str, Any] = yaml.safe_load(f)

    assets = list(core_weights.keys())
    target = np.array(
        [float(core_weights.get(asset, 0.0)) + float(tilts.get(asset, 0.0)) for asset in assets],
        dtype=float,
    )

    if target.sum() <= 1e-12:
        target = np.array([1.0 / len(assets)] * len(assets), dtype=float)
    else:
        target = target / target.sum()

    min_position = float(overlay_cfg.get("constraints", {}).get("min_position", 0.01))
    max_position = float(overlay_cfg.get("constraints", {}).get("max_position", 0.25))

    if _is_valid(target, min_position, max_position):
        return dict(zip(assets, target.tolist(), strict=False))

    repaired = _nearest_valid_weights(target, min_position, max_position)
    return dict(zip(assets, repaired.tolist(), strict=False))


def _is_valid(weights: np.ndarray, min_position: float, max_position: float) -> bool:
    return bool(
        abs(weights.sum() - 1.0) <= 1e-8
        and np.all(weights >= min_position - 1e-8)
        and np.all(weights <= max_position + 1e-8)
    )


def _nearest_valid_weights(
    target: np.ndarray,
    min_position: float,
    max_position: float,
) -> np.ndarray:
    if cp is None:
        return _project_bounded_simplex(target, min_position, max_position)

    n_assets = len(target)
    weights = cp.Variable(n_assets)
    objective = cp.Minimize(cp.sum_squares(weights - target))
    constraints = [
        cp.sum(weights) == 1,
        weights >= min_position,
        weights <= max_position,
    ]
    problem = cp.Problem(objective, constraints)

    for solver in (cp.OSQP, cp.SCS):
        try:
            problem.solve(solver=solver, warm_start=True, verbose=False)
        except Exception:
            continue
        if weights.value is not None:
            solution = np.asarray(weights.value, dtype=float)
            solution = np.clip(solution, min_position, max_position)
            solution = solution / solution.sum()
            return solution

    return _project_bounded_simplex(target, min_position, max_position)


def _project_bounded_simplex(
    target: np.ndarray,
    min_position: float,
    max_position: float,
) -> np.ndarray:
    weights = np.clip(target.astype(float), min_position, max_position)
    free = np.ones(len(weights), dtype=bool)

    for _ in range(len(weights) * 3):
        gap = 1.0 - weights.sum()
        if abs(gap) <= 1e-10:
            break
        active = np.where(free)[0]
        if len(active) == 0:
            break
        weights[active] += gap / len(active)

        over = active[weights[active] > max_position]
        under = active[weights[active] < min_position]
        if len(over) == 0 and len(under) == 0:
            continue
        if len(over) > 0:
            weights[over] = max_position
            free[over] = False
        if len(under) > 0:
            weights[under] = min_position
            free[under] = False

    weights = np.clip(weights, min_position, max_position)
    weights = weights / weights.sum()
    return weights
