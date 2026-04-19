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
];

export function findStrategy(id: string): StrategyMeta | undefined {
  return STRATEGIES.find((s) => s.id === id);
}
