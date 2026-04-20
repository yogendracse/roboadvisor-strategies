"use client";

import { useState, useMemo, useRef } from "react";
import { useQuery } from "@tanstack/react-query";

import { MetricStrip } from "@/components/strategy/MetricStrip";
import { TabContent } from "@/components/strategy/TabContent";
import { Markdown } from "@/components/ui/Markdown";
import { Tabs, type TabDef } from "@/components/ui/Tabs";
import { apiFetch } from "@/lib/api";
import type { StrategyResult } from "@/lib/strategy-compute";

// ─── Param types ──────────────────────────────────────────────────────────────

interface SimulatorParams {
  tickers: string[];
  date_start: string;
  date_end: string;
  initial_capital: number;
  weighting: "equal" | "inv_vol";
  inv_vol_window: number;
  default_system: string;
  ticker_systems: Record<string, string>;
  max_drawdown_limit: number;
  concentration_cap: number;
  tc_bps: number;
  warmup_days: number;
  sharpe_window: number;
  rebalance_freq: number;
}

const SYSTEMS = [
  "10/30 MA",
  "30/100 MA",
  "80/160 MA",
  "30-Day Breakout",
];

function defaultDates(): { start: string; end: string } {
  const end = new Date();
  const start = new Date(end);
  start.setFullYear(start.getFullYear() - 3);
  return {
    start: start.toISOString().slice(0, 10),
    end: end.toISOString().slice(0, 10),
  };
}

const { start: DEFAULT_START, end: DEFAULT_END } = defaultDates();

const DEFAULT_PARAMS: SimulatorParams = {
  tickers: ["AAPL", "MSFT", "SPY"],
  date_start: DEFAULT_START,
  date_end: DEFAULT_END,
  initial_capital: 100_000,
  weighting: "equal",
  inv_vol_window: 30,
  default_system: "30/100 MA",
  ticker_systems: {},
  max_drawdown_limit: 0.20,
  concentration_cap: 0.40,
  tc_bps: 1.0,
  warmup_days: 200,
  sharpe_window: 90,
  rebalance_freq: 5,
};

// ─── Component ────────────────────────────────────────────────────────────────

