"use client";

import type { ReactNode } from "react";

export interface TabDef {
  id: string;
  title: string;
  icon?: string | null;
}

interface Props {
  tabs: TabDef[];
  active: string;
  onChange: (id: string) => void;
  rightSlot?: ReactNode;
}

export function Tabs({ tabs, active, onChange, rightSlot }: Props) {
  return (
    <div className="flex items-center justify-between border-b border-zinc-200 dark:border-zinc-800">
      <nav className="flex flex-wrap gap-1" role="tablist">
        {tabs.map((t) => {
          const isActive = t.id === active;
          return (
            <button
              key={t.id}
              role="tab"
              aria-selected={isActive}
              onClick={() => onChange(t.id)}
              className={`-mb-px flex items-center gap-1.5 border-b-2 px-3 py-2 text-sm font-medium transition ${
                isActive
                  ? "border-zinc-900 text-zinc-900 dark:border-zinc-50 dark:text-zinc-50"
                  : "border-transparent text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200"
              }`}
            >
              {t.icon && <span aria-hidden>{t.icon}</span>}
              {t.title}
            </button>
          );
        })}
      </nav>
      {rightSlot}
    </div>
  );
}
