import { RoboAdvisorWorkspace } from "@/components/robo-advisor/RoboAdvisorWorkspace";

export default function RoboAdvisorPage() {
  return (
    <div className="flex min-h-full flex-1 flex-col bg-zinc-50 dark:bg-black">
      <header className="border-b border-zinc-200 bg-white px-6 py-3 dark:border-zinc-800 dark:bg-zinc-900">
        <div className="mx-auto max-w-screen-xl flex items-center gap-2">
          <h1 className="text-sm font-medium text-zinc-900 dark:text-zinc-50">
            Robo-Advisor
          </h1>
          <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-700 dark:bg-amber-950 dark:text-amber-300">
            Alpha
          </span>
          <span className="ml-2 text-xs text-zinc-400 dark:text-zinc-500">
            Multi-strategy core · Prediction market overlay · Walk-forward backtest
          </span>
        </div>
      </header>
      <RoboAdvisorWorkspace />
    </div>
  );
}
