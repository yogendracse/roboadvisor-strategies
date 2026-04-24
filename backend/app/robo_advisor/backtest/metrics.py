from __future__ import annotations

import numpy as np
import pandas as pd


_TRADING_DAYS = 252


def total_return(equity: pd.Series) -> float:
    return float(equity.iloc[-1] / equity.iloc[0] - 1)


def cagr(equity: pd.Series) -> float:
    n_years = (equity.index[-1] - equity.index[0]).days / 365.25
    if n_years <= 0:
        return 0.0
    return float((equity.iloc[-1] / equity.iloc[0]) ** (1.0 / n_years) - 1)


def annualized_volatility(returns: pd.Series) -> float:
    return float(returns.std() * np.sqrt(_TRADING_DAYS))


def sharpe_ratio(returns: pd.Series, rf: float = 0.0) -> float:
    excess = returns - rf / _TRADING_DAYS
    std = excess.std()
    if std < 1e-10:
        return 0.0
    return float(excess.mean() / std * np.sqrt(_TRADING_DAYS))


def sortino_ratio(returns: pd.Series, rf: float = 0.0) -> float:
    excess = returns - rf / _TRADING_DAYS
    downside = excess[excess < 0]
    if len(downside) == 0 or downside.std() < 1e-10:
        return 0.0
    return float(excess.mean() / downside.std() * np.sqrt(_TRADING_DAYS))


def drawdown_series(equity: pd.Series) -> pd.Series:
    roll_max = equity.cummax()
    return equity / roll_max - 1


def max_drawdown(equity: pd.Series) -> float:
    return float(drawdown_series(equity).min())


def max_drawdown_duration(equity: pd.Series) -> int:
    underwater = drawdown_series(equity) < 0
    if not underwater.any():
        return 0
    max_dur = curr = 0
    for u in underwater:
        curr = curr + 1 if u else 0
        max_dur = max(max_dur, curr)
    return max_dur


def calmar_ratio(equity: pd.Series) -> float:
    mdd = abs(max_drawdown(equity))
    return float(cagr(equity) / mdd) if mdd > 1e-10 else 0.0


def var_95(returns: pd.Series) -> float:
    r = returns.dropna()
    return float(np.percentile(r, 5)) if len(r) > 0 else 0.0


def cvar_95(returns: pd.Series) -> float:
    r = returns.dropna()
    v = var_95(r)
    tail = r[r <= v]
    return float(tail.mean()) if len(tail) > 0 else v


def compute_all(equity: pd.Series) -> dict[str, float]:
    returns = equity.pct_change().dropna()
    return {
        "total_return": total_return(equity),
        "cagr": cagr(equity),
        "volatility": annualized_volatility(returns),
        "sharpe": sharpe_ratio(returns),
        "sortino": sortino_ratio(returns),
        "max_drawdown": max_drawdown(equity),
        "max_drawdown_duration_days": float(max_drawdown_duration(equity)),
        "calmar": calmar_ratio(equity),
        "var_95": var_95(returns),
        "cvar_95": cvar_95(returns),
    }
