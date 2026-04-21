"use client";

import { NumberField, SelectField } from "./ParamField";

export interface CounterTrendParamValues {
  date_start: string | null;
  date_end: string | null;
  // Tab 1 — Range Exhaustion
  p_value: number;
  // Tab 2 — Doji
  epsilon_oc: number;
  epsilon_gw: number;
  epsilon_df: number;
  trend_length: number;
  bb_window: number;
  bb_std: number;
  // Tab 3 — Spread
  pairs_lookback: number;
  entry_z: number;
  // Tab 4 — Drawdown
  tier1_pct: number;
  tier2_pct: number;
  // Tab 5 — Renko
  brick_mode: "atr" | "fixed";
  fixed_brick: number;
  atr_period: number;
  min_bricks: number;
}

export const defaultCounterTrendParams: CounterTrendParamValues = {
  date_start: null,
  date_end: null,
  p_value: 2.2,
  epsilon_oc: 0.05,
  epsilon_gw: 0.10,
  epsilon_df: 0.10,
  trend_length: 3,
  bb_window: 20,
  bb_std: 2.0,
  pairs_lookback: 60,
  entry_z: 2.0,
  tier1_pct: 0.25,
  tier2_pct: 0.33,
  brick_mode: "atr",
  fixed_brick: 20,
  atr_period: 14,
  min_bricks: 3,
};

const BRICK_MODES = [
  { value: "atr",   label: "ATR-based" },
  { value: "fixed", label: "Fixed size" },
] as const;

interface Props {
  value: CounterTrendParamValues;
  onChange: (v: CounterTrendParamValues) => void;
}

export function CounterTrendParams({ value, onChange }: Props) {
  const update = (patch: Partial<CounterTrendParamValues>) =>
    onChange({ ...value, ...patch });

  return (
    <div className="space-y-5">
      {/* ── Tab 1: Range Exhaustion ── */}
      <Section label="📐 Range Exhaustion">
        <NumberField
          label="P — retrace multiplier"
          help="Entry = PrvHiWRoll − P × AvgRange"
          value={value.p_value}
          min={0.5}
          max={3.0}
          step={0.1}
          onChange={(v) => update({ p_value: v })}
        />
      </Section>

      {/* ── Tab 2: Doji ── */}
      <Section label="🕯️ Doji Detection">
        <NumberField
          label="ε body/range (Doji)"
          help="Body < ε × Range → Doji"
          value={value.epsilon_oc}
          min={0.01}
          max={0.25}
          step={0.01}
          onChange={(v) => update({ epsilon_oc: v })}
        />
        <NumberField
          label="ε Graveyard wick"
          help="Lower wick < ε × Range"
          value={value.epsilon_gw}
          min={0.01}
          max={0.40}
          step={0.01}
          onChange={(v) => update({ epsilon_gw: v })}
        />
        <NumberField
          label="ε Dragonfly wick"
          help="Upper wick < ε × Range"
          value={value.epsilon_df}
          min={0.01}
          max={0.40}
          step={0.01}
          onChange={(v) => update({ epsilon_df: v })}
        />
        <NumberField
          label="Trend context (days)"
          help="Prior N days must all trend one way"
          value={value.trend_length}
          min={1}
          max={10}
          step={1}
          onChange={(v) => update({ trend_length: v })}
        />
        <NumberField
          label="BB window"
          value={value.bb_window}
          min={10}
          max={60}
          step={5}
          onChange={(v) => update({ bb_window: v })}
        />
        <NumberField
          label="BB std dev"
          value={value.bb_std}
          min={1.0}
          max={3.0}
          step={0.5}
          onChange={(v) => update({ bb_std: v })}
        />
      </Section>

      {/* ── Tab 3: Spread ── */}
      <Section label="📊 Spread System">
        <NumberField
          label="Lookback window (days)"
          value={value.pairs_lookback}
          min={20}
          max={250}
          step={10}
          onChange={(v) => update({ pairs_lookback: v })}
        />
        <NumberField
          label="Entry Z-score threshold"
          help="Long < −Z, Short > +Z"
          value={value.entry_z}
          min={0.5}
          max={4.0}
          step={0.5}
          onChange={(v) => update({ entry_z: v })}
        />
      </Section>

      {/* ── Tab 4: Drawdown ── */}
      <Section label="📉 Drawdown Entry">
        <NumberField
          label="Tier 1 threshold"
          help="e.g. 0.25 = enter at −25 % DD"
          value={value.tier1_pct}
          min={0.05}
          max={0.60}
          step={0.05}
          onChange={(v) => update({ tier1_pct: v })}
        />
        <NumberField
          label="Tier 2 threshold"
          help="e.g. 0.33 = enter at −33 % DD"
          value={value.tier2_pct}
          min={0.05}
          max={0.70}
          step={0.05}
          onChange={(v) => update({ tier2_pct: v })}
        />
      </Section>

      {/* ── Tab 5: Renko ── */}
      <Section label="🧱 Renko">
        <SelectField
          label="Brick size mode"
          value={value.brick_mode}
          options={BRICK_MODES}
          onChange={(v) => update({ brick_mode: v as "atr" | "fixed" })}
        />
        {value.brick_mode === "atr" ? (
          <NumberField
            label="ATR period"
            value={value.atr_period}
            min={5}
            max={60}
            step={1}
            onChange={(v) => update({ atr_period: v })}
          />
        ) : (
          <NumberField
            label="Fixed brick size"
            value={value.fixed_brick}
            min={1}
            max={500}
            step={5}
            onChange={(v) => update({ fixed_brick: v })}
          />
        )}
        <NumberField
          label="Min bricks for trend"
          help="Consecutive bricks before CT signal"
          value={value.min_bricks}
          min={2}
          max={10}
          step={1}
          onChange={(v) => update({ min_bricks: v })}
        />
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
