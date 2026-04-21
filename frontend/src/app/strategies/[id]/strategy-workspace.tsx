"use client";

import { useEffect, useMemo, useState } from "react";

import { InstrumentPicker } from "@/components/instruments/InstrumentPicker";
import { MetricStrip } from "@/components/strategy/MetricStrip";
import { TabContent } from "@/components/strategy/TabContent";
import {
  defaultVolParams,
  VolAnalysisParams,
  type VolAnalysisParamValues,
} from "@/components/strategy/VolAnalysisParams";
import {
  defaultTrendParams,
  TrendFollowingParams,
  type TrendFollowingParamValues,
} from "@/components/strategy/TrendFollowingParams";
import {
  defaultCounterTrendParams,
  CounterTrendParams,
  type CounterTrendParamValues,
} from "@/components/strategy/CounterTrendParams";
import { Markdown } from "@/components/ui/Markdown";
import { Tabs, type TabDef } from "@/components/ui/Tabs";
import { useInstruments } from "@/lib/instruments";
import { useStrategyStore } from "@/lib/store";
import type { StrategyMeta } from "@/lib/strategies";
import {
  useComputeQuery,
  useSummaryQuery,
} from "@/lib/strategy-compute";
import { useDebouncedValue } from "@/lib/use-debounced-value";

interface Props {
  strategy: StrategyMeta;
}

const SUMMARY_TAB_ID = "__summary__";

