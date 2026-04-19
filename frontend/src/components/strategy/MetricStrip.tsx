"use client";

import type { Metric } from "@/lib/strategy-compute";

interface Props {
  metrics: Metric[];
}

function formatValue(m: Metric): string {
  if (m.format === "percent") return `${(m.value * 100).toFixed(1)}%`;
  if (m.format === "ratio") return m.value.toFixed(3);
  if (Number.isInteger(m.value)) return m.value.toLocaleString();
  return m.value.toFixed(3);
}

function tone(m: Metric): string {
  if (m.format !== "ratio" && m.format !== "percent") return "";
  if (m.key === "max_dd") {
    return m.value < 0 ? "text-red-600 dark:text-red-400" : "";
  }
  if (m.value > 0) return "text-emerald-600 dark:text-emerald-400";
  if (m.value < 0) return "text-red-600 dark:text-red-400";
  return "";
}

export function MetricStrip({ metrics }: Props) {
  if (!metrics.length) return null;
  return (
    <ul className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-7">
      {metrics.map((m) => (
        <li
          key={m.key}
          className="rounded-lg border border-zinc-200 bg-white px-3 py-2 dark:border-zinc-800 dark:bg-zinc-900"
        >
          <div className="text-[10px] font-medium uppercase tracking-wide text-zinc-500">
            {m.label}
          </div>
          <div className={`mt-0.5 font-mono text-base font-semibold ${tone(m)}`}>
            {formatValue(m)}
          </div>
        </li>
      ))}
    </ul>
  );
}
