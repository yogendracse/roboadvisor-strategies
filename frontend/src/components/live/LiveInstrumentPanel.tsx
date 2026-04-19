"use client";

import { useEffect, useState } from "react";

import { Modal } from "@/components/ui/Modal";
import {
  extractErrorMessage,
  useAddLiveUpload,
  useAddLiveYfinance,
  useDeleteLiveInstrument,
  useLiveInstruments,
  useRefreshLiveInstrument,
  type LiveInstrument,
} from "@/lib/live";
import { useLiveStore } from "@/lib/store";

// ── Staleness helpers ─────────────────────────────────────────────────────────

/** Days elapsed since an ISO date string. */
function daysSince(isoDate: string): number {
  const diff = Date.now() - new Date(isoDate).getTime();
  return Math.floor(diff / 86_400_000);
}

/** True when max_date is more than 1 day old (accounts for weekends). */
function isStale(inst: LiveInstrument): boolean {
  return daysSince(inst.max_date) > 1;
}

function stalenessLabel(inst: LiveInstrument): string {
  const d = daysSince(inst.max_date);
  if (d === 0) return "up to date";
  if (d === 1) return "1 day old";
  return `${d} days old`;
}

// ── Main panel ────────────────────────────────────────────────────────────────

export function LiveInstrumentPanel() {
  const { data, isLoading, isError, error } = useLiveInstruments();
  const activeId = useLiveStore((s) => s.liveActiveInstrumentId);
  const setActive = useLiveStore((s) => s.setLiveActiveInstrument);
  const setDateRange = useLiveStore((s) => s.setLiveDateRange);
  const [addOpen, setAddOpen] = useState(false);

  const deleteMut = useDeleteLiveInstrument();
  const refreshMut = useRefreshLiveInstrument();

  const instruments = data?.instruments ?? [];
  const activeInst = instruments.find((i) => i.id === activeId) ?? null;

  // Auto-select first instrument when list loads
  useEffect(() => {
    if (!instruments.length) return;
    const current = instruments.find((i) => i.id === activeId);
    if (!current) select(instruments[0]);
  });

  function select(inst: LiveInstrument) {
    setActive(inst.id);
    setDateRange(twoYearsBefore(inst.max_date), inst.max_date);
  }

  function handleDelete() {
    if (!activeInst) return;
    if (!confirm(`Remove "${activeInst.label}"?`)) return;
    deleteMut.mutate(activeInst.id, {
      onSuccess: () => {
        const remaining = instruments.filter((i) => i.id !== activeInst.id);
        remaining.length > 0 ? select(remaining[0]) : setActive(null);
      },
    });
  }

  function handleRefresh() {
    if (!activeInst) return;
    refreshMut.mutate(activeInst.id, {
      onSuccess: (updated) => {
        // Extend the date range to include newly fetched data
        setDateRange(twoYearsBefore(updated.max_date), updated.max_date);
      },
    });
  }

  return (
    <div>
      {/* Header row */}
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-zinc-500">
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

      {!isLoading && instruments.length === 0 && (
        <p className="text-xs text-zinc-400">
          No instruments yet — click Add to fetch from yfinance or upload a CSV.
        </p>
      )}

      {instruments.length > 0 && (
        <>
          {/* Dropdown + delete */}
          <div className="flex items-center gap-2">
            <select
              value={activeId ?? ""}
              onChange={(e) => {
                const inst = instruments.find((i) => i.id === e.target.value);
                if (inst) select(inst);
              }}
              className="flex-1 rounded-md border border-zinc-300 bg-white px-2.5 py-1.5 text-sm text-zinc-900 focus:border-zinc-500 focus:outline-none dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-100"
            >
              {instruments.map((inst) => (
                <option key={inst.id} value={inst.id}>
                  {inst.label}
                  {isStale(inst) ? " ·" : ""}
                </option>
              ))}
            </select>

            {activeInst && (
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

          {/* Metadata + staleness */}
          {activeInst && (
            <div className="mt-1.5 space-y-1">
              <p className="text-xs text-zinc-500">
                {activeInst.n_rows.toLocaleString()} rows · {activeInst.min_date} → {activeInst.max_date}
              </p>

              {isStale(activeInst) && (
                <div className="flex items-center gap-2">
                  <span className="text-[11px] text-amber-600 dark:text-amber-400">
                    Data {stalenessLabel(activeInst)}
                  </span>
                  {refreshMut.isError && (
                    <span className="text-[11px] text-red-500">
                      {extractErrorMessage(refreshMut.error)}
                    </span>
                  )}
                  <button
                    onClick={handleRefresh}
                    disabled={refreshMut.isPending}
                    className="ml-auto inline-flex items-center gap-1 rounded-md border border-zinc-200 px-2 py-0.5 text-[11px] font-medium text-zinc-600 transition hover:border-zinc-400 hover:text-zinc-900 disabled:opacity-50 dark:border-zinc-700 dark:text-zinc-400 dark:hover:border-zinc-500 dark:hover:text-zinc-100"
                  >
                    <RefreshIcon spinning={refreshMut.isPending} />
                    {refreshMut.isPending ? "Refreshing…" : "Refresh"}
                  </button>
                </div>
              )}
            </div>
          )}
        </>
      )}

      <AddLiveInstrumentDialog
        open={addOpen}
        existingInstruments={instruments}
        onClose={() => setAddOpen(false)}
        onAdded={(inst) => {
          setAddOpen(false);
          select(inst);
        }}
        onSelect={(inst) => {
          setAddOpen(false);
          select(inst);
        }}
      />
    </div>
  );
}

// ── Add dialog ────────────────────────────────────────────────────────────────

function AddLiveInstrumentDialog({
  open,
  existingInstruments,
  onClose,
  onAdded,
  onSelect,
}: {
  open: boolean;
  existingInstruments: LiveInstrument[];
  onClose: () => void;
  onAdded: (inst: LiveInstrument) => void;
  onSelect: (inst: LiveInstrument) => void;
}) {
  const [tab, setTab] = useState<"yfinance" | "upload">("yfinance");
  const [ticker, setTicker] = useState("");
  const [label, setLabel] = useState("");
  const [file, setFile] = useState<File | null>(null);

  const yf = useAddLiveYfinance();
  const upload = useAddLiveUpload();
  const refreshMut = useRefreshLiveInstrument();

  function reset() {
    setTicker("");
    setLabel("");
    setFile(null);
    yf.reset();
    upload.reset();
    refreshMut.reset();
  }

  function close() {
    reset();
    onClose();
  }

  // Check if the typed ticker already exists
  const normalised = ticker.trim().toUpperCase();
  const existing = normalised
    ? existingInstruments.find(
        (i) => i.id.toUpperCase() === normalised || i.label.toUpperCase() === normalised,
      )
    : null;

  async function submitYf() {
    if (!normalised) return;
    const inst = await yf.mutateAsync(normalised);
    reset();
    onAdded(inst);
  }

  async function submitRefresh() {
    if (!existing) return;
    const inst = await refreshMut.mutateAsync(existing.id);
    reset();
    onAdded(inst);
  }

  async function submitUpload() {
    if (!file || !label.trim()) return;
    const inst = await upload.mutateAsync({ label: label.trim(), file });
    reset();
    onAdded(inst);
  }

  return (
    <Modal open={open} onClose={close} title="Add live instrument">
      <div className="mb-4 flex gap-2 border-b border-zinc-200 dark:border-zinc-800">
        <TabBtn active={tab === "yfinance"} onClick={() => setTab("yfinance")}>
          yfinance
        </TabBtn>
        <TabBtn active={tab === "upload"} onClick={() => setTab("upload")}>
          Upload CSV / Excel
        </TabBtn>
      </div>

      {tab === "yfinance" ? (
        <div className="space-y-3">
          <FieldRow label="Ticker">
            <input
              autoFocus
              value={ticker}
              onChange={(e) => setTicker(e.target.value)}
              onKeyDown={(e) => !existing && e.key === "Enter" && submitYf()}
              placeholder="AAPL, SPY, GLD…"
              className={inputCls}
            />
          </FieldRow>

          {/* Already-in-list notice */}
          {existing && (
            <div className="rounded-md border border-zinc-200 bg-zinc-50 px-3 py-2.5 dark:border-zinc-700 dark:bg-zinc-800">
              <p className="text-xs font-medium text-zinc-700 dark:text-zinc-200">
                Already in your list
              </p>
              <p className="mt-0.5 text-[11px] text-zinc-500">
                {existing.n_rows.toLocaleString()} rows · {existing.min_date} → {existing.max_date}
                {isStale(existing) && (
                  <span className="ml-1.5 text-amber-600 dark:text-amber-400">
                    ({stalenessLabel(existing)})
                  </span>
                )}
              </p>
              <div className="mt-2 flex gap-2">
                <button
                  onClick={() => { reset(); onSelect(existing); }}
                  className="flex-1 rounded-md border border-zinc-300 px-3 py-1.5 text-xs font-medium text-zinc-700 transition hover:border-zinc-500 dark:border-zinc-600 dark:text-zinc-300 dark:hover:border-zinc-400"
                >
                  Use existing
                </button>
                {isStale(existing) && (
                  <button
                    onClick={submitRefresh}
                    disabled={refreshMut.isPending}
                    className="flex-1 rounded-md bg-zinc-900 px-3 py-1.5 text-xs font-medium text-white transition hover:bg-zinc-700 disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-300"
                  >
                    {refreshMut.isPending ? "Refreshing…" : "Refresh data"}
                  </button>
                )}
              </div>
              {refreshMut.isError && (
                <ErrorNote>{extractErrorMessage(refreshMut.error)}</ErrorNote>
              )}
            </div>
          )}

          {!existing && (
            <>
              {yf.isError && <ErrorNote>{extractErrorMessage(yf.error)}</ErrorNote>}
              <button
                onClick={submitYf}
                disabled={!normalised || yf.isPending}
                className={btnCls}
              >
                {yf.isPending ? "Fetching…" : "Fetch & add"}
              </button>
            </>
          )}
        </div>
      ) : (
        <div className="space-y-3">
          <FieldRow label="Label">
            <input
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder="My Asset"
              className={inputCls}
            />
          </FieldRow>
          <FieldRow label="File">
            <input
              type="file"
              accept=".csv,.xlsx,.xls"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              className="block w-full text-sm text-zinc-700 file:mr-3 file:rounded-md file:border-0 file:bg-zinc-100 file:px-3 file:py-1.5 file:text-sm file:font-medium hover:file:bg-zinc-200 dark:text-zinc-300 dark:file:bg-zinc-800 dark:hover:file:bg-zinc-700"
            />
            <p className="mt-1 text-xs text-zinc-500">
              Needs a Date column and a Close (or Price) column.
            </p>
          </FieldRow>
          {upload.isError && (
            <ErrorNote>{extractErrorMessage(upload.error)}</ErrorNote>
          )}
          <button
            onClick={submitUpload}
            disabled={!file || !label.trim() || upload.isPending}
            className={btnCls}
          >
            {upload.isPending ? "Uploading…" : "Add uploaded file"}
          </button>
        </div>
      )}
    </Modal>
  );
}

// ── Helpers & micro-components ────────────────────────────────────────────────

function twoYearsBefore(isoDate: string): string {
  const d = new Date(isoDate);
  d.setFullYear(d.getFullYear() - 2);
  return d.toISOString().slice(0, 10);
}

function TabBtn({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={`-mb-px border-b-2 px-3 py-2 text-sm font-medium transition ${
        active
          ? "border-zinc-900 text-zinc-900 dark:border-zinc-50 dark:text-zinc-50"
          : "border-transparent text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200"
      }`}
    >
      {children}
    </button>
  );
}

function FieldRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-zinc-500">
        {label}
      </span>
      {children}
    </label>
  );
}

function ErrorNote({ children }: { children: React.ReactNode }) {
  return (
    <p className="mt-1.5 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300">
      {children}
    </p>
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

function RefreshIcon({ spinning }: { spinning: boolean }) {
  return (
    <svg
      width="11"
      height="11"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      style={spinning ? { animation: "spin 1s linear infinite" } : undefined}
    >
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
      <polyline points="23 4 23 10 17 10" />
      <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10" />
    </svg>
  );
}

const inputCls =
  "block w-full rounded-md border border-zinc-300 bg-white px-3 py-1.5 text-sm text-zinc-900 placeholder:text-zinc-400 focus:border-zinc-500 focus:outline-none dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-100";

const btnCls =
  "inline-flex w-full items-center justify-center rounded-md bg-zinc-900 px-4 py-2 text-sm font-medium text-white shadow-sm transition hover:bg-zinc-800 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-zinc-50 dark:text-zinc-900 dark:hover:bg-zinc-200";
