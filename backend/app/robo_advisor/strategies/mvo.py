from __future__ import annotations

import logging
from datetime import date

import numpy as np
import pandas as pd
from sklearn.covariance import LedoitWolf

from .base import BasePortfolioStrategy, MIN_POSITION, MAX_POSITION

try:
    import cvxpy as cp
except ModuleNotFoundError:  # pragma: no cover - runtime fallback
    cp = None

logger = logging.getLogger(__name__)

_LOOKBACK = 252
_RF = 0.0  # daily risk-free rate


class MVOStrategy(BasePortfolioStrategy):
    def __init__(
        self,
        mode: str = "max_sharpe",
        lookback: int = _LOOKBACK,
        min_pos: float = MIN_POSITION,
        max_pos: float = MAX_POSITION,
    ) -> None:
        if mode not in ("max_sharpe", "min_variance"):
            raise ValueError(f"Unknown mode: {mode}")
        self.mode = mode
        self.lookback = lookback
        self.min_pos = min_pos
        self.max_pos = max_pos

    def compute_target_weights(
        self,
        as_of_date: date,
        universe: list[str],
        price_data: pd.DataFrame,
    ) -> dict[str, float]:
        cols = [c for c in universe if c in price_data.columns]
        if not cols:
            return self.equal_weight(universe)

        df = price_data[cols].copy()
        df = df[df.index <= pd.Timestamp(as_of_date)]
        df = df.tail(self.lookback + 1).dropna(how="all")

        if len(df) < max(30, self.lookback // 2):
            logger.warning("MVO: only %d rows (need %d), falling back to equal weight", len(df), self.lookback // 2)
            return self.equal_weight(universe)

        returns = df.pct_change().dropna()
        if len(returns) < 2:
            return self.equal_weight(universe)

        n = len(cols)
        mu = returns.mean().values * 252  # annualized

        lw = LedoitWolf()
        lw.fit(returns.values)
        Sigma = lw.covariance_ * 252
        Sigma = (Sigma + Sigma.T) / 2 + 1e-6 * np.eye(n)  # ensure strict PSD

        try:
            if self.mode == "min_variance":
                w = self._min_variance(n, Sigma)
            else:
                w = self._max_sharpe(n, mu, Sigma)

            if w is None:
                raise ValueError("Solver returned None")

            result = {t: float(w[i]) for i, t in enumerate(cols)}
            for t in universe:
                if t not in result:
                    result[t] = 0.0
            return self._enforce_bounds(result)

        except Exception as exc:
            logger.warning("MVO optimization failed (%s): %s — equal weight fallback", self.mode, exc)
            return self.equal_weight(universe)

    def _enforce_bounds(self, weights: dict[str, float]) -> dict[str, float]:
        tickers = list(weights.keys())
        arr = np.array([weights[t] for t in tickers], dtype=float)
        arr = np.clip(arr, self.min_pos, self.max_pos)
        free = np.ones(len(arr), dtype=bool)

        for _ in range(len(arr) * 3):
            gap = 1.0 - arr.sum()
            if abs(gap) <= 1e-10:
                break
            active = np.where(free)[0]
            if len(active) == 0:
                break
            arr[active] += gap / len(active)

            over = active[arr[active] > self.max_pos]
            under = active[arr[active] < self.min_pos]
            if len(over) == 0 and len(under) == 0:
                continue
            if len(over) > 0:
                arr[over] = self.max_pos
                free[over] = False
            if len(under) > 0:
                arr[under] = self.min_pos
                free[under] = False

        arr = np.clip(arr, self.min_pos, self.max_pos)
        arr = arr / arr.sum()
        return dict(zip(tickers, arr.tolist()))

    def _min_variance(self, n: int, Sigma: np.ndarray) -> np.ndarray | None:
        if cp is None:
            inv_var = 1.0 / np.clip(np.diag(Sigma), 1e-8, None)
            return inv_var / inv_var.sum()

        w = cp.Variable(n)
        prob = cp.Problem(
            cp.Minimize(cp.quad_form(w, Sigma)),
            [cp.sum(w) == 1, w >= self.min_pos, w <= self.max_pos],
        )
        prob.solve(solver=cp.CLARABEL, verbose=False)
        if prob.status in ("optimal", "optimal_inaccurate") and w.value is not None:
            return np.maximum(w.value, 0)
        return None

    def _max_sharpe(self, n: int, mu: np.ndarray, Sigma: np.ndarray) -> np.ndarray | None:
        mu_excess = mu - _RF

        if np.all(mu_excess <= 0):
            logger.warning("MVO: no positive excess returns, using min_variance")
            return self._min_variance(n, Sigma)

        if cp is None:
            try:
                raw = np.linalg.pinv(Sigma) @ mu_excess
            except Exception:
                return self._min_variance(n, Sigma)
            raw = np.maximum(raw, 0)
            if raw.sum() <= 1e-10:
                return self._min_variance(n, Sigma)
            return raw / raw.sum()

        # Tangency portfolio: minimize z.T @ Sigma @ z s.t. mu_excess.T @ z == 1
        # w = z / sum(z) after solving.
        # Min/max position constraints: z_i/sum(z) in [min_pos, max_pos]
        # ↔ (I - min_pos * J) @ z >= 0  and  (max_pos * J - I) @ z >= 0
        # where J = ones((n,n)) so (J @ z)[i] = sum(z)
        J = np.ones((n, n))
        A_min = np.eye(n) - self.min_pos * J
        A_max = self.max_pos * J - np.eye(n)

        z = cp.Variable(n)
        prob = cp.Problem(
            cp.Minimize(cp.quad_form(z, Sigma)),
            [
                mu_excess @ z == 1,
                z >= 0,
                A_min @ z >= 0,
                A_max @ z >= 0,
            ],
        )
        prob.solve(solver=cp.CLARABEL, verbose=False)

        if prob.status in ("optimal", "optimal_inaccurate") and z.value is not None:
            z_val = np.maximum(z.value, 0)
            total = z_val.sum()
            if total <= 1e-10:
                return None
            return z_val / total

        # Fallback: try min_variance
        logger.warning("MVO max_sharpe failed (%s), falling back to min_variance", prob.status)
        return self._min_variance(n, Sigma)
