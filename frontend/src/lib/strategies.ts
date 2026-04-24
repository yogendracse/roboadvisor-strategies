import type { InstrumentKind } from "./instruments";

export interface StrategyMeta {
  id: string;
  name: string;
  description: string;
  kind: InstrumentKind;
  has_summary: boolean;
}

export const STRATEGIES: StrategyMeta[] = [
  {
    id: "vol-analysis",
    name: "Volatility Analysis",
    description:
      "Mean-reversion on rolling vol z-scores. Long low-vol quantile, short high-vol quantile.",
    kind: "vol",
    has_summary: true,
  },
  {
    id: "trend-following",
    name: "Trend Following",
    description:
      "Moving-average crossovers & breakout systems. Equal-weight or inverse-vol portfolio of best-per-asset system.",
    kind: "trend",
    has_summary: false,
  },
  {
    id: "counter-trend",
    name: "Counter Trend",
    description:
      "Six counter-trend approaches: Range Exhaustion, Doji Detection, Spread Mean-Reversion, Drawdown Entry, Renko, and ML Enhancement. S&P 500 futures 2003–2021.",
    kind: "trend",
    has_summary: false,
  },
  {
    id: "pairs-trading",
    name: "Pairs Trading",
    description:
      "Spread-based pairs trade on two instruments (Black & White). Dickey-Fuller cointegration, multi-horizon signals (N=5/10/20), full position engine, inverse-vol sizing, in-sample vs out-of-sample split, and parameter-sweep overfitting check.",
    kind: "trend",
    has_summary: false,
  },
];

export function findStrategy(id: string): StrategyMeta | undefined {
  return STRATEGIES.find((s) => s.id === id);
}
