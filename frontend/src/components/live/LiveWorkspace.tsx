"use client";

import { useMemo } from "react";

import { LiveInstrumentPanel } from "./LiveInstrumentPanel";
import { LivePriceChart } from "./LivePriceChart";
import { SignalSummaryStrip } from "./SignalSummaryStrip";
import { StrategyCheckboxPanel } from "./StrategyCheckboxPanel";
import { TrendIndicator } from "./TrendIndicator";
import { VolatilityIndicator } from "./VolatilityIndicator";
import { useLiveCompute } from "@/lib/live";
import { useLiveStore, TREND_SYSTEMS } from "@/lib/store";
import { useDebouncedValue } from "@/lib/use-debounced-value";

export function LiveWorkspace() {
  const activeId = useLiveStore((s) => s.liveActiveInstrumentId);
  const dateStart = useLiveStore((s) => s.liveDateStart);
  const dateEnd = useLiveStore((s) => s.liveDateEnd);
  const setDateRange = useLiveStore((s) => s.setLiveDateRange);
  const enabled = useLiveStore((s) => s.liveEnabledStrategies);
  const activeTrendSystem = useLiveStore((s) => s.liveActiveTrendSystem);
  const setActiveTrendSystem = useLiveStore((s) => s.setLiveActiveTrendSystem);

  const computeParams = useMemo(() => {
    if (!activeId) return null;
    return {
      instrument_id: activeId,
      date_start: dateStart,
      date_end: dateEnd,
      strategies: enabled as string[],
      active_trend_system: activeTrendSystem,
    };
  }, [activeId, dateStart, dateEnd, enabled, activeTrendSystem]);

  const debouncedParams = useDebouncedValue(computeParams, 400);

  const { data, isFetching, isError, error } = useLiveCompute(debouncedParams);

  const hasVol = enabled.includes("volatility");
  const hasTrend = enabled.includes("trend");

  return (
    <div className="flex flex-1 overflow-hidden">
      {/* ── Sidebar ─────────────────────────────────────────────────────── */}
      <aside className="w-64 shrink-0 overflow-y-auto border-r border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
        <div className="space-y-6">
          <LiveInstrumentPanel />

          {/* Date range */}
          <div className="space-y-2">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-zinc-500">
              Date range
            </h3>
            <div className="space-y-1.5">
              <label className="block">
                <span className="mb-0.5 block text-xs text-zinc-500">From</span>
                <input
                  type="date"
                  value={dateStart ?? ""}
                  onChange={(e) => setDateRange(e.target.value || null, dateEnd)}
                  className={dateCls}
                />
              </label>
              <label className="block">
                <span className="mb-0.5 block text-xs text-zinc-500">To</span>
                <input
                  type="date"
                  value={dateEnd ?? ""}
                  onChange={(e) => setDateRange(dateStart, e.target.value || null)}
                  className={dateCls}
                />
              </label>
            </div>
          </div>

          <StrategyCheckboxPanel />

          {/* Trend system selector — only shown when trend is enabled */}
          {hasTrend && (
            <div className="space-y-2">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-zinc-500">
                Trend system
              </h3>
              <select
                value={activeTrendSystem}
                onChange={(e) =>
                  setActiveTrendSystem(e.target.value as typeof activeTrendSystem)
                }
                className="w-full rounded-md border border-zinc-300 bg-white px-2.5 py-1.5 text-sm text-zinc-900 focus:border-zinc-500 focus:outline-none dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-100"
              >
                {TREND_SYSTEMS.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            </div>
          )}
        </div>
      </aside>

      {/* ── Main content ─────────────────────────────────────────────────── */}
      <main className="flex flex-1 flex-col overflow-y-auto p-5">
        {!activeId && (
          <EmptyState message="Add an instrument to get started." />
        )}

        {activeId && !data && isFetching && (
          <EmptyState message="Computing signals…" />
        )}

        {isError && (
          <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300">
            {error instanceof Error ? error.message : "Compute failed"}
          </div>
        )}

        {data && (
          <div className="space-y-3">
            {/* Warnings */}
            {data.warnings.length > 0 && (
              <div className="space-y-1">
                {data.warnings.map((w, i) => (
                  <p
                    key={i}
                    className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200"
                  >
                    {w}
                  </p>
                ))}
              </div>
            )}

            {/* Signal summary badges */}
            {(hasVol || hasTrend) && (
              <SignalSummaryStrip result={data} enabled={enabled} activeTrendSystem={activeTrendSystem} />
            )}

            {/* Price chart */}
            <LivePriceChart figure={data.price_figure} label={data.label} isFetching={isFetching} />

            {/* Volatility indicator */}
            {hasVol && data.vol_figure && (
              <VolatilityIndicator
                figure={data.vol_figure}
                currentQuintile={data.current_vol_quintile ?? null}
                currentLabel={data.current_vol_label ?? null}
              />
            )}

            {/* Trend indicator */}
            {hasTrend && Object.keys(data.trend_figures).length > 0 && (
              <TrendIndicator
                figures={data.trend_figures}
                activeSystem={activeTrendSystem}
                currentSignals={data.current_trend_signals}
                currentLabels={data.current_trend_labels}
              />
            )}
          </div>
        )}
      </main>
    </div>
  );
}

function EmptyState({ message }: { message: string }) {
  return (
    <div className="flex flex-1 items-center justify-center">
      <p className="text-sm text-zinc-400">{message}</p>
    </div>
  );
}

const dateCls =
  "block w-full rounded-md border border-zinc-300 bg-white px-2.5 py-1.5 text-sm text-zinc-900 focus:border-zinc-500 focus:outline-none dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-100";
