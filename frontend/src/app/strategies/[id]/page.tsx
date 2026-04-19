import { notFound } from "next/navigation";
import Link from "next/link";

import { StrategyWorkspace } from "./strategy-workspace";
import { findStrategy, STRATEGIES } from "@/lib/strategies";

export function generateStaticParams() {
  return STRATEGIES.map((s) => ({ id: s.id }));
}

export default async function StrategyPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const strategy = findStrategy(id);
  if (!strategy) notFound();

  return (
    <div className="flex min-h-full flex-1 flex-col bg-zinc-50 dark:bg-black">
      <header className="border-b border-zinc-200 bg-white px-6 py-3 dark:border-zinc-800 dark:bg-zinc-900">
        <div className="flex items-center gap-3">
          <Link
            href="/"
            className="text-sm text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200"
          >
            ← Strategies
          </Link>
          <span className="text-zinc-300 dark:text-zinc-700">/</span>
          <h1 className="text-sm font-medium text-zinc-900 dark:text-zinc-50">
            {strategy.name}
          </h1>
        </div>
      </header>

      <StrategyWorkspace strategy={strategy} />
    </div>
  );
}
