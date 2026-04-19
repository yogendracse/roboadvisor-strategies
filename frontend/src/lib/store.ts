import { create } from "zustand";

import type { InstrumentKind } from "./instruments";

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
