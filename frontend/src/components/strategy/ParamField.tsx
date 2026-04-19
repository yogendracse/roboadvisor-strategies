"use client";

import type { ChangeEvent } from "react";

interface NumberFieldProps {
  label: string;
  help?: string;
  value: number;
  min?: number;
  max?: number;
  step?: number;
  onChange: (v: number) => void;
}

export function NumberField({
  label,
  help,
  value,
  min,
  max,
  step,
  onChange,
}: NumberFieldProps) {
  return (
    <label className="block">
      <div className="flex items-baseline justify-between">
        <span className="text-xs font-medium uppercase tracking-wide text-zinc-500">
          {label}
        </span>
        <span className="text-xs font-mono text-zinc-700 dark:text-zinc-300">
          {value}
        </span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e: ChangeEvent<HTMLInputElement>) =>
          onChange(Number(e.target.value))
        }
        className="mt-1.5 w-full accent-zinc-900 dark:accent-zinc-100"
      />
      {help && <p className="mt-1 text-[11px] text-zinc-500">{help}</p>}
    </label>
  );
}

interface SelectFieldProps<T extends string | number> {
  label: string;
  value: T;
  options: readonly { value: T; label: string }[];
  onChange: (v: T) => void;
}

export function SelectField<T extends string | number>({
  label,
  value,
  options,
  onChange,
}: SelectFieldProps<T>) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-zinc-500">
        {label}
      </span>
      <select
        value={String(value)}
        onChange={(e) => {
          const raw = e.target.value;
          const parsed = typeof options[0].value === "number" ? Number(raw) : raw;
          onChange(parsed as T);
        }}
        className="block w-full rounded-md border border-zinc-300 bg-white px-2.5 py-1.5 text-sm text-zinc-900 focus:border-zinc-500 focus:outline-none dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-100"
      >
        {options.map((opt) => (
          <option key={String(opt.value)} value={String(opt.value)}>
            {opt.label}
          </option>
        ))}
      </select>
    </label>
  );
}

interface DateRangeFieldProps {
  start: string;
  end: string;
  min: string;
  max: string;
  onChange: (start: string, end: string) => void;
}

export function DateRangeField({
  start,
  end,
  min,
  max,
  onChange,
}: DateRangeFieldProps) {
  return (
    <div>
      <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-zinc-500">
        Date range
      </span>
      <div className="flex items-center gap-1.5">
        <input
          type="date"
          value={start}
          min={min}
          max={end}
          onChange={(e) => onChange(e.target.value, end)}
          className={dateInput}
        />
        <span className="text-xs text-zinc-400">→</span>
        <input
          type="date"
          value={end}
          min={start}
          max={max}
          onChange={(e) => onChange(start, e.target.value)}
          className={dateInput}
        />
      </div>
    </div>
  );
}

const dateInput =
  "w-full rounded-md border border-zinc-300 bg-white px-2 py-1 text-xs text-zinc-900 focus:border-zinc-500 focus:outline-none dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-100";
