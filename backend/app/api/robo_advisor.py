"""
robo_advisor.py
---------------
FastAPI router for the Robo-Advisor data pipeline (M1).

Endpoints:
    GET /api/robo-advisor/prices/{ticker}
        Return cached OHLCV rows for a single ticker.
        Query params: start, end (YYYY-MM-DD)

    GET /api/robo-advisor/prices
        Return list of available tickers in cache.

    GET /api/robo-advisor/macro/{series_id}
        Return cached FRED macro series rows.
        Query params: start, end

    GET /api/robo-advisor/macro
        Return list of available FRED series in cache.

    GET /api/robo-advisor/signals
        Return harmonized prediction-market signals.
        Query params: signal_id, start, end

    POST /api/robo-advisor/refresh/prices
        Trigger a background yfinance download for given tickers.

    POST /api/robo-advisor/refresh/macro
        Trigger a background FRED download (requires FRED_API_KEY).
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Annotated, Any, Literal

import pandas as pd
import yaml
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel

from app.robo_advisor.data.loaders.fred_loader import MacroLoader
from app.robo_advisor.data.loaders.harmonizer import HarmonizedSignal, SignalHarmonizer
from app.robo_advisor.data.loaders.yfinance_loader import DEFAULT_UNIVERSE, PriceLoader

_STRATEGIES_CONFIG = Path(__file__).parents[2] / "config" / "strategies.yaml"

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/robo-advisor", tags=["robo-advisor"])

# Singletons — created once per process
_price_loader = PriceLoader()
_macro_loader = MacroLoader()
_harmonizer = SignalHarmonizer()


# ─── Response models ──────────────────────────────────────────────────────────

class OHLCVRow(BaseModel):
    date: date
    ticker: str
    open: float | None
    high: float | None
    low: float | None
    close: float
    volume: float | None
    adj_close: float | None


class MacroRow(BaseModel):
    date: date
    series_id: str
    value: float
    series_name: str


class RefreshResponse(BaseModel):
    status: str
    message: str


# ─── Price endpoints ──────────────────────────────────────────────────────────

@router.get("/prices", summary="List cached tickers")
def list_prices() -> list[str]:
    return _price_loader.available_tickers()


@router.get("/prices/{ticker}", summary="OHLCV for a single ticker")
def get_prices(
    ticker: str,
    start: Annotated[date | None, Query(description="Start date YYYY-MM-DD")] = None,
    end:   Annotated[date | None, Query(description="End date YYYY-MM-DD")]   = None,
) -> list[OHLCVRow]:
    try:
        df = _price_loader.load(ticker.upper())
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if start:
        df = df[df["date"] >= start]
    if end:
        df = df[df["date"] <= end]

    return [
        OHLCVRow(
            date=row["date"],
            ticker=row["ticker"],
            open=_float_or_none(row.get("open")),
            high=_float_or_none(row.get("high")),
            low=_float_or_none(row.get("low")),
            close=float(row["close"]),
            volume=_float_or_none(row.get("volume")),
            adj_close=_float_or_none(row.get("adj_close")),
        )
        for _, row in df.iterrows()
    ]


@router.post("/refresh/prices", summary="Download latest prices via yfinance")
def refresh_prices(
    background_tasks: BackgroundTasks,
    tickers: Annotated[list[str], Query()] = DEFAULT_UNIVERSE,
    start: str = "2000-01-01",
) -> RefreshResponse:
    background_tasks.add_task(_price_loader.refresh, tickers, start)
    return RefreshResponse(
        status="accepted",
        message=f"Downloading prices for {tickers} in background",
    )


# ─── Macro endpoints ──────────────────────────────────────────────────────────

@router.get("/macro", summary="List cached FRED series")
def list_macro() -> list[str]:
    return _macro_loader.available_series()


@router.get("/macro/{series_id}", summary="FRED macro series values")
def get_macro(
    series_id: str,
    start: Annotated[date | None, Query()] = None,
    end:   Annotated[date | None, Query()] = None,
) -> list[MacroRow]:
    try:
        df = _macro_loader.load(series_id.upper())
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if start:
        df = df[df["date"] >= start]
    if end:
        df = df[df["date"] <= end]

    return [
        MacroRow(
            date=row["date"],
            series_id=row["series_id"],
            value=float(row["value"]),
            series_name=row.get("series_name", row["series_id"]),
        )
        for _, row in df.iterrows()
    ]


@router.post("/refresh/macro", summary="Refresh FRED macro data (requires FRED_API_KEY)")
def refresh_macro(background_tasks: BackgroundTasks) -> RefreshResponse:
    background_tasks.add_task(_macro_loader.refresh)
    return RefreshResponse(
        status="accepted",
        message="Refreshing FRED macro series in background. Requires FRED_API_KEY env var.",
    )


# ─── Signal endpoints ─────────────────────────────────────────────────────────

@router.get("/signals", summary="Harmonized prediction-market signals")
def get_signals(
    signal_id: Annotated[str | None, Query(description="Filter to a specific signal")] = None,
    start:     Annotated[date | None, Query()] = None,
    end:       Annotated[date | None, Query()] = None,
) -> list[HarmonizedSignal]:
    signal_ids = [signal_id] if signal_id else None
    try:
        return _harmonizer.get_signals(
            signal_ids=signal_ids,
            start=start,
            end=end,
        )
    except Exception as exc:
        logger.exception("Signal harmonizer failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/signals/latest", summary="Latest value for each signal")
def get_latest_signals() -> list[HarmonizedSignal]:
    from app.robo_advisor.data.loaders.harmonizer import SIGNAL_IDS
    results = []
    for sid in SIGNAL_IDS:
        sig = _harmonizer.latest(sid)
        if sig:
            results.append(sig)
    return results


# ─── Portfolio recommendation endpoint ───────────────────────────────────────

class RecommendRequest(BaseModel):
    risk_profile: Literal["conservative", "balanced", "aggressive"] = "balanced"
    capital: float = 100_000.0
    as_of_date: date | None = None


class RecommendResponse(BaseModel):
    weights: dict[str, float]
    dollar_amounts: dict[str, float]
    share_counts: dict[str, int]
    strategy_mix: dict[str, float]
    meta: dict[str, Any]


@router.post("/portfolio/recommend", summary="Compute target portfolio weights")
def recommend_portfolio(body: RecommendRequest) -> RecommendResponse:
    with open(_STRATEGIES_CONFIG) as f:
        cfg = yaml.safe_load(f)

    universe: list[str] = cfg["universe"]["core_etfs"]
    profile_mix: dict[str, float] = cfg["risk_profiles"][body.risk_profile]
    price_df, price_wide = _load_price_frames()

    as_of = pd.Timestamp(body.as_of_date) if body.as_of_date else price_wide.index.max()
    blender = _build_blender(body.risk_profile, cfg)
    weights = blender.compute_target_weights(as_of.date(), universe, price_wide)

    # Latest price per ticker for share count
    latest_prices: dict[str, float] = {}
    for ticker in universe:
        rows = price_df[price_df["ticker"] == ticker]
        if not rows.empty:
            latest_prices[ticker] = float(rows.sort_values("date")["adj_close"].iloc[-1])

    capital = body.capital
    dollar_amounts = {t: round(weights.get(t, 0.0) * capital, 2) for t in universe}
    share_counts: dict[str, int] = {}
    for t in universe:
        price = latest_prices.get(t, 0.0)
        share_counts[t] = int(dollar_amounts[t] / price) if price > 0 else 0

    return RecommendResponse(
        weights={t: round(weights.get(t, 0.0), 6) for t in universe},
        dollar_amounts=dollar_amounts,
        share_counts=share_counts,
        strategy_mix={k: float(v) for k, v in profile_mix.items()},
        meta={
            "universe_size": len(universe),
            "as_of_date": as_of.date().isoformat(),
            "risk_profile": body.risk_profile,
        },
    )


# ─── Backtest endpoint ───────────────────────────────────────────────────────

class OverlayPreviewRequest(BaseModel):
    as_of_date: date
    risk_profile: Literal["conservative", "balanced", "aggressive"] = "balanced"


class SignalSnapshot(BaseModel):
    value: float
    baseline: float
    deviation: float
    z: float
    rolling_mean: float
    rolling_std: float
    source: str
    confidence: float
    as_of_date: str


class OverlayPreviewResponse(BaseModel):
    core_weights: dict[str, float]
    signals: dict[str, SignalSnapshot]
    raw_tilts: dict[str, float]
    tilts: dict[str, float]
    active_circuit_breakers: list[str]
    final_weights: dict[str, float]
    overlay_budget_used: float
    overlay_budget_limit: float
    warnings: list[str] = []


_BACKTEST_CONFIG = Path(__file__).parents[2] / "config" / "backtest.yaml"


class BacktestRequest(BaseModel):
    risk_profile: Literal["conservative", "balanced", "aggressive"] = "balanced"
    start_date: str = "2015-01-01"
    end_date: str = "2026-04-01"
    initial_capital: float = 100_000.0
    rebalance_freq: Literal["daily", "weekly", "monthly", "quarterly"] = "monthly"
    tx_cost_bps: float = 5.0
    use_overlay: bool = False


class EquityPoint(BaseModel):
    date: str
    value: float


class MetricsDict(BaseModel):
    total_return: float
    cagr: float
    volatility: float
    sharpe: float
    sortino: float
    max_drawdown: float
    max_drawdown_duration_days: float
    calmar: float
    var_95: float
    cvar_95: float


class BenchmarkResult(BaseModel):
    equity_curve: list[EquityPoint]
    metrics: MetricsDict


class TradesSummary(BaseModel):
    total_trades: int
    total_cost_dollars: float
    turnover_annualized: float


class TradeRow(BaseModel):
    date: str
    ticker: str
    delta_weight: float
    price: float
    cost_dollars: float


class AttributionDict(BaseModel):
    core_return: float
    overlay_return: float
    total_return: float
    overlay_sharpe_contribution: float


class BacktestResponse(BaseModel):
    equity_curve: list[EquityPoint]
    metrics: MetricsDict
    benchmarks: dict[str, BenchmarkResult]
    trades_summary: TradesSummary
    trades: list[TradeRow]
    equity_figure: dict  # Plotly JSON
    drawdown_figure: dict  # Plotly JSON
    attribution: AttributionDict
    core_equity_curve: list[EquityPoint] | None = None
    overlay_equity_curve: list[EquityPoint] | None = None
    warnings: list[str] = []
    meta: dict[str, Any]


@router.post("/overlay/preview", summary="Preview prediction-market overlay")
def preview_overlay(body: OverlayPreviewRequest) -> OverlayPreviewResponse:
    from app.robo_advisor.overlay import build_overlay_preview

    with open(_STRATEGIES_CONFIG) as f:
        strat_cfg = yaml.safe_load(f)

    universe: list[str] = strat_cfg["universe"]["core_etfs"]
    _, price_wide = _load_price_frames()
    blender = _build_blender(body.risk_profile, strat_cfg)
    core_weights = blender.compute_target_weights(body.as_of_date, universe, price_wide)
    preview = build_overlay_preview(body.as_of_date, core_weights)

    return OverlayPreviewResponse(
        core_weights={k: round(float(v), 6) for k, v in preview.core_weights.items()},
        signals={k: SignalSnapshot(**v) for k, v in preview.signals.items()},
        raw_tilts={k: round(float(v), 6) for k, v in preview.raw_tilts.items()},
        tilts={k: round(float(v), 6) for k, v in preview.tilts.items()},
        active_circuit_breakers=preview.active_circuit_breakers,
        final_weights={k: round(float(v), 6) for k, v in preview.final_weights.items()},
        overlay_budget_used=round(preview.overlay_budget_used, 6),
        overlay_budget_limit=round(preview.overlay_budget_limit, 6),
        warnings=preview.warnings,
    )


def _load_price_frames() -> tuple[pd.DataFrame, pd.DataFrame]:
    try:
        price_df = _price_loader.load()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=f"Price data unavailable: {exc}") from exc

    price_wide = (
        price_df.pivot_table(index="date", columns="ticker", values="adj_close")
        .pipe(lambda df: df.set_index(pd.to_datetime(df.index)))
        .sort_index()
    )
    return price_df, price_wide


def _build_blender(risk_profile: str, cfg: dict) -> Any:
    from app.robo_advisor.strategies.blender import StrategyBlender
    from app.robo_advisor.strategies.mvo import MVOStrategy
    from app.robo_advisor.strategies.risk_parity import RiskParityStrategy

    constraints = cfg["constraints"]
    profile_mix: dict[str, float] = cfg["risk_profiles"][risk_profile]
    pairs: list[tuple[Any, float]] = []
    if profile_mix.get("mvo", 0) > 0:
        pairs.append((
            MVOStrategy(
                mode="max_sharpe",
                lookback=constraints["lookback_days"],
                min_pos=constraints["min_position"],
                max_pos=constraints["max_position"],
            ),
            profile_mix["mvo"],
        ))
    if profile_mix.get("risk_parity", 0) > 0:
        pairs.append((
            RiskParityStrategy(
                lookback=constraints["lookback_days"],
                min_pos=constraints["min_position"],
                max_pos=constraints["max_position"],
            ),
            profile_mix["risk_parity"],
        ))
    return StrategyBlender(pairs)


def _equity_to_points(eq: pd.Series) -> list[EquityPoint]:
    return [EquityPoint(date=str(d.date()), value=round(float(v), 2)) for d, v in eq.items()]


def _build_equity_figure(
    curves: dict[str, pd.Series],
    colors: dict[str, str] | None = None,
) -> dict:
    import json, plotly.graph_objects as go

    _colors = colors or {
        "Portfolio": "#7c3aed",
        "Core Portfolio": "#0f766e",
        "SPY B&H": "#10b981",
        "60/40": "#f59e0b",
        "Equal Weight": "#3b82f6",
    }
    traces = []
    for name, eq in curves.items():
        norm = eq / eq.iloc[0] * 100
        traces.append(
            go.Scatter(
                x=norm.index.strftime("%Y-%m-%d").tolist(),
                y=[round(float(v), 2) for v in norm],
                mode="lines",
                name=name,
                line={"width": 2, "color": _colors.get(name, "#6b7280")},
            )
        )
    fig = go.Figure(
        data=traces,
        layout=go.Layout(
            title="Portfolio Growth (Base = 100)",
            xaxis={"title": "Date", "showgrid": False},
            yaxis={"title": "Value (Base 100)", "showgrid": True},
            legend={"orientation": "h", "y": -0.15},
            plot_bgcolor="white",
            paper_bgcolor="white",
            height=400,
            margin={"l": 50, "r": 20, "t": 50, "b": 60},
        ),
    )
    return json.loads(fig.to_json())


def _build_drawdown_figure(curves: dict[str, pd.Series]) -> dict:
    import json, plotly.graph_objects as go
    from app.robo_advisor.backtest.metrics import drawdown_series

    _colors = {
        "Portfolio": "#7c3aed",
        "Core Portfolio": "#0f766e",
        "SPY B&H": "#10b981",
        "60/40": "#f59e0b",
        "Equal Weight": "#3b82f6",
    }
    traces = []
    for name, eq in curves.items():
        dd = drawdown_series(eq)
        traces.append(
            go.Scatter(
                x=dd.index.strftime("%Y-%m-%d").tolist(),
                y=[round(float(v) * 100, 2) for v in dd],
                mode="lines",
                name=name,
                fill="tozeroy" if name == "Portfolio" else None,
                line={"width": 1.5, "color": _colors.get(name, "#6b7280")},
                opacity=0.8,
            )
        )
    fig = go.Figure(
        data=traces,
        layout=go.Layout(
            title="Drawdown (%)",
            xaxis={"title": "Date", "showgrid": False},
            yaxis={"title": "Drawdown %", "showgrid": True, "ticksuffix": "%"},
            legend={"orientation": "h", "y": -0.15},
            plot_bgcolor="white",
            paper_bgcolor="white",
            height=250,
            margin={"l": 50, "r": 20, "t": 40, "b": 60},
        ),
    )
    return json.loads(fig.to_json())


@router.post("/backtest/run", summary="Run walk-forward backtest (core strategies)")
def run_backtest(body: BacktestRequest) -> BacktestResponse:
    from datetime import date as date_cls
    from app.robo_advisor.backtest.benchmarks import EqualWeight, SixtyForty, SPYBuyHold
    from app.robo_advisor.backtest.engine import BacktestEngine
    from app.robo_advisor.overlay import OverlayStrategy

    with open(_STRATEGIES_CONFIG) as f:
        strat_cfg = yaml.safe_load(f)
    universe: list[str] = strat_cfg["universe"]["core_etfs"]

    _, price_wide = _load_price_frames()

    start = date_cls.fromisoformat(body.start_date)
    end = date_cls.fromisoformat(body.end_date)

    engine = BacktestEngine(
        start_date=start,
        end_date=end,
        initial_capital=body.initial_capital,
        rebalance_freq=body.rebalance_freq,
        tx_cost_bps=body.tx_cost_bps,
    )
    bm_engine = BacktestEngine(
        start_date=start,
        end_date=end,
        initial_capital=body.initial_capital,
        rebalance_freq=body.rebalance_freq,
        tx_cost_bps=body.tx_cost_bps,
    )

    blender = _build_blender(body.risk_profile, strat_cfg)
    core_result = engine.run(blender, universe, price_wide, strategy_name=f"{body.risk_profile}_blended")
    warnings: list[str] = []

    if body.use_overlay:
        overlay_strategy = OverlayStrategy(blender)
        result = engine.run(
            overlay_strategy,
            universe,
            price_wide,
            strategy_name=f"{body.risk_profile}_overlay",
        )
        for preview in overlay_strategy.preview_history.values():
            warnings.extend(preview.warnings)
        warnings = sorted(set(warnings))
    else:
        result = core_result

    bench_spy = bm_engine.run(SPYBuyHold(), universe, price_wide, "spy_buy_hold")
    bench_6040 = bm_engine.run(SixtyForty(), universe, price_wide, "sixty_forty")
    bench_ew = bm_engine.run(EqualWeight(), universe, price_wide, "equal_weight")

    # Trades summary
    n_trades = len(result.trades)
    total_cost = float(result.trades["cost_dollars"].sum()) if n_trades > 0 else 0.0
    n_years = (pd.Timestamp(end) - pd.Timestamp(start)).days / 365.25
    total_turnover = float(result.trades["delta_weight"].abs().sum()) if n_trades > 0 else 0.0
    turnover_ann = total_turnover / n_years if n_years > 0 else 0.0

    equity_curves = {
        "Portfolio": result.equity_curve,
        "SPY B&H": bench_spy.equity_curve,
        "60/40": bench_6040.equity_curve,
        "Equal Weight": bench_ew.equity_curve,
    }
    if body.use_overlay:
        equity_curves = {
            "Portfolio": result.equity_curve,
            "Core Portfolio": core_result.equity_curve,
            "SPY B&H": bench_spy.equity_curve,
            "60/40": bench_6040.equity_curve,
            "Equal Weight": bench_ew.equity_curve,
        }

    def _to_bench(r: Any) -> BenchmarkResult:
        return BenchmarkResult(
            equity_curve=_equity_to_points(r.equity_curve),
            metrics=MetricsDict(**{k: round(float(v), 6) for k, v in r.metrics.items()}),
        )

    attribution = AttributionDict(
        core_return=round(float(core_result.metrics["total_return"]), 6),
        overlay_return=round(float(result.metrics["total_return"] - core_result.metrics["total_return"]), 6),
        total_return=round(float(result.metrics["total_return"]), 6),
        overlay_sharpe_contribution=round(float(result.metrics["sharpe"] - core_result.metrics["sharpe"]), 6),
    )

    return BacktestResponse(
        equity_curve=_equity_to_points(result.equity_curve),
        metrics=MetricsDict(**{k: round(float(v), 6) for k, v in result.metrics.items()}),
        benchmarks={
            "spy": _to_bench(bench_spy),
            "sixty_forty": _to_bench(bench_6040),
            "equal_weight": _to_bench(bench_ew),
        },
        trades_summary=TradesSummary(
            total_trades=n_trades,
            total_cost_dollars=round(total_cost, 2),
            turnover_annualized=round(turnover_ann, 4),
        ),
        trades=[
            TradeRow(
                date=str(pd.Timestamp(row["date"]).date()),
                ticker=str(row["ticker"]),
                delta_weight=round(float(row["delta_weight"]), 6),
                price=round(float(row["price"]), 4),
                cost_dollars=round(float(row["cost_dollars"]), 4),
            )
            for _, row in result.trades.iterrows()
        ],
        equity_figure=_build_equity_figure(equity_curves),
        drawdown_figure=_build_drawdown_figure(equity_curves),
        attribution=attribution,
        core_equity_curve=_equity_to_points(core_result.equity_curve),
        overlay_equity_curve=_equity_to_points(result.equity_curve) if body.use_overlay else None,
        warnings=warnings,
        meta={
            "risk_profile": body.risk_profile,
            "rebalance_freq": body.rebalance_freq,
            "tx_cost_bps": body.tx_cost_bps,
            "use_overlay": body.use_overlay,
            "universe": universe,
            **result.meta,
        },
    )


# ─── Sensitivity regression ───────────────────────────────────────────────────

@router.get("/analysis/regression")
def get_regression_analysis(
    window: Literal["fred_proxy", "polymarket", "both"] = "both",
) -> dict[str, Any]:
    """
    Run OLS sensitivity regressions for all signal × asset pairs.

    Window options:
    - fred_proxy: 2015–Aug 2025, monthly frequency, FRED proxies for recession_prob / fed_cuts
    - polymarket: Sep 2025–present, daily frequency, actual Polymarket probabilities
    - both: return both windows + combined summary
    """
    from analysis.sensitivity_regression import (
        SensitivityRegressor,
        build_api_response,
        run_both_windows,
        _FRED_WINDOW_START,
        _FRED_WINDOW_END,
        _PM_WINDOW_START,
    )
    import yaml
    from pathlib import Path
    config_path = Path(__file__).parents[3] / "config" / "overlay.yaml"
    overlay_cfg = {}
    if config_path.exists():
        with open(config_path) as f:
            overlay_cfg = yaml.safe_load(f) or {}

    reg = SensitivityRegressor(overlay_cfg)
    today = date.today().isoformat()

    if window == "fred_proxy":
        fred = reg.run_all(_FRED_WINDOW_START, _FRED_WINDOW_END, window="fred_proxy")
        pm: dict = {}
        for sig in fred:
            pm[sig] = {}
    elif window == "polymarket":
        pm = reg.run_all(_PM_WINDOW_START, today, window="polymarket")
        fred = {}
        for sig in pm:
            fred[sig] = {}
    else:
        fred, pm = run_both_windows(overlay_cfg)

    return build_api_response(fred, pm, reg, window)


# ─── Overlay config PATCH ─────────────────────────────────────────────────────

class OverlayPatchBody(BaseModel):
    sensitivities: dict[str, dict[str, float]]


@router.patch("/config/overlay")
def patch_overlay_config(body: OverlayPatchBody) -> dict[str, Any]:
    """
    Partial-update overlay.yaml sensitivities.

    Only keys provided are updated; all others keep their current values.
    Backs up existing file to overlay.yaml.bak before writing.
    Overlay engine reads config at request time — no restart needed.
    """
    config_path = Path(__file__).parents[3] / "config" / "overlay.yaml"
    bak_path = config_path.with_suffix(".yaml.bak")

    import shutil
    import yaml as _yaml  # type: ignore[import]

    if not config_path.exists():
        raise HTTPException(status_code=404, detail="overlay.yaml not found")

    with open(config_path) as f:
        cfg = _yaml.safe_load(f) or {}

    shutil.copy2(config_path, bak_path)

    signals_cfg = cfg.setdefault("signals", {})
    for signal_name, asset_betas in body.sensitivities.items():
        sig_block = signals_cfg.setdefault(signal_name, {})
        sensitivities = sig_block.setdefault("sensitivities", {})
        for asset, beta in asset_betas.items():
            sensitivities[asset] = round(float(beta), 6)

    with open(config_path, "w") as f:
        _yaml.dump(cfg, f, default_flow_style=False, sort_keys=False)

    logger.info("overlay.yaml updated; backup at %s", bak_path)
    return {"status": "updated", "backup": str(bak_path), "config": cfg}


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _float_or_none(v) -> float | None:
    try:
        f = float(v)
        import math
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None
