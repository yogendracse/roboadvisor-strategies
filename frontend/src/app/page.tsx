import Link from "next/link";

import { STRATEGIES } from "@/lib/strategies";

export default function Home() {
  return (
    <main className="flex flex-1 flex-col items-center bg-zinc-50 px-6 py-16 dark:bg-black">
      <div className="w-full max-w-5xl">
        <header className="mb-10">
          <h1 className="text-3xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">
            Volatility Dashboard
          </h1>
          <p className="mt-1 text-zinc-600 dark:text-zinc-400">
            Multi-strategy backtesting & analysis
          </p>
        </header>

        <section>
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-zinc-500">
            Strategies
          </h2>
          <ul className="grid grid-cols-1 gap-4 md:grid-cols-2">
            {STRATEGIES.map((s) => (
              <li key={s.id}>
                <Link
                  href={`/strategies/${s.id}`}
                  className="block rounded-xl border border-zinc-200 bg-white p-5 shadow-sm transition hover:border-zinc-900 hover:shadow-md dark:border-zinc-800 dark:bg-zinc-900 dark:hover:border-zinc-50"
                >
                  <h3 className="text-lg font-medium text-zinc-900 dark:text-zinc-50">
                    {s.name}
                  </h3>
                  <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
                    {s.description}
                  </p>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      </div>
    </main>
  );
}
