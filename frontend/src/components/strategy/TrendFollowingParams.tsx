"use client";

import {
  DateRangeField,
  NumberField,
  SelectField,
} from "./ParamField";

export interface TrendFollowingParamValues {
  date_start: string | null;
  date_end: string | null;
  tc_bps: number;
  use_ema: boolean;
  signal_asset: string | null;
  signal_system: string;
  best_systems: Record<string, string>;
}

export const defaultTrendParams: TrendFollowingParamValues = {
  date_start: null,
  date_end: null,
  tc_bps: 1,
  use_ema: false,
  signal_asset: null,
  signal_system: "30/100 MA",
  best_systems: {},
};

export const TREND_SYSTEMS = [
  { value: "10/30 MA", label: "10/30 MA" },
  { value: "30/100 MA", label: "30/100 MA" },
  { value: "80/160 MA", label: "80/160 MA" },
  { value: "30-Day Breakout", label: "30-Day Breakout" },
] as const;

interface Props {
  value: TrendFollowingParamValues;
  onChange: (v: TrendFollowingParamValues) => void;
  minDate?: string | null;
  maxDate?: string | null;
  assetLabels: string[];
}

export function TrendFollowingParams({
  value,
  onChange,
  minDate,
  maxDate,
  assetLabels,
}: Props) {
  const update = (patch: Partial<TrendFollowingParamValues>) =>
    onChange({ ...value, ...patch });

  const start = value.date_start ?? minDate ?? "";
  const end = value.date_end ?? maxDate ?? "";

  const assetOptions = assetLabels.map((a) => ({ value: a, label: a }));
  const currentSignalAsset =
    value.signal_asset && assetLabels.includes(value.signal_asset)
      ? value.signal_asset
      : assetLabels[0] ?? "";

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
        label="Transaction cost (bps)"
        help="Applied each time the signal flips"
        value={value.tc_bps}
        min={0}
        max={5}
        step={0.5}
        onChange={(v) => update({ tc_bps: v })}
      />

      <label className="flex items-center justify-between gap-3">
        <span className="text-xs font-medium uppercase tracking-wide text-zinc-500">
          Use EMA instead of SMA
        </span>
        <input
          type="checkbox"
          checked={value.use_ema}
          onChange={(e) => update({ use_ema: e.target.checked })}
          className="h-4 w-4 accent-zinc-900 dark:accent-zinc-100"
        />
      </label>

      {assetLabels.length > 0 && (
        <div className="space-y-2 rounded-lg border border-zinc-200 bg-zinc-50 p-2.5 dark:border-zinc-800 dark:bg-zinc-950/40">
          <div className="text-[11px] font-medium uppercase tracking-wide text-zinc-500">
            Signal chart
          </div>
          <SelectField
            label="Asset"
            value={currentSignalAsset}
            options={assetOptions}
            onChange={(v) => update({ signal_asset: v })}
          />
          <SelectField
            label="System"
            value={value.signal_system}
            options={TREND_SYSTEMS}
            onChange={(v) => update({ signal_system: v })}
          />
        </div>
      )}
    </div>
  );
}
