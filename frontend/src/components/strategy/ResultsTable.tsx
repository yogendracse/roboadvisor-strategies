"use client";

import type { TableSpec } from "@/lib/strategy-compute";

export function ResultsTable({ table }: { table: TableSpec }) {
  return (
    <div className="overflow-hidden rounded-xl border border-zinc-200 bg-white shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
      <div className="border-b border-zinc-200 bg-zinc-50 px-4 py-2 dark:border-zinc-800 dark:bg-zinc-950/50">
        <h4 className="text-sm font-semibold text-zinc-900 dark:text-zinc-50">
          {table.title}
        </h4>
        {table.description && (
          <p className="text-xs text-zinc-500">{table.description}</p>
        )}
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-zinc-200 bg-zinc-50/50 text-xs uppercase tracking-wide text-zinc-500 dark:border-zinc-800 dark:bg-zinc-950/30">
              {table.columns.map((c) => (
                <th
                  key={c.key}
                  className={`px-3 py-2 font-medium ${
                    c.align === "right" ? "text-right" : "text-left"
                  }`}
                >
                  {c.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {table.rows.map((row, i) => (
              <tr
                key={i}
                className="border-b border-zinc-100 last:border-0 dark:border-zinc-800/60"
              >
                {table.columns.map((c) => {
                  const raw = row[c.key];
                  return (
                    <td
                      key={c.key}
                      className={`px-3 py-1.5 ${
                        c.align === "right"
                          ? "text-right font-mono tabular-nums"
                          : "text-left"
                      } text-zinc-800 dark:text-zinc-200`}
                    >
                      {raw == null ? "—" : String(raw)}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
