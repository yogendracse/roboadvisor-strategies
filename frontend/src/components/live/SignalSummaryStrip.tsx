"use client";

import type { LiveComputeResult } from "@/lib/live";
import type { LiveStrategy, TrendSystem } from "@/lib/store";

const QUINTILE_COLOURS = [
  "#1B5E20",
  "#558B2F",
  "#F9A825",
  "#E65100",
  "#B71C1C",
];

interface Props {
  result: LiveComputeResult;
  enabled: LiveStrategy[];
  activeTrendSystem: TrendSystem;
}

function signalBadgeClass(label: string): string {
  if (label === "Buy")
    return "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300";
  if (label === "Sell")
    return "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300";
  return "bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400";
}

export function SignalSummaryStrip({
  result,
  enabled,
  activeTrendSystem,
}: Props) {
  const badges: React.ReactNode[] = [];

  if (enabled.includes("volatility") && result.current_vol_quintile != null) {
    const q = result.current_vol_quintile;
    const colour = QUINTILE_COLOURS[q - 1];
    badges.push(
      <Badge key="vol">
        <span className="text-zinc-500">VOL:</span>{" "}
        <span
          className="rounded px-1.5 py-0.5 text-[11px] font-semibold text-white"
          style={{ backgroundColor: colour }}
        >
          {result.current_vol_label ?? `Q${q}`}
        </span>
      </Badge>,
    );
  }

  if (enabled.includes("trend")) {
    const label = result.current_trend_labels[activeTrendSystem];
    if (label) {
      badges.push(
        <Badge key="trend">
          <span className="text-zinc-500">TREND ({activeTrendSystem}):</span>{" "}
          <span
            className={`rounded px-1.5 py-0.5 text-[11px] font-semibold ${signalBadgeClass(label)}`}
          >
            {label}
          </span>
        </Badge>,
      );
    }
  }

  if (badges.length === 0) return null;

  return (
    <div className="flex flex-wrap items-center gap-2 rounded-lg border border-zinc-200 bg-white px-3 py-2 dark:border-zinc-800 dark:bg-zinc-900">
      <span className="text-xs font-semibold uppercase tracking-wide text-zinc-400">
        Now
      </span>
      {badges}
    </div>
  );
}

function Badge({ children }: { children: React.ReactNode }) {
  return (
    <span className="flex items-center gap-1 text-sm">{children}</span>
  );
}
