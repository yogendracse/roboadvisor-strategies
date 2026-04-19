"use client";

import { useMemo } from "react";

import {
  DateRangeField,
  NumberField,
  SelectField,
} from "./ParamField";

export interface VolAnalysisParamValues {
  window: number;
  norm_win: number;
  n_quantiles: number;
  long_q: number;
  short_q: number;
  date_start: string | null;
  date_end: string | null;
}

export const defaultVolParams: VolAnalysisParamValues = {
  window: 20,
  norm_win: 250,
  n_quantiles: 5,
  long_q: 1,
  short_q: 5,
  date_start: null,
  date_end: null,
};

interface Props {
  value: VolAnalysisParamValues;
  onChange: (v: VolAnalysisParamValues) => void;
  minDate?: string | null;
  maxDate?: string | null;
}

export function VolAnalysisParams({
  value,
  onChange,
  minDate,
  maxDate,
}: Props) {
  const qOptions = useMemo(
    () =>
      Array.from({ length: value.n_quantiles }, (_, i) => ({
        value: i + 1,
        label: `Q${i + 1}`,
      })),
    [value.n_quantiles],
  );

  const update = (patch: Partial<VolAnalysisParamValues>) =>
    onChange({ ...value, ...patch });

  const start = value.date_start ?? minDate ?? "";
  const end = value.date_end ?? maxDate ?? "";

  return (
    <div className="space-y-4">
      {minDate && maxDate && (
        <DateRangeField
          start={start}
          end={end}
          min={minDate}
          max={maxDate}
          onChange={(s, e) => update({ date_start: s, date_end: e })}
        />
      )}

      <NumberField
        label="Analysis window (days)"
        help="Window for vol20, ret20, fret20"
        value={value.window}
        min={5}
        max={63}
        step={1}
        onChange={(v) => update({ window: v })}
      />
      <NumberField
        label="Z-score window (days)"
        help="Trailing window for rolling Z-score"
        value={value.norm_win}
        min={60}
        max={500}
        step={10}
        onChange={(v) => update({ norm_win: v })}
      />
      <NumberField
        label="Number of quantiles"
        value={value.n_quantiles}
        min={3}
        max={10}
        step={1}
        onChange={(v) => {
          const clamp = (q: number) => Math.min(q, v);
          update({
            n_quantiles: v,
            long_q: clamp(value.long_q),
            short_q: clamp(value.short_q),
          });
        }}
      />

      <div className="grid grid-cols-2 gap-2">
        <SelectField
          label="Long"
          value={value.long_q}
          options={qOptions}
          onChange={(v) => update({ long_q: v })}
        />
        <SelectField
          label="Short"
          value={value.short_q}
          options={qOptions}
          onChange={(v) => update({ short_q: v })}
        />
      </div>
    </div>
  );
}
