"use client";

import { LinkedPlotlyChart } from "./LinkedPlotlyChart";
import type { TrendSystem } from "@/lib/store";

interface Props {
  figures: Record<string, Record<string, unknown>>;
  activeSystem: TrendSystem;
  currentSignals: Record<string, number>;
  currentLabels: Record<string, string>;
}

function signalBadgeClass(label: string): string {
  if (label === "Buy")
    return "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300";
  if (label === "Sell")
    return "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300";
  return "bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400";
}

export function TrendIndicator({
  figures,
  activeSystem,
  currentSignals,
  currentLabels,
}: Props) {
  const figure = figures[activeSystem];
  const currentLabel = currentLabels[activeSystem];

  return (
    <div className="rounded-xl border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
      <div className="flex items-center justify-between border-b border-zinc-100 px-4 py-2.5 dark:border-zinc-800">
        <h2 className="text-sm font-medium text-zinc-800 dark:text-zinc-200">
          Trend Indicator — {activeSystem}
        </h2>
        {currentLabel && (
          <span
            className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${signalBadgeClass(currentLabel)}`}
          >
            {currentLabel}
          </span>
        )}
      </div>
      <div className="px-2 pb-2 pt-1">
        {figure ? (
          <LinkedPlotlyChart figure={figure} height={160} syncXAxis />
        ) : (
          <p className="py-6 text-center text-xs text-zinc-400">
            No signal data for {activeSystem}
          </p>
        )}
      </div>
    </div>
  );
}
