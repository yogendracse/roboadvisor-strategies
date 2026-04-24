"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import { useDebouncedValue } from "@/lib/use-debounced-value";
import { PlotlyChart } from "@/components/charts/PlotlyChart";

// ─── Types ────────────────────────────────────────────────────────────────────

type Tab = "overview" | "portfolio" | "signals" | "backtest";

interface Milestone {
  id: string;
  label: string;
  description: string;
  status: "done" | "in-progress" | "planned";
}

interface RecommendResponse {
  weights: Record<string, number>;
  dollar_amounts: Record<string, number>;
  share_counts: Record<string, number>;
  strategy_mix: Record<string, number>;
  meta: { universe_size: number; as_of_date: string; risk_profile: string };
}

interface BtMetrics {
  total_return: number; cagr: number; volatility: number; sharpe: number;
  sortino: number; max_drawdown: number; max_drawdown_duration_days: number;
  calmar: number; var_95: number; cvar_95: number;
}
interface BtBench { metrics: BtMetrics }
interface OverlayAttribution {
  core_return: number;
  overlay_return: number;
  total_return: number;
  overlay_sharpe_contribution: number;
}
interface BtResponse {
  metrics: BtMetrics;
  benchmarks: { spy: BtBench; sixty_forty: BtBench; equal_weight: BtBench };
  trades_summary: { total_trades: number; total_cost_dollars: number; turnover_annualized: number };
  trades: { date: string; ticker: string; delta_weight: number; price: number; cost_dollars: number }[];
  equity_figure: unknown;
  drawdown_figure: unknown;
  attribution: OverlayAttribution;
  core_equity_curve?: { date: string; value: number }[] | null;
  overlay_equity_curve?: { date: string; value: number }[] | null;
  warnings?: string[];
  meta: Record<string, unknown>;
}

interface OverlaySignalSnapshot {
  value: number;
  baseline: number;
  deviation: number;
  z: number;
  rolling_mean: number;
  rolling_std: number;
  source: string;
  confidence: number;
  as_of_date: string;
}

interface OverlayPreviewResponse {
  core_weights: Record<string, number>;
  signals: Record<string, OverlaySignalSnapshot>;
  raw_tilts: Record<string, number>;
  tilts: Record<string, number>;
  active_circuit_breakers: string[];
  final_weights: Record<string, number>;
  overlay_budget_used: number;
  overlay_budget_limit: number;
  warnings: string[];
}

// ─── Data ─────────────────────────────────────────────────────────────────────

const MILESTONES: Milestone[] = [
  {
    id: "M1",
    label: "Data Pipeline",
    description: "yfinance loader + Polymarket API client + FRED macro + local CSV storage",
    status: "done",
  },
  {
    id: "M2",
    label: "Core Strategies",
    description: "Mean-Variance Optimization (Ledoit-Wolf) + Risk Parity with unit tests",
    status: "done",
  },
  {
    id: "M3",
    label: "Factor Model",
    description: "Fama-French 3-factor + Momentum for the equity sleeve",
    status: "planned",
  },
  {
    id: "M4",
    label: "Strategy Blender",
    description: "Configurable strategy mix → target portfolio weights + share counts",
    status: "planned",
  },
  {
    id: "M5",
    label: "Backtesting Engine",
    description: "Walk-forward, transaction costs (5 bps), full metrics suite",
    status: "done",
  },
  {
    id: "M6",
    label: "Overlay Engine",
    description: "Polymarket signal ingestion, sensitivity mapping, de-risk / re-risk rules",
    status: "in-progress",
  },
  {
    id: "M7",
    label: "Risk Management",
    description: "Calendar + threshold rebalancing, -15% drawdown circuit breaker",
    status: "planned",
  },
  {
    id: "M8",
    label: "UI Dashboard",
    description: "Risk profile questionnaire, equity curve, signal panel, trade list",
    status: "planned",
  },
  {
    id: "M9",
    label: "Validation",
    description: "Full 2015–present backtest: overlay on vs. off vs. 60/40 vs. SPY",
    status: "planned",
  },
];

const SIGNAL_LABELS: Record<string, string> = {
  recession_prob: "Recession Probability",
  fed_cuts_expected: "Fed Cuts Expected",
  sp500_close_expected: "S&P 500 Close Expected",
};

const STRATEGY_LABELS: Record<string, string> = {
  mvo: "Mean-Variance Optimization",
  risk_parity: "Risk Parity",
};

const STRATEGY_COLORS: Record<string, string> = {
  mvo: "bg-violet-500",
  risk_parity: "bg-sky-500",
};

