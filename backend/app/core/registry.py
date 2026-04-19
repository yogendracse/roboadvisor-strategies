"""Strategy auto-registration.

Imports every module in `app.strategies.*` and collects any `STRATEGY` attribute
that's an instance of BaseStrategy. Adding a new strategy = drop a new file in
`app/strategies/` with a `STRATEGY = MyStrategy()` at module level. No other edits.
"""

from __future__ import annotations

import importlib
import pkgutil
from functools import lru_cache

from app import strategies as strategies_pkg
from app.strategies.base import BaseStrategy


@lru_cache(maxsize=1)
def _discover() -> dict[str, BaseStrategy]:
    found: dict[str, BaseStrategy] = {}
    for mod_info in pkgutil.iter_modules(strategies_pkg.__path__):
        if mod_info.name.startswith("_") or mod_info.name == "base":
            continue
        module = importlib.import_module(
            f"{strategies_pkg.__name__}.{mod_info.name}"
        )
        strategy = getattr(module, "STRATEGY", None)
        if isinstance(strategy, BaseStrategy):
            if strategy.id in found:
                raise RuntimeError(
                    f"Duplicate strategy id '{strategy.id}' in "
                    f"{mod_info.name} and {found[strategy.id].__class__.__module__}"
                )
            found[strategy.id] = strategy
    return found


def all_strategies() -> dict[str, BaseStrategy]:
    return dict(_discover())


def get_strategy(strategy_id: str) -> BaseStrategy | None:
    return _discover().get(strategy_id)
