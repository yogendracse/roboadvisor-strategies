"use client";

import { useLiveStore, type LiveStrategy } from "@/lib/store";

const OPTIONS: { id: LiveStrategy; label: string; description: string }[] = [
  {
    id: "volatility",
    label: "Volatility",
    description: "zvol20 quintile (Q1–Q5)",
  },
  {
    id: "trend",
    label: "Trend",
    description: "MA crossover / breakout signal",
  },
];

export function StrategyCheckboxPanel() {
  const enabled = useLiveStore((s) => s.liveEnabledStrategies);
  const setEnabled = useLiveStore((s) => s.setLiveEnabledStrategies);

  const toggle = (id: LiveStrategy) => {
    if (enabled.includes(id)) {
      setEnabled(enabled.filter((s) => s !== id));
    } else {
      setEnabled([...enabled, id]);
    }
  };

  return (
    <div className="space-y-2">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-zinc-500">
        Indicators
      </h3>
      {OPTIONS.map((opt) => (
        <label
          key={opt.id}
          className="flex cursor-pointer items-start gap-2.5"
        >
          <input
            type="checkbox"
            checked={enabled.includes(opt.id)}
            onChange={() => toggle(opt.id)}
            className="mt-0.5 h-3.5 w-3.5 rounded border-zinc-300 accent-zinc-900 dark:accent-zinc-100"
          />
          <div>
            <span className="text-sm font-medium text-zinc-800 dark:text-zinc-200">
              {opt.label}
            </span>
            <span className="ml-1.5 text-xs text-zinc-400">{opt.description}</span>
          </div>
        </label>
      ))}
    </div>
  );
}
