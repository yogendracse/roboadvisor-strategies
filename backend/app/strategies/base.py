"""Strategy plugin interface.

A Strategy subclasses BaseStrategy, declares a ParamsModel (Pydantic), and implements
`compute(params)` returning a StrategyResult. The module must set `STRATEGY = MyStrategy()`
for the registry to pick it up.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar, Type

from pydantic import BaseModel

from app.schemas.common import InstrumentKind
from app.schemas.results import StrategyResult


class BaseStrategy(ABC):
    id: ClassVar[str]
    name: ClassVar[str]
    description: ClassVar[str]
    instrument_kind: ClassVar[InstrumentKind]
    ParamsModel: ClassVar[Type[BaseModel]]
    has_summary: ClassVar[bool] = False

    @abstractmethod
    def compute(self, params: BaseModel) -> StrategyResult:
        """Run the strategy on a single instrument. Fast (<1s)."""

    def compute_summary(self, params: BaseModel) -> StrategyResult:
        """Multi-instrument summary. Only implemented if has_summary=True."""
        raise NotImplementedError(
            f"Strategy '{self.id}' does not expose a summary computation"
        )
