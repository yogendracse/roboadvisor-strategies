"use client";

import { useState, type ReactNode } from "react";

interface Props {
  summary: string;
  defaultOpen?: boolean;
  children: ReactNode;
}

export function Disclosure({ summary, defaultOpen = false, children }: Props) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="rounded-lg border border-zinc-200 bg-zinc-50 dark:border-zinc-800 dark:bg-zinc-950/50">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-sm font-medium text-zinc-800 transition hover:bg-zinc-100 dark:text-zinc-200 dark:hover:bg-zinc-900"
        aria-expanded={open}
      >
        <span className="flex items-center gap-2">
          <span aria-hidden>📖</span>
          {summary}
        </span>
        <ChevronIcon open={open} />
      </button>
      {open && (
        <div className="border-t border-zinc-200 px-3 py-3 dark:border-zinc-800">
          {children}
        </div>
      )}
    </div>
  );
}

function ChevronIcon({ open }: { open: boolean }) {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={`shrink-0 text-zinc-400 transition-transform ${
        open ? "rotate-180" : ""
      }`}
    >
      <polyline points="6 9 12 15 18 9" />
    </svg>
  );
}
