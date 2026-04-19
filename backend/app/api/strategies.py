from typing import Any

from fastapi import APIRouter, Body, HTTPException
from pydantic import ValidationError

from app.core.registry import all_strategies, get_strategy
from app.schemas.results import (
    StrategyListResponse,
    StrategyMeta,
    StrategyResult,
)

router = APIRouter(prefix="/strategies", tags=["strategies"])


@router.get("", response_model=StrategyListResponse)
def list_strategies() -> StrategyListResponse:
    return StrategyListResponse(
        strategies=[
            StrategyMeta(
                id=s.id,
                name=s.name,
                description=s.description,
                instrument_kind=s.instrument_kind.value,
                has_summary=s.has_summary,
            )
            for s in all_strategies().values()
        ]
    )


@router.get("/{strategy_id}/schema")
def get_schema(strategy_id: str) -> dict[str, Any]:
    strategy = get_strategy(strategy_id)
    if strategy is None:
        raise HTTPException(status_code=404, detail=f"Unknown strategy: {strategy_id}")
    return strategy.ParamsModel.model_json_schema()


@router.post("/{strategy_id}/compute", response_model=StrategyResult)
def compute(
    strategy_id: str, params: dict[str, Any] = Body(...)
) -> StrategyResult:
    strategy = get_strategy(strategy_id)
    if strategy is None:
        raise HTTPException(status_code=404, detail=f"Unknown strategy: {strategy_id}")
    try:
        parsed = strategy.ParamsModel.model_validate(params)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc
    try:
        return strategy.compute(parsed)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/{strategy_id}/summary", response_model=StrategyResult)
def compute_summary(
    strategy_id: str, params: dict[str, Any] = Body(...)
) -> StrategyResult:
    strategy = get_strategy(strategy_id)
    if strategy is None:
        raise HTTPException(status_code=404, detail=f"Unknown strategy: {strategy_id}")
    if not strategy.has_summary:
        raise HTTPException(
            status_code=404,
            detail=f"Strategy '{strategy_id}' does not expose a summary",
        )
    try:
        parsed = strategy.ParamsModel.model_validate(params)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc
    try:
        return strategy.compute_summary(parsed)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