export function SimulatorWorkspace() {
  const [params, setParams] = useState<SimulatorParams>(DEFAULT_PARAMS);
  // Committed params: only sent when user clicks "Run"
  const [committed, setCommitted] = useState<SimulatorParams | null>(null);
  const [activeTabId, setActiveTabId] = useState<string | null>(null);
  const [tickerInput, setTickerInput] = useState(DEFAULT_PARAMS.tickers.join(", "));

  const update = (patch: Partial<SimulatorParams>) =>
    setParams((p) => ({ ...p, ...patch }));

  const handleRun = () => {
    // Parse tickers from the free-text input
    const parsed = tickerInput
      .split(/[\s,]+/)
      .map((t) => t.trim().toUpperCase())
      .filter(Boolean);
    const next = { ...params, tickers: parsed.length ? parsed : params.tickers };
    setParams(next);
    setCommitted(next);
    setActiveTabId(null);
  };

  const { data: result, isFetching, isError, error } = useQuery({
    queryKey: ["simulator", committed],
    queryFn: () =>
      apiFetch<StrategyResult>("/api/simulator/run", {
        method: "POST",
        body: JSON.stringify(committed),
      }),
    enabled: committed !== null,
    staleTime: 5 * 60_000,
    placeholderData: (prev) => prev,
  });

  // Default to first tab when result arrives
  const prevResultRef = useRef<StrategyResult | undefined>(undefined);
  if (result && result !== prevResultRef.current) {
    prevResultRef.current = result;
    if (!activeTabId && result.tabs?.length) {
      setActiveTabId(result.tabs[0].id);
    }
  }

  const tabDefs: TabDef[] = useMemo(
    () => result?.tabs?.map((t) => ({ id: t.id, title: t.title, icon: t.icon })) ?? [],
    [result],
  );

  const activeTab = result?.tabs?.find((t) => t.id === activeTabId) ?? null;

  return (
    <div className="flex flex-1 gap-4 p-4">
      {/* ── Sidebar ─────────────────────────────────────────────────────────── */}
      <aside className="flex w-72 shrink-0 flex-col gap-4">
        <div className="flex flex-col gap-3 rounded-xl border border-zinc-200 bg-white p-4 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
          <h3 className="text-sm font-semibold uppercase tracking-wide text-zinc-500">
            Simulation Parameters
          </h3>

          {/* Tickers */}
          <label className="block">
            <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-zinc-500">
              Tickers (comma-separated)
            </span>
            <input
              type="text"
              value={tickerInput}
              onChange={(e) => setTickerInput(e.target.value)}
              placeholder="AAPL, MSFT, SPY"
              className="block w-full rounded-md border border-zinc-300 bg-white px-2.5 py-1.5 text-sm text-zinc-900 focus:border-zinc-500 focus:outline-none dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-100"
            />
            <p className="mt-1 text-[11px] text-zinc-500">
              Yahoo Finance tickers. Data fetched at run time.
            </p>
          </label>

          {/* Date range */}
          <div>
            <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-zinc-500">
              Date Range
            </span>
            <div className="flex items-center gap-1.5">
              <input
                type="date"
                value={params.date_start}
                max={params.date_end}
                onChange={(e) => update({ date_start: e.target.value })}
                className={dateInput}
              />
              <span className="text-xs text-zinc-400">→</span>
              <input
                type="date"
                value={params.date_end}
                min={params.date_start}
                onChange={(e) => update({ date_end: e.target.value })}
                className={dateInput}
              />
            </div>
          </div>

          {/* Capital */}
          <SliderField
            label="Initial Capital ($)"
            value={params.initial_capital}
            min={10_000}
            max={10_000_000}
            step={10_000}
            format={(v) => `$${v.toLocaleString()}`}
            onChange={(v) => update({ initial_capital: v })}
          />

          {/* Weighting */}
          <label className="block">
            <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-zinc-500">
              Portfolio Weighting
            </span>
            <select
              value={params.weighting}
              onChange={(e) => update({ weighting: e.target.value as "equal" | "inv_vol" })}
              className={selectCls}
            >
              <option value="equal">Equal Weight (1/N)</option>
              <option value="inv_vol">Inverse Volatility</option>
            </select>
          </label>

          {params.weighting === "inv_vol" && (
            <SliderField
              label="Inv-Vol lookback (days)"
              value={params.inv_vol_window}
              min={5}
              max={120}
              step={5}
              onChange={(v) => update({ inv_vol_window: v })}
            />
          )}

          {/* System */}
          <label className="block">
            <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-zinc-500">
              Default System
            </span>
            <select
              value={params.default_system}
              onChange={(e) => update({ default_system: e.target.value })}
              className={selectCls}
            >
              {SYSTEMS.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
            <p className="mt-1 text-[11px] text-zinc-500">
              Applied to all tickers unless overridden below.
            </p>
          </label>

          {/* Guardrails */}
          <div className="rounded-lg border border-zinc-200 bg-zinc-50 p-2.5 dark:border-zinc-800 dark:bg-zinc-950/40 space-y-3">
            <div className="text-[11px] font-medium uppercase tracking-wide text-zinc-500">
              Guardrails
            </div>
            <SliderField
              label="Circuit-breaker (max DD)"
              value={params.max_drawdown_limit}
              min={0.05}
              max={1.0}
              step={0.01}
              format={(v) => `${(v * 100).toFixed(0)}%`}
              onChange={(v) => update({ max_drawdown_limit: v })}
            />
            <SliderField
              label="Concentration cap"
              value={params.concentration_cap}
              min={0.1}
              max={1.0}
              step={0.05}
              format={(v) => `${(v * 100).toFixed(0)}%`}
              onChange={(v) => update({ concentration_cap: v })}
            />
            <SliderField
              label="Transaction cost (bps)"
              value={params.tc_bps}
              min={0}
              max={20}
              step={0.5}
              onChange={(v) => update({ tc_bps: v })}
            />
          </div>

          {/* Advanced */}
          <div className="rounded-lg border border-zinc-200 bg-zinc-50 p-2.5 dark:border-zinc-800 dark:bg-zinc-950/40 space-y-3">
            <div className="text-[11px] font-medium uppercase tracking-wide text-zinc-500">
              Advanced
            </div>
            <SliderField
              label="Warmup period (days)"
              value={params.warmup_days}
              min={50}
              max={500}
              step={10}
              onChange={(v) => update({ warmup_days: v })}
            />
            <SliderField
              label="Rolling Sharpe window (days)"
              value={params.sharpe_window}
              min={20}
              max={252}
              step={5}
              onChange={(v) => update({ sharpe_window: v })}
            />
            <SliderField
              label="Rebalance every N days"
              value={params.rebalance_freq}
              min={1}
              max={20}
              step={1}
              onChange={(v) => update({ rebalance_freq: v })}
            />
          </div>

          {/* Run button */}
          <button
            onClick={handleRun}
            disabled={isFetching}
            className="mt-1 flex items-center justify-center gap-2 rounded-lg bg-zinc-900 px-4 py-2 text-sm font-semibold text-white transition hover:bg-zinc-700 disabled:opacity-60 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-300"
          >
            {isFetching ? (
              <>
                <Spinner /> Running…
              </>
            ) : (
              "Run Simulation"
            )}
          </button>
          {isFetching && (
            <p className="text-center text-[11px] text-zinc-500">
              Fetching live data + simulating — may take 10–30 s
            </p>
          )}
        </div>
      </aside>

      {/* ── Main area ─────────────────────────────────────────────────────────── */}
      <section className="flex min-w-0 flex-1 flex-col gap-4 overflow-hidden">
        <header className="rounded-xl border border-zinc-200 bg-white p-4 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
          <h2 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">
            Simulation Engine
          </h2>
          <p className="text-sm text-zinc-600 dark:text-zinc-400">
            Sequential portfolio simulator — no lookahead bias. Configure tickers and
            parameters, then click{" "}
            <span className="font-medium text-zinc-900 dark:text-zinc-50">
              Run Simulation
            </span>
            .
          </p>
        </header>

        {isError && (
          <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300">
            <span className="font-medium">Simulation failed:</span>{" "}
            {error instanceof Error ? error.message : String(error)}
          </div>
        )}

        {result?.warnings?.map((w, i) => (
          <div
            key={i}
            className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-300"
          >
            {w}
          </div>
        ))}

        {result?.overview_md && (
          <div className="rounded-xl border border-zinc-200 bg-white p-4 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
            <Markdown>{result.overview_md}</Markdown>
          </div>
        )}

        {result && (result.metrics?.length ?? 0) > 0 && (
          <MetricStrip metrics={result.metrics ?? []} />
        )}

        {tabDefs.length > 0 && (
          <Tabs
            tabs={tabDefs}
            active={activeTabId ?? tabDefs[0].id}
            onChange={setActiveTabId}
          />
        )}

        {activeTab && (
          <TabContent tab={activeTab} isStale={isFetching && !!result} />
        )}

        {!committed && !isFetching && (
          <div className="flex flex-1 items-center justify-center rounded-xl border border-dashed border-zinc-300 p-10 text-sm text-zinc-500 dark:border-zinc-700">
            Configure your portfolio above and click{" "}
            <strong className="mx-1 text-zinc-700 dark:text-zinc-300">
              Run Simulation
            </strong>{" "}
            to start.
          </div>
        )}
      </section>
    </div>
  );
}

// ─── Small helpers ────────────────────────────────────────────────────────────

const dateInput =
  "w-full rounded-md border border-zinc-300 bg-white px-2 py-1 text-xs text-zinc-900 focus:border-zinc-500 focus:outline-none dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-100";

const selectCls =
  "block w-full rounded-md border border-zinc-300 bg-white px-2.5 py-1.5 text-sm text-zinc-900 focus:border-zinc-500 focus:outline-none dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-100";

interface SliderFieldProps {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  format?: (v: number) => string;
  onChange: (v: number) => void;
}

function SliderField({ label, value, min, max, step, format, onChange }: SliderFieldProps) {
  const display = format ? format(value) : String(value);
  return (
    <label className="block">
      <div className="flex items-baseline justify-between">
        <span className="text-xs font-medium uppercase tracking-wide text-zinc-500">
          {label}
        </span>
        <span className="font-mono text-xs text-zinc-700 dark:text-zinc-300">{display}</span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="mt-1.5 w-full accent-zinc-900 dark:accent-zinc-100"
      />
    </label>
  );
}

function Spinner() {
  return (
    <svg className="h-3 w-3 animate-spin" viewBox="0 0 24 24" fill="none">
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path
        className="opacity-75"
        fill="currentColor"
        d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"
      />
    </svg>
  );
}
