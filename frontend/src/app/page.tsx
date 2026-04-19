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

      </div>
    </main>
  );
}
