"use client";

import { LinkedPlotlyChart } from "./LinkedPlotlyChart";

interface Props {
  figure: Record<string, unknown>;
  label: string;
  isFetching?: boolean;
}

export function LivePriceChart({ figure, label, isFetching }: Props) {
  return (
    <div className="rounded-xl border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
      <div className="flex items-center justify-between border-b border-zinc-100 px-4 py-2.5 dark:border-zinc-800">
        <h2 className="text-sm font-medium text-zinc-800 dark:text-zinc-200">
          {label}
        </h2>
        {isFetching && (
          <span className="text-xs text-zinc-400">Updating…</span>
        )}
      </div>
      <div className="px-2 pb-2 pt-1">
        <LinkedPlotlyChart figure={figure} height={300} syncXAxis />
      </div>
    </div>
  );
}
