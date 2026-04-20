import { SimulatorWorkspace } from "@/components/simulator/SimulatorWorkspace";

export default function SimulatorPage() {
  return (
    <div className="flex min-h-full flex-1 flex-col bg-zinc-50 dark:bg-black">
      <header className="border-b border-zinc-200 bg-white px-6 py-3 dark:border-zinc-800 dark:bg-zinc-900">
        <div className="flex items-center gap-2">
          <h1 className="text-sm font-medium text-zinc-900 dark:text-zinc-50">
            Simulation Engine
          </h1>
          <span className="rounded-full bg-violet-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-violet-700 dark:bg-violet-950 dark:text-violet-300">
            Live Data
          </span>
        </div>
      </header>
      <SimulatorWorkspace />
    </div>
  );
}
