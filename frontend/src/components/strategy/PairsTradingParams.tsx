"use client";

import { NumberField, SelectField } from "./ParamField";

export interface PairsTradingParamValues {
  entry_threshold: number;
  long_entry: number;
  short_entry: number;
  long_exit_cap: number;
  short_exit_cap: number;
  holding_period: number;
  active_N: 5 | 10 | 20;
  selected_day: string | null;
}

export const defaultPairsTradingParams: PairsTradingParamValues = {
  entry_threshold: 1.0,
  long_entry: -1.0,
  short_entry: 1.0,
  long_exit_cap: 1.0,
  short_exit_cap: -1.0,
  holding_period: 5,
  active_N: 10,
  selected_day: null,
};

const N_OPTIONS = [
  { value: 5,  label: "N = 5  (fast)" },
  { value: 10, label: "N = 10 (default)" },
  { value: 20, label: "N = 20 (slow)" },
] as const;

interface Props {
  value: PairsTradingParamValues;
  onChange: (v: PairsTradingParamValues) => void;
}

export function PairsTradingParams({ value, onChange }: Props) {
  const update = (patch: Partial<PairsTradingParamValues>) =>
    onChange({ ...value, ...patch });

  // Symmetric-threshold helper: moving the single entry slider mirrors onto
  // long_entry / short_entry / caps, so the visual threshold and the engine
  // stay in sync unless the user deliberately splits them below.
  const updateSymmetric = (t: number) =>
    update({
      entry_threshold: t,
      long_entry: -t,
      short_entry: t,
      long_exit_cap: t,
      short_exit_cap: -t,
    });

  return (
    <div className="space-y-5">
      {/* ── Signal thresholds (symmetric shortcut) ── */}
      <Section label="📶 Signal Threshold">
        <NumberField
          label="Entry threshold ±σ"
          help="Symmetric shortcut: sets long/short entries & caps at ±this"
          value={value.entry_threshold}
          min={0.25}
          max={3.5}
          step={0.25}
          onChange={updateSymmetric}
        />
      </Section>

      {/* ── Asymmetric engine params ── */}
      <Section label="🎛️ Engine (asymmetric)">
        <NumberField
          label="Long entry (−σ)"
          help="Go long spread when zdiff ≤ this"
          value={value.long_entry}
          min={-3.5}
          max={0.0}
          step={0.25}
          onChange={(v) => update({ long_entry: v })}
        />
        <NumberField
          label="Short entry (+σ)"
          help="Go short spread when zdiff ≥ this"
          value={value.short_entry}
          min={0.0}
          max={3.5}
          step={0.25}
          onChange={(v) => update({ short_entry: v })}
        />
        <NumberField
          label="Long profit cap"
          help="Exit long when zdiff ≥ this"
          value={value.long_exit_cap}
          min={-1.0}
          max={3.5}
          step={0.25}
          onChange={(v) => update({ long_exit_cap: v })}
        />
        <NumberField
          label="Short profit cap"
          help="Exit short when zdiff ≤ this"
          value={value.short_exit_cap}
          min={-3.5}
          max={1.0}
          step={0.25}
          onChange={(v) => update({ short_exit_cap: v })}
        />
        <NumberField
          label="Holding period (days)"
          help="Force-exit after this many bars"
          value={value.holding_period}
          min={1}
          max={30}
          step={1}
          onChange={(v) => update({ holding_period: v })}
        />
      </Section>

      {/* ── Drill-down target ── */}
      <Section label="🔎 Drill-down horizon">
        <SelectField
          label="Active N"
          value={value.active_N}
          options={N_OPTIONS}
          onChange={(v) =>
            update({ active_N: Number(v) as 5 | 10 | 20 })
          }
        />
        <label className="block">
          <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-zinc-500">
            Strategy-in-Action day
          </span>
          <input
            type="date"
            value={value.selected_day ?? ""}
            onChange={(e) =>
              update({ selected_day: e.target.value || null })
            }
            className="w-full rounded-md border border-zinc-300 bg-white px-2 py-1 text-xs text-zinc-900 focus:border-zinc-500 focus:outline-none dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-100"
          />
          <p className="mt-1 text-[11px] text-zinc-500">
            Empty = last row. Drives Tab 8 explainer.
          </p>
        </label>
      </Section>
    </div>
  );
}

function Section({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-2 rounded-lg border border-zinc-200 bg-zinc-50 p-2.5 dark:border-zinc-800 dark:bg-zinc-950/40">
      <div className="text-[11px] font-medium uppercase tracking-wide text-zinc-500">
        {label}
      </div>
      <div className="space-y-3">{children}</div>
    </div>
  );
}