export function StrategyWorkspace({ strategy }: Props) {
  const activeId = useStrategyStore((s) => s.activeInstrumentId[strategy.kind]);
  const instruments = useInstruments(strategy.kind);
  const activeInst = useMemo(
    () => instruments.data?.instruments.find((i) => i.id === activeId),
    [instruments.data, activeId],
  );

  const [volParams, setVolParams] =
    useState<VolAnalysisParamValues>(defaultVolParams);
  const [trendParams, setTrendParams] =
    useState<TrendFollowingParamValues>(defaultTrendParams);
  const [counterTrendParams, setCounterTrendParams] =
    useState<CounterTrendParamValues>(defaultCounterTrendParams);
  const [activeTabId, setActiveTabId] = useState<string | null>(null);

  // Compute windows
  const trendDateRange = useMemo(() => {
    const insts = instruments.data?.instruments ?? [];
    if (insts.length === 0) return null;
    const minD = insts.reduce((acc, i) => (i.min_date < acc ? i.min_date : acc), insts[0].min_date);
    const maxD = insts.reduce((acc, i) => (i.max_date > acc ? i.max_date : acc), insts[0].max_date);
    return { min: minD, max: maxD };
  }, [instruments.data]);

  // Vol: default date range from active instrument
  useEffect(() => {
    if (strategy.id !== "vol-analysis" || !activeInst) return;
    setVolParams((p) => ({
      ...p,
      date_start: activeInst.min_date,
      date_end: activeInst.max_date,
    }));
  }, [strategy.id, activeInst?.id, activeInst?.min_date, activeInst?.max_date]);

  // Trend: default date range from union of all instruments
  useEffect(() => {
    if (strategy.id !== "trend-following" || !trendDateRange) return;
    setTrendParams((p) => ({
      ...p,
      date_start: p.date_start ?? trendDateRange.min,
      date_end: p.date_end ?? trendDateRange.max,
    }));
  }, [strategy.id, trendDateRange?.min, trendDateRange?.max]);

  // Trend: sync signal_asset from picker selection
  useEffect(() => {
    if (strategy.id !== "trend-following" || !activeInst) return;
    setTrendParams((p) =>
      p.signal_asset === activeInst.label
        ? p
        : { ...p, signal_asset: activeInst.label },
    );
  }, [strategy.id, activeInst?.label]);

  const computeBody = useMemo<Record<string, unknown> | null>(() => {
    if (strategy.id === "vol-analysis") {
      if (!activeInst) return null;
      return { ...volParams, instrument_id: activeInst.id };
    }
    if (strategy.id === "trend-following") {
      return { ...trendParams };
    }
    if (strategy.id === "counter-trend") {
      return { ...counterTrendParams };
    }
    return null;
  }, [strategy.id, activeInst, volParams, trendParams, counterTrendParams]);

  const debouncedBody = useDebouncedValue(computeBody, 300);
  const compute = useComputeQuery(strategy.id, debouncedBody);
  const result = compute.data;

  const isSummaryActive = activeTabId === SUMMARY_TAB_ID;
  const summary = useSummaryQuery(
    strategy.id,
    debouncedBody,
    isSummaryActive && strategy.has_summary,
  );
  const summaryResult = summary.data;

  // Reset tab when strategy changes
  useEffect(() => {
    setActiveTabId(null);
  }, [strategy.id]);

  // Default active tab = first compute tab
  useEffect(() => {
    if (activeTabId !== null || !result?.tabs?.length) return;
    setActiveTabId(result.tabs[0].id);
  }, [result?.tabs, activeTabId]);

  const tabDefs: TabDef[] = useMemo(() => {
    const base: TabDef[] =
      result?.tabs?.map((t) => ({ id: t.id, title: t.title, icon: t.icon })) ??
      [];
    if (strategy.has_summary && base.length > 0) {
      base.push({
        id: SUMMARY_TAB_ID,
        title: "Summary · All Instruments",
        icon: "🌐",
      });
    }
    return base;
  }, [result, strategy.has_summary]);

  const activeTab =
    activeTabId === SUMMARY_TAB_ID
      ? summaryResult?.tabs?.[0] ?? null
      : result?.tabs?.find((t) => t.id === activeTabId) ?? null;

  const loadingSummary =
    isSummaryActive && summary.isFetching && !summaryResult;

  const assetLabels = useMemo(
    () => instruments.data?.instruments.map((i) => i.label) ?? [],
    [instruments.data],
  );

  return (
    <div className="flex flex-1 gap-4 p-4">
      <aside className="flex w-72 shrink-0 flex-col gap-4">
        {strategy.id !== "counter-trend" && (
          <div className="flex flex-col rounded-xl border border-zinc-200 bg-white p-4 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
            <InstrumentPicker kind={strategy.kind} />
            {strategy.id === "trend-following" && (
              <p className="mt-2 text-[11px] text-zinc-500">
                All instruments above are included. Selection chooses the default
                asset for the Signal tab.
              </p>
            )}
          </div>
        )}
        {strategy.id === "counter-trend" && (
          <div className="flex flex-col rounded-xl border border-zinc-200 bg-white p-4 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
            <p className="text-[11px] text-zinc-500">
              Uses bundled S&amp;P 500 futures data (2003–2021). Parameters below
              apply across all six tabs simultaneously.
            </p>
          </div>
        )}

        <div className="flex flex-col gap-3 rounded-xl border border-zinc-200 bg-white p-4 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold uppercase tracking-wide text-zinc-500">
              Parameters
            </h3>
            {(compute.isFetching || summary.isFetching) && (
              <span className="flex items-center gap-1 text-[11px] text-zinc-500">
                <Spinner /> computing
              </span>
            )}
          </div>

          {strategy.id === "vol-analysis" && activeInst && (
            <VolAnalysisParams
              value={volParams}
              onChange={setVolParams}
              minDate={activeInst.min_date}
              maxDate={activeInst.max_date}
            />
          )}
          {strategy.id === "trend-following" && (
            <TrendFollowingParams
              value={trendParams}
              onChange={setTrendParams}
              minDate={trendDateRange?.min}
              maxDate={trendDateRange?.max}
              assetLabels={assetLabels}
            />
          )}
          {strategy.id === "counter-trend" && (
            <CounterTrendParams
              value={counterTrendParams}
              onChange={setCounterTrendParams}
            />
          )}
        </div>
      </aside>

      <section className="flex min-w-0 flex-1 flex-col gap-4 overflow-hidden">
        <header className="rounded-xl border border-zinc-200 bg-white p-4 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
          <h2 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">
            {strategy.name}
            {strategy.id === "vol-analysis" && activeInst && (
              <span className="ml-2 text-sm font-normal text-zinc-500">
                · {activeInst.label}
              </span>
            )}
          </h2>
          <p className="text-sm text-zinc-600 dark:text-zinc-400">
            {strategy.description}
          </p>
        </header>

        {compute.isError && (
          <ErrorNote
            label="Compute failed"
            message={
              compute.error instanceof Error
                ? compute.error.message
                : String(compute.error)
            }
          />
        )}

        {result?.overview_md && !isSummaryActive && (
          <Card>
            <Markdown>{result.overview_md}</Markdown>
          </Card>
        )}
        {summaryResult?.overview_md && isSummaryActive && (
          <Card>
            <Markdown>{summaryResult.overview_md}</Markdown>
          </Card>
        )}

        {(!!result?.warnings?.length || !!summaryResult?.warnings?.length) && (
          <div className="flex flex-col gap-2">
            {(isSummaryActive ? summaryResult?.warnings : result?.warnings)?.map(
              (w, i) => (
                <div
                  key={i}
                  className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-300"
                >
                  {w}
                </div>
              ),
            )}
          </div>
        )}

        {result && !isSummaryActive && (result.metrics?.length ?? 0) > 0 && (
          <MetricStrip metrics={result.metrics ?? []} />
        )}

        {tabDefs.length > 0 && (
          <Tabs
            tabs={tabDefs}
            active={activeTabId ?? tabDefs[0].id}
            onChange={setActiveTabId}
          />
        )}

        {summary.isError && isSummaryActive && (
          <ErrorNote
            label="Summary failed"
            message={
              summary.error instanceof Error
                ? summary.error.message
                : String(summary.error)
            }
          />
        )}

        {loadingSummary && (
          <div className="flex items-center justify-center rounded-xl border border-dashed border-zinc-300 p-10 text-sm text-zinc-500 dark:border-zinc-700">
            Running the strategy across every instrument — this takes a few seconds…
          </div>
        )}

        {activeTab && (
          <TabContent
            tab={activeTab}
            isStale={
              isSummaryActive
                ? summary.isFetching && !!summaryResult
                : compute.isFetching && !!result
            }
          />
        )}

        {!result && !compute.isFetching && (
          <div className="flex flex-1 items-center justify-center rounded-xl border border-dashed border-zinc-300 p-10 text-sm text-zinc-500 dark:border-zinc-700">
            {strategy.kind === "vol" && !activeInst
              ? "Select an instrument on the left."
              : strategy.id === "counter-trend"
              ? "Computing counter-trend analysis…"
              : "Loading initial results…"}
          </div>
        )}
      </section>
    </div>
  );
}

function Card({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-4 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
      {children}
    </div>
  );
}

function ErrorNote({
  label,
  message,
}: {
  label: string;
  message: string;
}) {
  return (
    <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300">
      <span className="font-medium">{label}:</span> {message}
    </div>
  );
}

function Spinner() {
  return (
    <svg
      className="h-3 w-3 animate-spin text-zinc-500"
      viewBox="0 0 24 24"
      fill="none"
    >
      <circle
        className="opacity-25"
        cx="12"
        cy="12"
        r="10"
        stroke="currentColor"
        strokeWidth="4"
      />
      <path
        className="opacity-75"
        fill="currentColor"
        d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"
      />
    </svg>
  );
}