// ─── Sub-components ───────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: Milestone["status"] }) {
  const map = {
    done:          "bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300",
    "in-progress": "bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300",
    planned:       "bg-zinc-100 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400",
  } as const;
  const label = { done: "Done", "in-progress": "In Progress", planned: "Planned" } as const;
  return (
    <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${map[status]}`}>
      {label[status]}
    </span>
  );
}


// ─── Tabs ─────────────────────────────────────────────────────────────────────

function OverviewTab() {
  return (
    <div className="space-y-8">
      {/* Architecture diagram */}
      <section>
        <h3 className="mb-3 text-sm font-semibold text-zinc-700 dark:text-zinc-300">System Architecture</h3>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          {[
            {
              title: "Data Layer",
              items: ["yfinance daily OHLCV", "Polymarket API (prediction markets)", "FRED macro series", "CSV local cache"],
              color: "border-sky-200 dark:border-sky-800",
              dot: "bg-sky-400",
            },
            {
              title: "Strategy Engine",
              items: ["MVO (Ledoit-Wolf shrinkage)", "Risk Parity (inv-vol)", "Factor Model (FF3 + Mom) — M3", "Strategy Blender (config-driven)"],
              color: "border-violet-200 dark:border-violet-800",
              dot: "bg-violet-400",
            },
            {
              title: "Overlay + Portfolio",
              items: ["Prediction market signal ingestion", "Sensitivity mapping (YAML config)", "De-risk / re-risk rules", "Circuit breakers + rebalancing"],
              color: "border-emerald-200 dark:border-emerald-800",
              dot: "bg-emerald-400",
            },
          ].map((block) => (
            <div key={block.title} className={`rounded-xl border ${block.color} bg-white p-4 dark:bg-zinc-900`}>
              <div className="flex items-center gap-2 mb-3">
                <span className={`h-2 w-2 rounded-full ${block.dot}`} />
                <span className="text-sm font-medium text-zinc-900 dark:text-zinc-50">{block.title}</span>
              </div>
              <ul className="space-y-1">
                {block.items.map((item) => (
                  <li key={item} className="text-xs text-zinc-500 dark:text-zinc-400">• {item}</li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </section>

      {/* Milestones */}
      <section>
        <h3 className="mb-3 text-sm font-semibold text-zinc-700 dark:text-zinc-300">Build Milestones</h3>
        <div className="divide-y divide-zinc-100 dark:divide-zinc-800 rounded-xl border border-zinc-200 dark:border-zinc-800 overflow-hidden">
          {MILESTONES.map((m) => (
            <div key={m.id} className="flex items-start gap-4 bg-white dark:bg-zinc-900 px-4 py-3">
              <span className="w-8 shrink-0 text-xs font-mono font-semibold text-zinc-400 dark:text-zinc-500 mt-0.5">{m.id}</span>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-sm font-medium text-zinc-900 dark:text-zinc-50">{m.label}</span>
                  <StatusBadge status={m.status} />
                </div>
                <p className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">{m.description}</p>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* Key formula */}
      <section>
        <h3 className="mb-3 text-sm font-semibold text-zinc-700 dark:text-zinc-300">Core Overlay Formula</h3>
        <div className="rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-4">
          <code className="block text-sm font-mono text-violet-700 dark:text-violet-300 mb-2">
            tilt_i = sensitivity_i × (P_market − P_baseline)
          </code>
          <p className="text-xs text-zinc-500 dark:text-zinc-400">
            Where <code className="font-mono">P_market</code> is the current Polymarket probability and{" "}
            <code className="font-mono">P_baseline</code> is the trailing 90-day rolling median.
            Total deviation is capped at ±20% per asset and the full overlay budget is capped at 30%.
            De-risking requires both a recession spike and a confirming VIX z-score.
          </p>
        </div>
      </section>
    </div>
  );
}

function PortfolioTab() {
  const [riskProfile, setRiskProfile] = useState<"conservative" | "balanced" | "aggressive">("balanced");
  const [capital, setCapital] = useState("100000");
  const [asOfDate, setAsOfDate] = useState("2026-04-23");
  const debouncedCapital = useDebouncedValue(capital, 600);
  const capitalNum = Math.max(0, parseFloat(debouncedCapital) || 0);

  const { data, isLoading, isError } = useQuery({
    queryKey: ["robo-recommend", riskProfile, capitalNum, asOfDate],
    queryFn: () =>
      apiFetch<RecommendResponse>("/api/robo-advisor/portfolio/recommend", {
        method: "POST",
        body: JSON.stringify({ risk_profile: riskProfile, capital: capitalNum, as_of_date: asOfDate }),
      }),
    enabled: capitalNum > 0,
    staleTime: 5 * 60 * 1000,
  });

  const overlayPreview = useQuery({
    queryKey: ["robo-overlay-preview", riskProfile, asOfDate],
    queryFn: () =>
      apiFetch<OverlayPreviewResponse>("/api/robo-advisor/overlay/preview", {
        method: "POST",
        body: JSON.stringify({ risk_profile: riskProfile, as_of_date: asOfDate }),
      }),
    staleTime: 60 * 1000,
  });

  const profileDescriptions = {
    conservative: "MVO 30 / RP 70",
    balanced:     "MVO 50 / RP 50",
    aggressive:   "MVO 70 / RP 30",
  };

  const weightRows = Object.keys(overlayPreview.data?.final_weights ?? data?.weights ?? {})
    .sort((a, b) => (overlayPreview.data?.final_weights?.[b] ?? data?.weights?.[b] ?? 0) - (overlayPreview.data?.final_weights?.[a] ?? data?.weights?.[a] ?? 0));

  return (
    <div className="space-y-6">
      {/* Risk profile */}
      <section>
        <h3 className="mb-3 text-sm font-semibold text-zinc-700 dark:text-zinc-300">Risk Profile</h3>
        <div className="grid grid-cols-3 gap-3">
          {(["conservative", "balanced", "aggressive"] as const).map((p) => (
            <button
              key={p}
              onClick={() => setRiskProfile(p)}
              className={`rounded-lg border p-3 text-left transition ${
                riskProfile === p
                  ? "border-zinc-900 bg-zinc-900 text-white dark:border-zinc-50 dark:bg-zinc-50 dark:text-zinc-900"
                  : "border-zinc-200 bg-white text-zinc-700 hover:border-zinc-400 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-300 dark:hover:border-zinc-600"
              }`}
            >
              <div className="text-sm font-medium capitalize">{p}</div>
              <div className="mt-0.5 text-xs opacity-60">{profileDescriptions[p]}</div>
            </button>
          ))}
        </div>
      </section>

      {/* Capital */}
      <section>
        <h3 className="mb-3 text-sm font-semibold text-zinc-700 dark:text-zinc-300">Capital</h3>
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-sm text-zinc-500">$</span>
          <input
            type="number"
            value={capital}
            onChange={(e) => setCapital(e.target.value)}
            className="w-40 rounded-lg border border-zinc-200 bg-white px-3 py-1.5 text-sm text-zinc-900 focus:border-zinc-900 focus:outline-none dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50 dark:focus:border-zinc-400"
          />
          <input
            type="date"
            value={asOfDate}
            onChange={(e) => setAsOfDate(e.target.value)}
            className="rounded-lg border border-zinc-200 bg-white px-3 py-1.5 text-sm text-zinc-900 focus:border-zinc-900 focus:outline-none dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50 dark:focus:border-zinc-400"
          />
        </div>
      </section>

      {/* Strategy mix */}
      <section>
        <h3 className="mb-3 text-sm font-semibold text-zinc-700 dark:text-zinc-300">
          Strategy Mix — <span className="text-zinc-500 font-normal capitalize">{riskProfile}</span>
        </h3>
        <div className="space-y-2">
          {Object.entries(data?.strategy_mix ?? {}).map(([id, weight]) => (
            <div key={id} className="flex items-center gap-3">
              <span className="w-48 text-xs text-zinc-600 dark:text-zinc-400 shrink-0">
                {STRATEGY_LABELS[id] ?? id}
              </span>
              <div className="flex-1 h-2 rounded-full bg-zinc-100 dark:bg-zinc-800 overflow-hidden">
                <div
                  className={`h-full rounded-full transition-all duration-300 ${STRATEGY_COLORS[id] ?? "bg-zinc-400"}`}
                  style={{ width: `${weight * 100}%` }}
                />
              </div>
              <span className="w-10 text-right text-xs font-mono text-zinc-700 dark:text-zinc-300">
                {(weight * 100).toFixed(0)}%
              </span>
            </div>
          ))}
          {!data && (
            // Static preview while loading
            [
              { id: "mvo",          pct: riskProfile === "conservative" ? 30 : riskProfile === "balanced" ? 50 : 70 },
              { id: "risk_parity",  pct: riskProfile === "conservative" ? 70 : riskProfile === "balanced" ? 50 : 30 },
            ].map(({ id, pct }) => (
              <div key={id} className="flex items-center gap-3">
                <span className="w-48 text-xs text-zinc-600 dark:text-zinc-400 shrink-0">
                  {STRATEGY_LABELS[id]}
                </span>
                <div className="flex-1 h-2 rounded-full bg-zinc-100 dark:bg-zinc-800 overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all duration-300 ${STRATEGY_COLORS[id]}`}
                    style={{ width: `${pct}%` }}
                  />
                </div>
                <span className="w-10 text-right text-xs font-mono text-zinc-700 dark:text-zinc-300">{pct}%</span>
              </div>
            ))
          )}
        </div>
      </section>

      {/* Target allocation */}
      <section>
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold text-zinc-700 dark:text-zinc-300">Core vs Final Allocation</h3>
          {data && (
            <span className="text-[10px] text-zinc-400 dark:text-zinc-500">
              as of {data.meta.as_of_date}
            </span>
          )}
        </div>

        {isError && (
          <div className="rounded-xl border border-rose-200 dark:border-rose-900 bg-rose-50 dark:bg-rose-950/30 px-4 py-3 text-xs text-rose-600 dark:text-rose-400">
            Could not compute portfolio — ensure price data is loaded (POST /api/robo-advisor/refresh/prices).
          </div>
        )}

        {isLoading && (
          <div className="divide-y divide-zinc-100 dark:divide-zinc-800 rounded-xl border border-zinc-200 dark:border-zinc-800 overflow-hidden">
            {Array.from({ length: 8 }).map((_, i) => (
              <div key={i} className="flex items-center gap-3 bg-white dark:bg-zinc-900 px-4 py-2.5 animate-pulse">
                <div className="h-3 w-10 rounded bg-zinc-200 dark:bg-zinc-700" />
                <div className="flex-1 h-1.5 rounded-full bg-zinc-200 dark:bg-zinc-700" />
                <div className="h-3 w-12 rounded bg-zinc-200 dark:bg-zinc-700" />
              </div>
            ))}
          </div>
        )}

        {data && overlayPreview.data && (
          <div className="divide-y divide-zinc-100 dark:divide-zinc-800 rounded-xl border border-zinc-200 dark:border-zinc-800 overflow-hidden">
            {weightRows.map((ticker) => {
              const coreWeight = data.weights[ticker] ?? overlayPreview.data.core_weights[ticker] ?? 0;
              const finalWeight = overlayPreview.data.final_weights[ticker] ?? coreWeight;
              const tilt = overlayPreview.data.tilts[ticker] ?? 0;
              return (
                <div key={ticker} className="bg-white dark:bg-zinc-900 px-4 py-3">
                  <div className="flex items-center gap-3">
                    <span className="w-14 text-xs font-mono font-semibold text-zinc-900 dark:text-zinc-50">{ticker}</span>
                    <div className="w-24 h-1.5 rounded-full bg-zinc-100 dark:bg-zinc-800 overflow-hidden">
                      <div
                        className="h-full bg-zinc-400 rounded-full"
                        style={{ width: `${Math.min(coreWeight * 400, 100)}%` }}
                      />
                    </div>
                    <span className="w-14 text-right text-xs font-mono text-zinc-500 dark:text-zinc-400">
                      {(coreWeight * 100).toFixed(1)}%
                    </span>
                    <div className="w-24 h-1.5 rounded-full bg-zinc-100 dark:bg-zinc-800 overflow-hidden">
                      <div
                        className={`h-full rounded-full ${tilt >= 0 ? "bg-emerald-400" : "bg-rose-400"}`}
                        style={{ width: `${Math.min(finalWeight * 400, 100)}%` }}
                      />
                    </div>
                    <span className="w-14 text-right text-xs font-mono text-zinc-900 dark:text-zinc-50">
                      {(finalWeight * 100).toFixed(1)}%
                    </span>
                    <span className={`w-14 text-right text-xs font-mono ${tilt >= 0 ? "text-emerald-600" : "text-rose-600"}`}>
                      {tilt >= 0 ? "+" : ""}{(tilt * 100).toFixed(1)}%
                    </span>
                    <span className="flex-1 text-right text-xs text-zinc-500 dark:text-zinc-400">
                      ${((finalWeight * capitalNum) || 0).toLocaleString("en-US", { maximumFractionDigits: 0 })}
                    </span>
                  </div>
                  <details className="mt-2">
                    <summary className="cursor-pointer text-[11px] text-zinc-500">Why this tilt?</summary>
                    <div className="mt-2 flex flex-wrap gap-2 text-[11px] text-zinc-500">
                      {Object.entries(overlayPreview.data.signals).map(([signalName, signal]) => (
                        <span key={signalName} className="rounded bg-zinc-100 px-2 py-1 dark:bg-zinc-800">
                          {SIGNAL_LABELS[signalName] ?? signalName}: {signal.value.toFixed(2)} vs {signal.baseline.toFixed(2)} ({signal.deviation >= 0 ? "+" : ""}{signal.deviation.toFixed(2)})
                        </span>
                      ))}
                    </div>
                  </details>
                </div>
              );
            })}
            <div className="grid grid-cols-2 gap-3 bg-zinc-50 dark:bg-zinc-800/50 px-4 py-3 text-xs text-zinc-500">
              <div>Core total: {(Object.values(data.weights).reduce((a, b) => a + b, 0) * 100).toFixed(1)}%</div>
              <div className="text-right">Final total: {(Object.values(overlayPreview.data.final_weights).reduce((a, b) => a + b, 0) * 100).toFixed(1)}%</div>
            </div>
          </div>
        )}

        {!overlayPreview.isLoading && overlayPreview.data && (
          <div className="rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-900 px-4 py-3 text-xs text-zinc-500">
            Overlay budget: {(overlayPreview.data.overlay_budget_used * 100).toFixed(1)}% of {(overlayPreview.data.overlay_budget_limit * 100).toFixed(0)}% used.
            {overlayPreview.data.active_circuit_breakers.length > 0 && (
              <span className="ml-2 text-zinc-700 dark:text-zinc-300">
                Active: {overlayPreview.data.active_circuit_breakers.join(", ")}
              </span>
            )}
          </div>
        )}

        {!data && !isLoading && !isError && (
          <div className="divide-y divide-zinc-100 dark:divide-zinc-800 rounded-xl border border-zinc-200 dark:border-zinc-800 overflow-hidden opacity-40">
            {["SPY", "QQQ", "TLT", "IEF", "GLD", "DBC", "VNQ", "VXUS"].map((ticker) => (
              <div key={ticker} className="flex items-center gap-3 bg-white dark:bg-zinc-900 px-4 py-2.5">
                <span className="w-14 text-xs font-mono font-semibold text-zinc-900 dark:text-zinc-50">{ticker}</span>
                <div className="w-24 h-1.5 rounded-full bg-zinc-100 dark:bg-zinc-800" />
                <span className="w-12 text-right text-xs font-mono text-zinc-400">—</span>
                <div className="w-24 h-1.5 rounded-full bg-zinc-100 dark:bg-zinc-800" />
                <span className="w-12 text-right text-xs font-mono text-zinc-400">—</span>
                <span className="w-16 text-right text-xs font-mono text-zinc-400">—</span>
                <span className="flex-1 text-right text-xs text-zinc-400">—</span>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

function SignalsTab() {
  const [riskProfile, setRiskProfile] = useState<"conservative" | "balanced" | "aggressive">("balanced");
  const [asOfDate, setAsOfDate] = useState("2026-04-23");
  const { data, isLoading, isError } = useQuery({
    queryKey: ["overlay-signals-tab", riskProfile, asOfDate],
    queryFn: () =>
      apiFetch<OverlayPreviewResponse>("/api/robo-advisor/overlay/preview", {
        method: "POST",
        body: JSON.stringify({ risk_profile: riskProfile, as_of_date: asOfDate }),
      }),
    staleTime: 60 * 1000,
  });

  const tiltRows = Object.keys(data?.tilts ?? {})
    .map((asset) => ({
      asset,
      activeTilt: data?.tilts?.[asset] ?? 0,
      rawTilt: data?.raw_tilts?.[asset] ?? 0,
    }))
    .sort((a, b) => Math.abs(b.rawTilt) - Math.abs(a.rawTilt));

  return (
    <div className="space-y-6">
      <section className="grid grid-cols-1 gap-3 md:grid-cols-3">
        <select value={riskProfile} onChange={(e) => setRiskProfile(e.target.value as typeof riskProfile)}
          className="rounded-lg border border-zinc-200 bg-white px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50">
          <option value="conservative">Conservative</option>
          <option value="balanced">Balanced</option>
          <option value="aggressive">Aggressive</option>
        </select>
        <input type="date" value={asOfDate} onChange={(e) => setAsOfDate(e.target.value)}
          className="rounded-lg border border-zinc-200 bg-white px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50" />
        {data && (
          <div className="rounded-lg border border-zinc-200 bg-white px-3 py-2 text-sm text-zinc-600 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-300">
            Overlay budget: {(data.overlay_budget_used * 100).toFixed(1)}% / {(data.overlay_budget_limit * 100).toFixed(0)}%
          </div>
        )}
      </section>

      <section>
        <h3 className="mb-3 text-sm font-semibold text-zinc-700 dark:text-zinc-300">
          Active Prediction Market Signals
        </h3>
        {isError && <p className="text-xs text-rose-500">Could not load overlay preview.</p>}
        {isLoading && <p className="text-xs text-zinc-500">Loading current overlay state…</p>}
        <div className="space-y-4">
          {Object.entries(data?.signals ?? {}).map(([signalName, signal]) => {
            const absDelta = Math.abs(signal.deviation);
            const isElevated = signal.deviation > 0;
            return (
              <div key={signalName} className="rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-4">
                <div className="flex items-start justify-between gap-4 mb-3">
                  <div>
                    <span className="text-sm font-medium text-zinc-900 dark:text-zinc-50">{SIGNAL_LABELS[signalName] ?? signalName}</span>
                    <div className="mt-0.5 flex items-center gap-2">
                      <span className="text-xs text-zinc-500">Baseline: {signal.baseline.toFixed(2)}</span>
                      <span className={`text-xs font-medium ${isElevated ? "text-rose-600" : "text-emerald-600"}`}>
                        {isElevated ? "▲" : "▼"} {absDelta.toFixed(2)} vs baseline
                      </span>
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="text-2xl font-bold tabular-nums text-zinc-900 dark:text-zinc-50">
                      {signal.value.toFixed(2)}
                    </div>
                    <div className="text-[11px] text-zinc-500">z = {signal.z.toFixed(2)} · {signal.source}</div>
                  </div>
                </div>
                <div className="h-2 rounded-full bg-zinc-100 dark:bg-zinc-800 overflow-hidden mb-3">
                  <div
                    className={`h-full rounded-full transition-all ${isElevated ? "bg-rose-400" : "bg-emerald-400"}`}
                    style={{ width: `${Math.min(Math.abs(signal.z) * 22, 100)}%` }}
                  />
                </div>
                <div className="text-[11px] text-zinc-500">
                  Rolling mean {signal.rolling_mean.toFixed(2)} · rolling std {signal.rolling_std.toFixed(2)} · confidence {(signal.confidence * 100).toFixed(0)}%
                </div>
              </div>
            );
          })}
        </div>
      </section>

      <section>
        <h3 className="mb-3 text-sm font-semibold text-zinc-700 dark:text-zinc-300">Active Tilts</h3>
        <div className="space-y-3 rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-4">
          {tiltRows.map(({ asset, activeTilt, rawTilt }) => (
            <div key={asset} className="flex items-center gap-3">
              <span className="w-14 text-xs font-mono font-semibold text-zinc-900 dark:text-zinc-50">{asset}</span>
              <div className="flex-1 h-3 rounded-full bg-zinc-100 dark:bg-zinc-800 overflow-hidden">
                <div
                  className={`h-full rounded-full ${activeTilt >= 0 ? "bg-emerald-400" : "bg-rose-400"}`}
                  style={{ width: `${Math.min(Math.abs(activeTilt) / 0.2 * 100, 100)}%` }}
                />
              </div>
              <span className={`w-16 text-right text-xs font-mono ${activeTilt >= 0 ? "text-emerald-600" : "text-rose-600"}`}>
                {activeTilt >= 0 ? "+" : ""}{(activeTilt * 100).toFixed(1)}%
              </span>
              <span className="w-28 text-right text-[11px] text-zinc-500">
                raw {rawTilt >= 0 ? "+" : ""}{(rawTilt * 100).toFixed(1)}%
              </span>
            </div>
          ))}
          {data && data.active_circuit_breakers.length > 0 && (
            <div className="flex flex-wrap gap-2 pt-2">
              {data.active_circuit_breakers.map((breaker) => (
                <span key={breaker} className="rounded-full bg-amber-100 px-2 py-1 text-[11px] font-semibold text-amber-700 dark:bg-amber-950 dark:text-amber-300">
                  {breaker}
                </span>
              ))}
            </div>
          )}
          {data?.warnings?.length ? (
            <div className="space-y-1 pt-2 text-[11px] text-amber-600 dark:text-amber-300">
              {data.warnings.map((warning) => <div key={warning}>{warning}</div>)}
            </div>
          ) : null}
          {data?.active_circuit_breakers.includes("awaiting_derisk_confirmation") && (
            <div className="pt-2 text-[11px] text-zinc-500">
              Raw tilts exist, but the overlay is held at neutral until recession risk is confirmed by the VIX rule.
            </div>
          )}
        </div>
      </section>
    </div>
  );
}

function BacktestTab() {
  const [profile, setProfile] = useState<"conservative"|"balanced"|"aggressive">("balanced");
  const [startDate, setStartDate] = useState("2015-01-01");
  const [endDate, setEndDate] = useState("2026-04-01");
  const [freq, setFreq] = useState<"monthly"|"quarterly"|"weekly">("monthly");
  const [useOverlay, setUseOverlay] = useState(false);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<BtResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function runBacktest() {
    setRunning(true); setError(null);
    try {
      const res = await apiFetch<BtResponse>("/api/robo-advisor/backtest/run", {
        method: "POST",
        body: JSON.stringify({ risk_profile: profile, start_date: startDate, end_date: endDate,
          initial_capital: 100000, rebalance_freq: freq, use_overlay: useOverlay }),
      });
      setResult(res);
    } catch (e) { setError(e instanceof Error ? e.message : "Backtest failed"); }
    finally { setRunning(false); }
  }

  const fmtPct  = (v: number) => `${(v * 100).toFixed(2)}%`;
  const fmtNum  = (v: number) => v.toFixed(3);
  const fmtDays = (v: number) => `${Math.round(v)}d`;

  const METRIC_ROWS: { key: keyof BtMetrics; label: string; fmt: (v:number)=>string }[] = [
    { key: "cagr",         label: "CAGR",         fmt: fmtPct },
    { key: "total_return", label: "Total Return",  fmt: fmtPct },
    { key: "sharpe",       label: "Sharpe",        fmt: fmtNum },
    { key: "sortino",      label: "Sortino",       fmt: fmtNum },
    { key: "calmar",       label: "Calmar",        fmt: fmtNum },
    { key: "volatility",   label: "Volatility",    fmt: fmtPct },
    { key: "max_drawdown", label: "Max Drawdown",  fmt: fmtPct },
    { key: "max_drawdown_duration_days", label: "DD Duration", fmt: fmtDays },
    { key: "var_95",       label: "VaR 95%",       fmt: fmtPct },
    { key: "cvar_95",      label: "CVaR 95%",      fmt: fmtPct },
  ];

  const COLS = [
    { id: "portfolio",    label: "Portfolio",     m: result?.metrics },
    { id: "spy",         label: "SPY B&H",       m: result?.benchmarks.spy.metrics },
    { id: "sixty_forty", label: "60/40",         m: result?.benchmarks.sixty_forty.metrics },
    { id: "equal_weight",label: "Equal Weight",  m: result?.benchmarks.equal_weight.metrics },
  ];

  return (
    <div className="space-y-6">
      {/* Config */}
      <section>
        <h3 className="mb-3 text-sm font-semibold text-zinc-700 dark:text-zinc-300">Backtest Parameters</h3>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-5 items-end">
          <div>
            <label className="text-[11px] text-zinc-500 mb-1 block">Profile</label>
            <select value={profile} onChange={e => setProfile(e.target.value as typeof profile)}
              className="w-full rounded-lg border border-zinc-200 bg-white px-2 py-1.5 text-sm dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50">
              <option value="conservative">Conservative</option>
              <option value="balanced">Balanced</option>
              <option value="aggressive">Aggressive</option>
            </select>
          </div>
          <div>
            <label className="text-[11px] text-zinc-500 mb-1 block">Start</label>
            <input type="date" value={startDate} onChange={e=>setStartDate(e.target.value)}
              className="w-full rounded-lg border border-zinc-200 bg-white px-2 py-1.5 text-sm dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"/>
          </div>
          <div>
            <label className="text-[11px] text-zinc-500 mb-1 block">End</label>
            <input type="date" value={endDate} onChange={e=>setEndDate(e.target.value)}
              className="w-full rounded-lg border border-zinc-200 bg-white px-2 py-1.5 text-sm dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"/>
          </div>
          <div>
            <label className="text-[11px] text-zinc-500 mb-1 block">Rebalance</label>
            <select value={freq} onChange={e=>setFreq(e.target.value as typeof freq)}
              className="w-full rounded-lg border border-zinc-200 bg-white px-2 py-1.5 text-sm dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50">
              <option value="monthly">Monthly</option>
              <option value="quarterly">Quarterly</option>
              <option value="weekly">Weekly</option>
            </select>
          </div>
          <label className="flex items-center gap-2 text-sm text-zinc-600 dark:text-zinc-300">
            <input type="checkbox" checked={useOverlay} onChange={e => setUseOverlay(e.target.checked)} />
            Apply Overlay
          </label>
          <button onClick={runBacktest} disabled={running}
            className="rounded-lg bg-zinc-900 px-4 py-2 text-sm font-medium text-white hover:bg-zinc-700 disabled:opacity-50 dark:bg-zinc-50 dark:text-zinc-900 dark:hover:bg-zinc-200 transition">
            {running ? "Running…" : "Run Backtest"}
          </button>
        </div>
        {running && (
          <p className="mt-2 text-xs text-zinc-400 animate-pulse">
            Computing {freq} rebalances 2015–2026 — MVO solves at each step, ~20-40s…
          </p>
        )}
        {error && <p className="mt-2 text-xs text-rose-500">{error}</p>}
      </section>

      {/* Charts */}
      {result && (
        <>
          <section>
            <h3 className="mb-2 text-sm font-semibold text-zinc-700 dark:text-zinc-300">Equity Curve (Base = 100)</h3>
            <div className="rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 overflow-hidden">
              <PlotlyChart figure={result.equity_figure} height={380} />
            </div>
          </section>
          <section>
            <h3 className="mb-2 text-sm font-semibold text-zinc-700 dark:text-zinc-300">Drawdown</h3>
            <div className="rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 overflow-hidden">
              <PlotlyChart figure={result.drawdown_figure} height={220} />
            </div>
          </section>
        </>
      )}

      {/* Metrics table */}
      {result ? (
        <section>
          <h3 className="mb-3 text-sm font-semibold text-zinc-700 dark:text-zinc-300">Performance Metrics</h3>
          {useOverlay && (
            <div className="mb-3 grid grid-cols-1 gap-3 md:grid-cols-4">
              {[
                { label: "Core Return", value: fmtPct(result.attribution.core_return) },
                { label: "Overlay Return", value: fmtPct(result.attribution.overlay_return) },
                { label: "Total Return", value: fmtPct(result.attribution.total_return) },
                { label: "Overlay Sharpe Contribution", value: fmtNum(result.attribution.overlay_sharpe_contribution) },
              ].map((item) => (
                <div key={item.label} className="rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
                  <div className="text-xs text-zinc-500">{item.label}</div>
                  <div className="mt-1 text-xl font-mono font-semibold text-zinc-900 dark:text-zinc-50">{item.value}</div>
                </div>
              ))}
            </div>
          )}
          <div className="overflow-x-auto rounded-xl border border-zinc-200 dark:border-zinc-800">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-zinc-100 dark:border-zinc-800">
                  <th className="px-4 py-2.5 text-left font-medium text-zinc-500">Metric</th>
                  {COLS.map(c => (
                    <th key={c.id} className={`px-4 py-2.5 text-right font-medium ${c.id === "portfolio" ? "text-violet-600" : "text-zinc-500"}`}>
                      {c.label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {METRIC_ROWS.map((row, i) => (
                  <tr key={row.key} className={`border-b border-zinc-50 dark:border-zinc-800/50 ${i%2===0?"bg-white dark:bg-zinc-900":"bg-zinc-50/50 dark:bg-zinc-800/20"}`}>
                    <td className="px-4 py-2 text-zinc-600 dark:text-zinc-400">{row.label}</td>
                    {COLS.map(c => (
                      <td key={c.id} className={`px-4 py-2 text-right font-mono ${c.id==="portfolio"?"font-semibold text-zinc-900 dark:text-zinc-50":"text-zinc-500"}`}>
                        {c.m ? row.fmt(c.m[row.key]) : "—"}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : (
        <section className="rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-900 px-6 py-12 text-center">
          <p className="text-sm text-zinc-500">Configure parameters above and click <strong>Run Backtest</strong>.</p>
          <p className="mt-1 text-xs text-zinc-400">Core-only (no overlay). Overlay added in M6.</p>
        </section>
      )}

      {/* Trades summary */}
      {result && (
        <section>
          <h3 className="mb-2 text-sm font-semibold text-zinc-700 dark:text-zinc-300">Trades Summary</h3>
          <div className="grid grid-cols-3 gap-3">
            {[
              { label: "Total Trades", value: result.trades_summary.total_trades.toString() },
              { label: "Total Cost", value: `$${result.trades_summary.total_cost_dollars.toFixed(2)}` },
              { label: "Ann. Turnover", value: `${(result.trades_summary.turnover_annualized * 100).toFixed(1)}%` },
            ].map(s => (
              <div key={s.label} className="rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-4">
                <div className="text-xs text-zinc-500 mb-1">{s.label}</div>
                <div className="text-2xl font-bold font-mono text-zinc-900 dark:text-zinc-50">{s.value}</div>
              </div>
            ))}
          </div>
          {useOverlay && (
            <p className="mt-3 text-xs text-zinc-500">
              Alpha from overlay: {fmtPct(result.attribution.overlay_return)}. {result.warnings?.join(" ")}
            </p>
          )}
          <details className="mt-4 rounded-xl border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
            <summary className="cursor-pointer px-4 py-3 text-sm font-medium text-zinc-700 dark:text-zinc-300">
              View Actual Trades
            </summary>
            <div className="max-h-[420px] overflow-auto border-t border-zinc-100 dark:border-zinc-800">
              <table className="w-full text-xs">
                <thead className="sticky top-0 bg-zinc-50 dark:bg-zinc-900">
                  <tr>
                    <th className="px-4 py-2 text-left font-medium text-zinc-500">Date</th>
                    <th className="px-4 py-2 text-left font-medium text-zinc-500">Ticker</th>
                    <th className="px-4 py-2 text-right font-medium text-zinc-500">Delta Wt</th>
                    <th className="px-4 py-2 text-right font-medium text-zinc-500">Price</th>
                    <th className="px-4 py-2 text-right font-medium text-zinc-500">Cost</th>
                  </tr>
                </thead>
                <tbody>
                  {result.trades.map((trade, index) => (
                    <tr key={`${trade.date}-${trade.ticker}-${index}`} className="border-t border-zinc-100 dark:border-zinc-800">
                      <td className="px-4 py-2 text-zinc-600 dark:text-zinc-400">{trade.date}</td>
                      <td className="px-4 py-2 font-mono text-zinc-900 dark:text-zinc-50">{trade.ticker}</td>
                      <td className={`px-4 py-2 text-right font-mono ${trade.delta_weight >= 0 ? "text-emerald-600" : "text-rose-600"}`}>
                        {trade.delta_weight >= 0 ? "+" : ""}{(trade.delta_weight * 100).toFixed(2)}%
                      </td>
                      <td className="px-4 py-2 text-right font-mono text-zinc-600 dark:text-zinc-400">${trade.price.toFixed(2)}</td>
                      <td className="px-4 py-2 text-right font-mono text-zinc-600 dark:text-zinc-400">${trade.cost_dollars.toFixed(2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        </section>
      )}
    </div>
  );
}

// ─── Main workspace ───────────────────────────────────────────────────────────

const TABS: { id: Tab; label: string }[] = [
  { id: "overview",  label: "Overview" },
  { id: "portfolio", label: "Portfolio Builder" },
  { id: "signals",   label: "Market Signals" },
  { id: "backtest",  label: "Backtest" },
];

export function RoboAdvisorWorkspace() {
  const [activeTab, setActiveTab] = useState<Tab>("overview");

  return (
    <div className="flex flex-1 flex-col">
      <div className="border-b border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-950">
        <div className="mx-auto max-w-screen-xl px-6">
          <div className="flex gap-1">
            {TABS.map((t) => (
              <button
                key={t.id}
                onClick={() => setActiveTab(t.id)}
                className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
                  activeTab === t.id
                    ? "border-zinc-900 text-zinc-900 dark:border-zinc-50 dark:text-zinc-50"
                    : "border-transparent text-zinc-500 hover:text-zinc-700 dark:text-zinc-400 dark:hover:text-zinc-300"
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="flex-1 bg-zinc-50 dark:bg-black">
        <div className="mx-auto max-w-screen-xl px-6 py-8">
          {activeTab === "overview"  && <OverviewTab />}
          {activeTab === "portfolio" && <PortfolioTab />}
          {activeTab === "signals"   && <SignalsTab />}
          {activeTab === "backtest"  && <BacktestTab />}
        </div>
      </div>
    </div>
  );
}
