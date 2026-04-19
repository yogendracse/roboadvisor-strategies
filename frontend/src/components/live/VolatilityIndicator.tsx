"use client";

import { LinkedPlotlyChart } from "./LinkedPlotlyChart";

const QUINTILE_COLOURS = [
  "#1B5E20",
  "#558B2F",
  "#F9A825",
  "#E65100",
  "#B71C1C",
];

interface Props {
  figure: Record<string, unknown>;
  currentQuintile: number | null;
  currentLabel: string | null;
}

export function VolatilityIndicator({
  figure,
  currentQuintile,
  currentLabel,
}: Props) {
  const colour =
    currentQuintile != null
      ? QUINTILE_COLOURS[currentQuintile - 1]
      : undefined;

  return (
    <div className="rounded-xl border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
      <div className="flex items-center justify-between border-b border-zinc-100 px-4 py-2.5 dark:border-zinc-800">
        <h2 className="text-sm font-medium text-zinc-800 dark:text-zinc-200">
          Volatility Indicator
        </h2>
        {currentQuintile != null && (
          <span
            className="rounded-full px-2.5 py-0.5 text-xs font-semibold text-white"
            style={{ backgroundColor: colour }}
          >
            {currentLabel ?? `Q${currentQuintile}`}
          </span>
        )}
      </div>
      <div className="px-2 pb-2 pt-1">
        <LinkedPlotlyChart figure={figure} height={200} syncXAxis />
      </div>
    </div>
  );
}
