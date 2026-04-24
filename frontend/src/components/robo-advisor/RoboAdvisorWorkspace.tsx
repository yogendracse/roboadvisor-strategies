"use client";

import { useState } from "react";

// ─── Types ────────────────────────────────────────────────────────────────────

type Tab = "overview" | "portfolio" | "signals" | "backtest";

interface Milestone {
  id: string;
  label: string;
  description: string;
  status: "done" | "in-progress" | "planned";
}

// ─── Data ─────────────────────────────────────────────────────────────────────

const MILESTONES: Milestone[] = [
  {
    id: "M1",
    label: "Data Pipeline",
    description: "yfinance loader + Kalshi API client + local Parquet/SQLite storage",
    status: "planned",
  },
  {
    id: "M2",
    label: "Core Strategies",
    description: "Mean-Variance Optimization (Ledoit-Wolf) + Risk Parity with unit tests",
    status: "planned",
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
    status: "planned",
  },
  {
    id: "M6",
    label: "Overlay Engine",
    description: "Kalshi signal ingestion, sensitivity mapping, de-risk / re-risk rules",
    status: "planned",
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

const SIGNALS = [
  { id: "recession_prob", label: "P(US Recession, 2026)", current: 0.32, baseline: 0.15, tilts: ["−VOO", "+TLT", "+GLD", "+XLP"] },
  { id: "fed_cut_prob",   label: "P(Fed Cut, Next Meeting)", current: 0.61, baseline: 0.50, tilts: ["+TLT", "+QQQ"] },
  { id: "sp_up_prob",     label: "P(S&P 500 Up, Year-End)", current: 0.55, baseline: 0.60, tilts: ["+VOO", "−TLT"] },
];

const STRATEGIES_MIX = [
  { id: "mvo",        label: "Mean-Variance Optimization", weight: 50, color: "bg-violet-500" },
  { id: "rp",         label: "Risk Parity",                weight: 30, color: "bg-sky-500" },
  { id: "factor",     label: "Factor Model (FF3+Mom)",     weight: 20, color: "bg-emerald-500" },
];

const CORE_UNIVERSE = [
  { ticker: "SPY", sleeve: "Core Macro", weight: 22 },
  { ticker: "QQQ", sleeve: "Core Macro", weight: 12 },
  { ticker: "TLT", sleeve: "Core Macro", weight: 18 },
  { ticker: "IEF", sleeve: "Core Macro", weight: 10 },
  { ticker: "GLD", sleeve: "Core Macro", weight: 8 },
  { ticker: "DBC", sleeve: "Core Macro", weight: 5 },
  { ticker: "VNQ", sleeve: "Core Macro", weight: 5 },
  { ticker: "VXUS", sleeve: "Core Macro", weight: 10 },
  { ticker: "Stock Sleeve", sleeve: "Equity Alpha", weight: 10 },
];

// ─── Sub-components ───────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: Milestone["status"] }) {
  const map = {
    done:        "bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300",
    "in-progress": "bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300",
    planned:     "bg-zinc-100 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400",
  } as const;
  const label = { done: "Done", "in-progress": "In Progress", planned: "Planned" } as const;
  return (
    <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${map[status]}`}>
      {label[status]}
    </span>
  );
}

function ComingSoonOverlay({ label }: { label: string }) {
  return (
    <div className="absolute inset-0 flex flex-col items-center justify-center rounded-xl bg-zinc-50/80 dark:bg-black/80 backdrop-blur-[2px] z-10">
      <span className="text-sm font-medium text-zinc-400 dark:text-zinc-500">{label}</span>
      <span className="mt-1 text-[11px] text-zinc-400 dark:text-zinc-600">Backend implementation in progress (M1–M9)</span>
    </div>
  );
}

// ─── Tabs ─────────────────────────────────────────────────────────────────────

function OverviewTab() {
  return (
    <div className="space-y-8">
      {/* Architecture diagram (text) */}
      <section>
        <h3 className="mb-3 text-sm font-semibold text-zinc-700 dark:text-zinc-300">System Architecture</h3>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          {[
            {
              title: "Data Layer",
              items: ["yfinance daily OHLCV", "Kalshi API (prediction markets)", "Parquet + SQLite local cache", "Fundamental data (P/B, P/E, Mom)"],
              color: "border-sky-200 dark:border-sky-800",
              dot: "bg-sky-400",
            },
            {
              title: "Strategy Engine",
              items: ["MVO (Ledoit-Wolf shrinkage)", "Risk Parity (ERC)", "Factor Model (FF3 + Momentum)", "Strategy Blender (config-driven)"],
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
            Where <code className="font-mono">P_market</code> is the current Kalshi probability and{" "}
            <code className="font-mono">P_baseline</code> is the trailing 2-year rolling median.
            Total deviation is capped at ±20% per asset. Both de-risk (P spikes above threshold) and
            re-risk (P falls or drawdown already priced in via VIX z-score) rules apply.
          </p>
        </div>
      </section>
    </div>
  );
}

function PortfolioTab() {
  const [riskProfile, setRiskProfile] = useState<"conservative" | "balanced" | "aggressive">("balanced");
  const [capital, setCapital] = useState("100000");

  const profileWeights: Record<string, number[]> = {
    conservative: [30, 50, 20],
    balanced:     [50, 30, 20],
    aggressive:   [65, 15, 20],
  };

  const weights = profileWeights[riskProfile];

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
              <div className="mt-0.5 text-xs opacity-60">
                {p === "conservative" && "MVO 30 / RP 50 / Factor 20"}
                {p === "balanced"     && "MVO 50 / RP 30 / Factor 20"}
                {p === "aggressive"   && "MVO 65 / RP 15 / Factor 20"}
              </div>
            </button>
          ))}
        </div>
      </section>

      {/* Capital */}
      <section>
        <h3 className="mb-3 text-sm font-semibold text-zinc-700 dark:text-zinc-300">Capital</h3>
        <div className="flex items-center gap-2">
          <span className="text-sm text-zinc-500">$</span>
          <input
            type="number"
            value={capital}
            onChange={(e) => setCapital(e.target.value)}
            className="w-40 rounded-lg border border-zinc-200 bg-white px-3 py-1.5 text-sm text-zinc-900 focus:border-zinc-900 focus:outline-none dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50 dark:focus:border-zinc-400"
          />
        </div>
      </section>

      {/* Strategy mix */}
      <section>
        <h3 className="mb-3 text-sm font-semibold text-zinc-700 dark:text-zinc-300">
          Strategy Mix — <span className="text-zinc-500 font-normal capitalize">{riskProfile}</span>
        </h3>
        <div className="space-y-2">
          {STRATEGIES_MIX.map((s, i) => (
            <div key={s.id} className="flex items-center gap-3">
              <span className="w-40 text-xs text-zinc-600 dark:text-zinc-400 shrink-0">{s.label}</span>
              <div className="flex-1 h-2 rounded-full bg-zinc-100 dark:bg-zinc-800 overflow-hidden">
                <div
                  className={`h-full rounded-full ${s.color} transition-all duration-300`}
                  style={{ width: `${weights[i]}%` }}
                />
              </div>
              <span className="w-10 text-right text-xs font-mono text-zinc-700 dark:text-zinc-300">{weights[i]}%</span>
            </div>
          ))}
        </div>
      </section>

      {/* Target allocation */}
      <section className="relative">
        <ComingSoonOverlay label="Portfolio weights calculated after M4 is complete" />
        <h3 className="mb-3 text-sm font-semibold text-zinc-700 dark:text-zinc-300">Target Allocation</h3>
        <div className="divide-y divide-zinc-100 dark:divide-zinc-800 rounded-xl border border-zinc-200 dark:border-zinc-800 overflow-hidden opacity-40">
          {CORE_UNIVERSE.map((row) => (
            <div key={row.ticker} className="flex items-center gap-3 bg-white dark:bg-zinc-900 px-4 py-2.5">
              <span className="w-24 text-xs font-mono font-semibold text-zinc-900 dark:text-zinc-50">{row.ticker}</span>
              <span className="flex-1 text-xs text-zinc-500">{row.sleeve}</span>
              <div className="w-24 h-1.5 rounded-full bg-zinc-100 dark:bg-zinc-800 overflow-hidden">
                <div className="h-full bg-violet-400 rounded-full" style={{ width: `${row.weight * 4}%` }} />
              </div>
              <span className="w-10 text-right text-xs font-mono text-zinc-700 dark:text-zinc-300">{row.weight}%</span>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

function SignalsTab() {
  return (
    <div className="space-y-6">
      <section>
        <h3 className="mb-3 text-sm font-semibold text-zinc-700 dark:text-zinc-300">
          Active Prediction Market Signals
          <span className="ml-2 rounded-full bg-zinc-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400">
            Mock Data
          </span>
        </h3>
        <div className="space-y-4">
          {SIGNALS.map((sig) => {
            const delta = sig.current - sig.baseline;
            const absDelta = Math.abs(delta);
            const isElevated = delta > 0;
            return (
              <div key={sig.id} className="rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-4">
                <div className="flex items-start justify-between gap-4 mb-3">
                  <div>
                    <span className="text-sm font-medium text-zinc-900 dark:text-zinc-50">{sig.label}</span>
                    <div className="mt-0.5 flex items-center gap-2">
                      <span className="text-xs text-zinc-500">Baseline: {(sig.baseline * 100).toFixed(0)}%</span>
                      <span className={`text-xs font-medium ${isElevated ? "text-rose-600" : "text-emerald-600"}`}>
                        {isElevated ? "▲" : "▼"} {(absDelta * 100).toFixed(0)}pp vs baseline
                      </span>
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="text-2xl font-bold tabular-nums text-zinc-900 dark:text-zinc-50">
                      {(sig.current * 100).toFixed(0)}%
                    </div>
                  </div>
                </div>
                {/* Probability bar */}
                <div className="h-2 rounded-full bg-zinc-100 dark:bg-zinc-800 overflow-hidden mb-3">
                  <div
                    className={`h-full rounded-full transition-all ${isElevated ? "bg-rose-400" : "bg-emerald-400"}`}
                    style={{ width: `${sig.current * 100}%` }}
                  />
                </div>
                {/* Tilts */}
                <div className="flex flex-wrap gap-1.5">
                  <span className="text-[11px] text-zinc-400 mr-1">Active tilts:</span>
                  {sig.tilts.map((t) => (
                    <span
                      key={t}
                      className={`rounded px-1.5 py-0.5 text-[11px] font-mono font-semibold ${
                        t.startsWith("+")
                          ? "bg-emerald-50 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300"
                          : "bg-rose-50 text-rose-700 dark:bg-rose-950 dark:text-rose-300"
                      }`}
                    >
                      {t}
                    </span>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      </section>

      {/* Config preview */}
      <section>
        <h3 className="mb-3 text-sm font-semibold text-zinc-700 dark:text-zinc-300">Sensitivity Config (signals.yaml)</h3>
        <div className="rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-950 p-4 overflow-x-auto">
          <pre className="text-xs text-zinc-300 leading-relaxed">{`signals:
  recession_prob:
    event_id: "RECESSION-26"
    baseline: 0.15
    tilts:
      VOO: -1.5    # beta to recession risk
      TLT: +1.0
      GLD: +0.5
      XLP: +0.3

  fed_cut_prob:
    event_id: "FED-CUT-NEXT"
    baseline: 0.50
    tilts:
      TLT: +0.8
      QQQ: +0.4

  sp_up_prob:
    event_id: "SPX-UP-YE"
    baseline: 0.60
    tilts:
      VOO: +1.2
      TLT: -0.8`}</pre>
        </div>
      </section>
    </div>
  );
}

function BacktestTab() {
  return (
    <div className="space-y-6">
      {/* Metrics placeholder */}
      <section className="relative">
        <ComingSoonOverlay label="Backtest engine available after M5" />
        <h3 className="mb-3 text-sm font-semibold text-zinc-700 dark:text-zinc-300">Performance Metrics</h3>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4 opacity-30">
          {[
            { label: "CAGR", value: "—" },
            { label: "Sharpe", value: "—" },
            { label: "Max DD", value: "—" },
            { label: "Sortino", value: "—" },
          ].map((m) => (
            <div key={m.label} className="rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-4">
              <div className="text-xs text-zinc-500 mb-1">{m.label}</div>
              <div className="text-2xl font-bold text-zinc-900 dark:text-zinc-50">{m.value}</div>
            </div>
          ))}
        </div>
      </section>

      {/* Equity curve placeholder */}
      <section className="relative">
        <ComingSoonOverlay label="Equity curve available after M5" />
        <h3 className="mb-3 text-sm font-semibold text-zinc-700 dark:text-zinc-300">Equity Curve</h3>
        <div className="h-48 rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 opacity-30 flex items-center justify-center">
          <span className="text-xs text-zinc-400">Portfolio · 60/40 · SPY</span>
        </div>
      </section>

      {/* Benchmarks */}
      <section>
        <h3 className="mb-3 text-sm font-semibold text-zinc-700 dark:text-zinc-300">Benchmark Comparison</h3>
        <div className="divide-y divide-zinc-100 dark:divide-zinc-800 rounded-xl border border-zinc-200 dark:border-zinc-800 overflow-hidden">
          {[
            { name: "Robo-Advisor (Overlay On)",  cagr: "—", sharpe: "—", maxDD: "—", status: "planned" },
            { name: "Robo-Advisor (Core Only)",   cagr: "—", sharpe: "—", maxDD: "—", status: "planned" },
            { name: "SPY Buy & Hold",             cagr: "—", sharpe: "—", maxDD: "—", status: "planned" },
            { name: "60/40 (VOO + TLT)",          cagr: "—", sharpe: "—", maxDD: "—", status: "planned" },
            { name: "Equal-Weight Core Universe", cagr: "—", sharpe: "—", maxDD: "—", status: "planned" },
          ].map((row) => (
            <div key={row.name} className="flex items-center gap-3 bg-white dark:bg-zinc-900 px-4 py-3">
              <span className="flex-1 text-sm text-zinc-700 dark:text-zinc-300">{row.name}</span>
              {["cagr", "sharpe", "maxDD"].map((k) => (
                <span key={k} className="w-16 text-right text-sm font-mono text-zinc-400">—</span>
              ))}
              <StatusBadge status={row.status as Milestone["status"]} />
            </div>
          ))}
        </div>
        <p className="mt-2 text-xs text-zinc-400">Backtest period: 2015-01-01 → present · Rebalance: monthly · Costs: 5 bps/trade</p>
      </section>
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
      {/* Tab bar */}
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

      {/* Content */}
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
