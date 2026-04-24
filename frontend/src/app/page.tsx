import Link from "next/link";

import { STRATEGIES } from "@/lib/strategies";

export default function Home() {
  return (
    <main className="flex flex-1 flex-col items-center bg-zinc-50 px-6 py-12 dark:bg-black">
      <div className="w-full max-w-5xl space-y-12">

        {/* Strategy Learnings */}
        <section>
          <header className="mb-4">
            <h2 className="text-xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">
              Strategy Learnings
            </h2>
            <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">
              Analytical back-tests — learn how each strategy behaves on historical data.
            </p>
          </header>
          <ul className="grid grid-cols-1 gap-4 md:grid-cols-2">
            {STRATEGIES.map((s) => (
              <li key={s.id}>
                <Link
                  href={`/strategies/${s.id}`}
                  className="block rounded-xl border border-zinc-200 bg-white p-5 shadow-sm transition hover:border-zinc-900 hover:shadow-md dark:border-zinc-800 dark:bg-zinc-900 dark:hover:border-zinc-50"
                >
                  <h3 className="text-base font-medium text-zinc-900 dark:text-zinc-50">
                    {s.name}
                  </h3>
                  <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">
                    {s.description}
                  </p>
                </Link>
              </li>
            ))}
          </ul>
        </section>

        {/* Live Signals */}
        <section>
          <header className="mb-4">
            <h2 className="text-xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">
              Live Signals
            </h2>
            <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">
              Operational view — what the strategies are saying <em>right now</em> about any asset.
            </p>
          </header>
          <Link
            href="/live"
            className="block rounded-xl border border-zinc-200 bg-white p-5 shadow-sm transition hover:border-zinc-900 hover:shadow-md dark:border-zinc-800 dark:bg-zinc-900 dark:hover:border-zinc-50"
          >
            <h3 className="text-base font-medium text-zinc-900 dark:text-zinc-50">
              Live Signal Dashboard
            </h3>
            <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">
              Add any instrument, select a date range, and see real-time volatility
              quintile and trend signals overlaid on a price chart with shared zoom.
            </p>
          </Link>
        </section>

        {/* Simulation Engine */}
        <section>
          <header className="mb-4">
            <h2 className="text-xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">
              Simulation Engine
            </h2>
            <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">
              Sequential portfolio simulator — live market data, no lookahead bias, full guardrails.
            </p>
          </header>
          <Link
            href="/simulator"
            className="block rounded-xl border border-zinc-200 bg-white p-5 shadow-sm transition hover:border-zinc-900 hover:shadow-md dark:border-zinc-800 dark:bg-zinc-900 dark:hover:border-zinc-50"
          >
            <h3 className="text-base font-medium text-zinc-900 dark:text-zinc-50">
              Portfolio Simulator
            </h3>
            <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">
              Pick any Yahoo Finance tickers, select equal-weight or inverse-vol weighting,
              configure circuit-breaker and concentration guardrails, and watch the
              equity curve, drawdown, rolling Sharpe, and trade log unfold.
            </p>
          </Link>
        </section>

        {/* Robo-Advisor */}
        <section>
          <header className="mb-4">
            <h2 className="text-xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">
              Robo-Advisor
            </h2>
            <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">
              Multi-strategy core portfolio with a tactical overlay driven by prediction market signals (Kalshi / Polymarket).
            </p>
          </header>
          <Link
            href="/robo-advisor"
            className="block rounded-xl border border-zinc-200 bg-white p-5 shadow-sm transition hover:border-zinc-900 hover:shadow-md dark:border-zinc-800 dark:bg-zinc-900 dark:hover:border-zinc-50"
          >
            <div className="flex items-center gap-2 mb-1">
              <h3 className="text-base font-medium text-zinc-900 dark:text-zinc-50">
                Prediction Market Overlay
              </h3>
              <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-700 dark:bg-amber-950 dark:text-amber-300">
                Alpha
              </span>
            </div>
            <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">
              MVO + Risk Parity + Factor Model blended core, tilted by Kalshi probabilities for recession,
              Fed cuts, and S&P direction. Walk-forward backtest with circuit breakers and rebalancing rules.
            </p>
          </Link>
        </section>

      </div>
    </main>
  );
}
