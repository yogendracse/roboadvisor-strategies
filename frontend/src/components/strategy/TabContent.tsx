"use client";

import { PlotlyChart } from "@/components/charts/PlotlyChart";
import { Disclosure } from "@/components/ui/Disclosure";
import { Markdown } from "@/components/ui/Markdown";
import { MetricStrip } from "./MetricStrip";
import { ResultsTable } from "./ResultsTable";
import type { TabSpec } from "@/lib/strategy-compute";

interface Props {
  tab: TabSpec;
  isStale?: boolean;
}

export function TabContent({ tab, isStale = false }: Props) {
  return (
    <div className={`flex flex-col gap-4 ${isStale ? "opacity-60" : ""}`}>
      {tab.intro_md && (
        <Disclosure
          summary={`${tab.title} — plain-language guide`}
          defaultOpen={false}
        >
          <Markdown>{tab.intro_md}</Markdown>
        </Disclosure>
      )}

      {tab.metrics && tab.metrics.length > 0 && (
        <MetricStrip metrics={tab.metrics} />
      )}

      {tab.charts?.map((c) => (
        <div
          key={c.id}
          className="flex flex-col gap-2 rounded-xl border border-zinc-200 bg-white p-4 shadow-sm dark:border-zinc-800 dark:bg-zinc-900"
        >
          <div>
            <h3 className="text-base font-semibold text-zinc-900 dark:text-zinc-50">
              {c.title}
            </h3>
            {c.description && (
              <div className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
                <Markdown>{c.description}</Markdown>
              </div>
            )}
          </div>
          <PlotlyChart figure={c.figure} />
          {c.guide_md && (
            <Disclosure summary="Plain-language guide">
              <Markdown>{c.guide_md}</Markdown>
            </Disclosure>
          )}
        </div>
      ))}

      {tab.tables?.map((t) => (
        <ResultsTable key={t.id} table={t} />
      ))}
    </div>
  );
}
