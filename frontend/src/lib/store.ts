import { create } from "zustand";

import type { InstrumentKind } from "./instruments";

// ── Strategy Learning store ───────────────────────────────────────────────────

interface StrategyState {
  activeInstrumentId: Record<InstrumentKind, string | null>;
  dateStart: Record<InstrumentKind, string | null>;
  dateEnd: Record<InstrumentKind, string | null>;
  setActiveInstrument: (kind: InstrumentKind, id: string | null) => void;
  setDateRange: (
    kind: InstrumentKind,
    start: string | null,
    end: string | null,
  ) => void;
}

export const useStrategyStore = create<StrategyState>((set) => ({
  activeInstrumentId: { vol: null, trend: null },
  dateStart: { vol: null, trend: null },
  dateEnd: { vol: null, trend: null },
  setActiveInstrument: (kind, id) =>
    set((s) => ({
      activeInstrumentId: { ...s.activeInstrumentId, [kind]: id },
    })),
  setDateRange: (kind, start, end) =>
    set((s) => ({
      dateStart: { ...s.dateStart, [kind]: start },
      dateEnd: { ...s.dateEnd, [kind]: end },
    })),
}));

// ── Live Signals store ────────────────────────────────────────────────────────

export type LiveStrategy = "volatility" | "trend";
export const TREND_SYSTEMS = ["10/30 MA", "30/100 MA", "80/160 MA", "30-Day Breakout"] as const;
export type TrendSystem = (typeof TREND_SYSTEMS)[number];

interface LiveState {
  liveActiveInstrumentId: string | null;
  liveDateStart: string | null;
  liveDateEnd: string | null;
  liveEnabledStrategies: LiveStrategy[];
  liveActiveTrendSystem: TrendSystem;
  /** Shared x-axis range [min, max] as ISO date strings; null = auto */
  liveXRange: [string, string] | null;

  setLiveActiveInstrument: (id: string | null) => void;
  setLiveDateRange: (start: string | null, end: string | null) => void;
  setLiveEnabledStrategies: (s: LiveStrategy[]) => void;
  setLiveActiveTrendSystem: (s: TrendSystem) => void;
  setLiveXRange: (range: [string, string] | null) => void;
}

export const useLiveStore = create<LiveState>((set) => ({
  liveActiveInstrumentId: null,
  liveDateStart: null,
  liveDateEnd: null,
  liveEnabledStrategies: ["volatility", "trend"],
  liveActiveTrendSystem: "30/100 MA",
  liveXRange: null,

  setLiveActiveInstrument: (id) => set({ liveActiveInstrumentId: id }),
  setLiveDateRange: (start, end) =>
    set({ liveDateStart: start, liveDateEnd: end }),
  setLiveEnabledStrategies: (s) => set({ liveEnabledStrategies: s }),
  setLiveActiveTrendSystem: (s) => set({ liveActiveTrendSystem: s }),
  setLiveXRange: (range) => set({ liveXRange: range }),
}));
