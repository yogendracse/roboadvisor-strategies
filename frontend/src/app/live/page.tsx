import { LiveWorkspace } from "@/components/live/LiveWorkspace";

export default function LivePage() {
  return (
    <div className="flex min-h-full flex-1 flex-col bg-zinc-50 dark:bg-black">
      <header className="border-b border-zinc-200 bg-white px-6 py-3 dark:border-zinc-800 dark:bg-zinc-900">
        <div className="flex items-center gap-2">
          <h1 className="text-sm font-medium text-zinc-900 dark:text-zinc-50">
            Live Signals
          </h1>
          <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300">
            Live
          </span>
        </div>
      </header>
      <LiveWorkspace />
    </div>
  );
}
