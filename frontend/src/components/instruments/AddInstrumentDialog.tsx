"use client";

import { useState } from "react";

import { Modal } from "@/components/ui/Modal";
import {
  extractErrorMessage,
  useAddUpload,
  useAddYfinance,
  useSectors,
  type InstrumentKind,
} from "@/lib/instruments";

interface Props {
  open: boolean;
  onClose: () => void;
  kind: InstrumentKind;
}

type Tab = "yfinance" | "upload";

export function AddInstrumentDialog({ open, onClose, kind }: Props) {
  const [tab, setTab] = useState<Tab>("yfinance");
  const [ticker, setTicker] = useState("");
  const [label, setLabel] = useState("");
  const [sector, setSector] = useState<string>("Unclassified");
  const [file, setFile] = useState<File | null>(null);

  const sectorsQuery = useSectors();
  const yf = useAddYfinance();
  const upload = useAddUpload();

  const reset = () => {
    setTicker("");
    setLabel("");
    setFile(null);
    setSector("Unclassified");
    yf.reset();
    upload.reset();
  };

  const closeAndReset = () => {
    reset();
    onClose();
  };

  const submitYf = async () => {
    if (!ticker.trim()) return;
    await yf.mutateAsync({
      ticker: ticker.trim().toUpperCase(),
      kind,
      sector: kind === "vol" ? sector : null,
    });
    closeAndReset();
  };

  const submitUpload = async () => {
    if (!file || !label.trim()) return;
    await upload.mutateAsync({
      label: label.trim(),
      kind,
      sector: kind === "vol" ? sector : null,
      file,
    });
    closeAndReset();
  };

  return (
    <Modal open={open} onClose={closeAndReset} title="Add instrument">
      <div className="mb-4 flex gap-2 border-b border-zinc-200 dark:border-zinc-800">
        <TabButton active={tab === "yfinance"} onClick={() => setTab("yfinance")}>
          yfinance
        </TabButton>
        <TabButton active={tab === "upload"} onClick={() => setTab("upload")}>
          Upload CSV / Excel
        </TabButton>
      </div>

      {tab === "yfinance" ? (
        <div className="space-y-3">
          <Field label="Ticker">
            <input
              autoFocus
              value={ticker}
              onChange={(e) => setTicker(e.target.value)}
              placeholder="AAPL, MSFT, GLD…"
              className={inputClass}
            />
          </Field>
          {kind === "vol" && (
            <SectorField
              sectors={sectorsQuery.data ?? []}
              value={sector}
              onChange={setSector}
            />
          )}
          {yf.isError && (
            <ErrorNote>{extractErrorMessage(yf.error)}</ErrorNote>
          )}
          <button
            onClick={submitYf}
            disabled={!ticker.trim() || yf.isPending}
            className={primaryButtonClass}
          >
            {yf.isPending ? "Fetching…" : "Fetch & add"}
          </button>
        </div>
      ) : (
        <div className="space-y-3">
          <Field label="Label">
            <input
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder="My Stock"
              className={inputClass}
            />
          </Field>
          <Field label="File">
            <input
              type="file"
              accept=".csv,.xlsx,.xls"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              className="block w-full text-sm text-zinc-700 file:mr-3 file:rounded-md file:border-0 file:bg-zinc-100 file:px-3 file:py-1.5 file:text-sm file:font-medium hover:file:bg-zinc-200 dark:text-zinc-300 dark:file:bg-zinc-800 dark:hover:file:bg-zinc-700"
            />
            <p className="mt-1 text-xs text-zinc-500">
              File must have a Date column and a Close (or Price / Adj Close)
              column.
            </p>
          </Field>
          {kind === "vol" && (
            <SectorField
              sectors={sectorsQuery.data ?? []}
              value={sector}
              onChange={setSector}
            />
          )}
          {upload.isError && (
            <ErrorNote>{extractErrorMessage(upload.error)}</ErrorNote>
          )}
          <button
            onClick={submitUpload}
            disabled={!file || !label.trim() || upload.isPending}
            className={primaryButtonClass}
          >
            {upload.isPending ? "Uploading…" : "Add uploaded file"}
          </button>
        </div>
      )}
    </Modal>
  );
}

function TabButton({
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

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-zinc-500">
        {label}
      </span>
      {children}
    </label>
  );
}

function SectorField({
  sectors,
  value,
  onChange,
}: {
  sectors: string[];
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <Field label="Sector">
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className={inputClass}
      >
        {sectors.map((s) => (
          <option key={s} value={s}>
            {s}
          </option>
        ))}
      </select>
    </Field>
  );
}

function ErrorNote({ children }: { children: React.ReactNode }) {
  return (
    <p className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300">
      {children}
    </p>
  );
}

const inputClass =
  "block w-full rounded-md border border-zinc-300 bg-white px-3 py-1.5 text-sm text-zinc-900 placeholder:text-zinc-400 focus:border-zinc-500 focus:outline-none dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-100";

const primaryButtonClass =
  "inline-flex w-full items-center justify-center rounded-md bg-zinc-900 px-4 py-2 text-sm font-medium text-white shadow-sm transition hover:bg-zinc-800 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-zinc-50 dark:text-zinc-900 dark:hover:bg-zinc-200";
