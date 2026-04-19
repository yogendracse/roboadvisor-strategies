"use client";

import { useEffect, useState } from "react";

import { AddInstrumentDialog } from "@/components/instruments/AddInstrumentDialog";
import {
  extractErrorMessage,
  useDeleteInstrument,
  useInstruments,
  type Instrument,
  type InstrumentKind,
} from "@/lib/instruments";
import { useStrategyStore } from "@/lib/store";

interface Props {
  kind: InstrumentKind;
}

export function InstrumentPicker({ kind }: Props) {
  const { data, isLoading, isError, error } = useInstruments(kind);
  const activeId = useStrategyStore((s) => s.activeInstrumentId[kind]);
  const setActive = useStrategyStore((s) => s.setActiveInstrument);
  const setRange = useStrategyStore((s) => s.setDateRange);
  const [addOpen, setAddOpen] = useState(false);
  const deleteMut = useDeleteInstrument();

  // Auto-select first instrument
  useEffect(() => {
    if (!data?.instruments.length) return;
    const current = data.instruments.find((i) => i.id === activeId);
    if (!current) {
      const first = data.instruments[0];
      setActive(kind, first.id);
      setRange(kind, first.min_date, first.max_date);
    }
  }, [data, activeId, kind, setActive, setRange]);

  const activeInst = data?.instruments.find((i) => i.id === activeId) ?? null;

  const handleSelect = (id: string) => {
    const inst = data?.instruments.find((i) => i.id === id);
    if (!inst) return;
    setActive(kind, inst.id);
    setRange(kind, inst.min_date, inst.max_date);
  };

  const handleDelete = () => {
    if (!activeInst || activeInst.builtin) return;
    if (!confirm(`Remove "${activeInst.label}"?`)) return;
    deleteMut.mutate(
      { kind: activeInst.kind, id: activeInst.id },
      {
        onSuccess: () => {
          // Select first remaining instrument after deletion
          const remaining = data?.instruments.filter((i) => i.id !== activeInst.id) ?? [];
          if (remaining.length > 0) {
            setActive(kind, remaining[0].id);
            setRange(kind, remaining[0].min_date, remaining[0].max_date);
          } else {
            setActive(kind, null);
          }
        },
      },
    );
  };

  return (
    <div>
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-zinc-500">
          Instrument
        </h3>
        <button
          onClick={() => setAddOpen(true)}
          className="inline-flex items-center gap-1 rounded-md bg-zinc-900 px-2.5 py-1 text-xs font-medium text-white transition hover:bg-zinc-800 dark:bg-zinc-50 dark:text-zinc-900 dark:hover:bg-zinc-200"
        >
          <PlusIcon /> Add
        </button>
      </div>

      {isLoading && <p className="text-sm text-zinc-500">Loading…</p>}
      {isError && (
        <p className="text-sm text-red-600 dark:text-red-400">
          {extractErrorMessage(error)}
        </p>
      )}

      {data && (
        <div className="flex items-center gap-2">
          <select
            value={activeId ?? ""}
            onChange={(e) => handleSelect(e.target.value)}
            className="flex-1 rounded-md border border-zinc-300 bg-white px-2.5 py-1.5 text-sm text-zinc-900 focus:border-zinc-500 focus:outline-none dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-100"
          >
            {data.instruments.map((inst) => (
              <option key={inst.id} value={inst.id}>
                {inst.label}
                {inst.builtin ? " ·" : ""}
              </option>
            ))}
          </select>

          {activeInst && !activeInst.builtin && (
            <button
              onClick={handleDelete}
              disabled={deleteMut.isPending}
              className="shrink-0 rounded-md border border-zinc-200 p-1.5 text-zinc-400 transition hover:border-red-200 hover:bg-red-50 hover:text-red-600 disabled:opacity-50 dark:border-zinc-700 dark:hover:border-red-900 dark:hover:bg-red-950 dark:hover:text-red-400"
              aria-label={`Remove ${activeInst.label}`}
            >
              <TrashIcon />
            </button>
          )}
        </div>
      )}

      {activeInst && (
        <p className="mt-1.5 text-xs text-zinc-500">
          {activeInst.n_rows.toLocaleString()} rows · {activeInst.min_date} → {activeInst.max_date}
          {activeInst.sector && activeInst.sector !== "Unclassified" && (
            <> · {activeInst.sector}</>
          )}
        </p>
      )}

      <AddInstrumentDialog
        open={addOpen}
        onClose={() => setAddOpen(false)}
        kind={kind}
      />
    </div>
  );
}

function PlusIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3">
      <line x1="12" y1="5" x2="12" y2="19" />
      <line x1="5" y1="12" x2="19" y2="12" />
    </svg>
  );
}

function TrashIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="3 6 5 6 21 6" />
      <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
    </svg>
  );
}
