"""Simulator API.

POST /api/simulator/run  — run a simulation and return a StrategyResult.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.schemas.results import StrategyResult
from app.services.simulator_service import SimulatorParams, build_result

router = APIRouter(prefix="/simulator", tags=["simulator"])


@router.post("/run", response_model=StrategyResult)
def run_simulator(params: SimulatorParams) -> StrategyResult:
    """Execute the portfolio simulation and return charts + metrics.

    The engine fetches live data from yfinance, runs a time-stepping loop
    with no lookahead bias, and returns a StrategyResult in the same schema
    as all other strategy compute endpoints.
    """
    try:
        return build_result(params)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
