import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import { API_BASE, ApiError, apiFetch } from "./api";
import { extractErrorMessage } from "./instruments";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface LiveInstrument {
  id: string;
  label: string;
  n_rows: number;
  min_date: string;
  max_date: string;
}

export interface LiveComputeRequest {
  instrument_id: string;
  date_start?: string | null;
  date_end?: string | null;
  strategies?: string[];
}

export interface LiveComputeResult {
  instrument_id: string;
  label: string;
  warnings: string[];
  price_figure: Record<string, unknown>;
  vol_figure?: Record<string, unknown> | null;
  current_vol_quintile?: number | null;
  current_vol_label?: string | null;
  trend_figures: Record<string, Record<string, unknown>>;
  current_trend_signals: Record<string, number>;
  current_trend_labels: Record<string, string>;
}

// ── Query keys ────────────────────────────────────────────────────────────────

const LIVE_INSTRUMENTS_KEY = ["live-instruments"] as const;

// ── Hooks ─────────────────────────────────────────────────────────────────────

export function useLiveInstruments() {
  return useQuery({
    queryKey: LIVE_INSTRUMENTS_KEY,
    queryFn: () =>
      apiFetch<{ instruments: LiveInstrument[] }>("/api/live/instruments"),
    staleTime: 30_000,
  });
}

export function useAddLiveYfinance() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (ticker: string) =>
      apiFetch<LiveInstrument>("/api/live/instruments/yfinance", {
        method: "POST",
        body: JSON.stringify({ ticker }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: LIVE_INSTRUMENTS_KEY });
    },
  });
}

export function useAddLiveUpload() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ label, file }: { label: string; file: File }) => {
      const form = new FormData();
      form.append("label", label);
      form.append("file", file);
      const res = await fetch(`${API_BASE}/api/live/instruments/upload`, {
        method: "POST",
        body: form,
      });
      if (!res.ok) {
        let body: unknown = null;
        try {
          body = await res.json();
        } catch {
          body = await res.text();
        }
        throw new ApiError(`${res.status} ${res.statusText}`, res.status, body);
      }
      return (await res.json()) as LiveInstrument;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: LIVE_INSTRUMENTS_KEY });
    },
  });
}

export function useRefreshLiveInstrument() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      apiFetch<LiveInstrument>(`/api/live/instruments/${id}/refresh`, {
        method: "POST",
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: LIVE_INSTRUMENTS_KEY });
    },
  });
}

export function useDeleteLiveInstrument() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) => {
      const res = await fetch(`${API_BASE}/api/live/instruments/${id}`, {
        method: "DELETE",
      });
      if (!res.ok) {
        throw new ApiError(
          `${res.status} ${res.statusText}`,
          res.status,
          await res.text().catch(() => null),
        );
      }
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: LIVE_INSTRUMENTS_KEY });
    },
  });
}

export function useLiveCompute(
  params: LiveComputeRequest | null,
) {
  return useQuery({
    queryKey: ["live-compute", params],
    queryFn: () =>
      apiFetch<LiveComputeResult>("/api/live/compute", {
        method: "POST",
        body: JSON.stringify(params),
      }),
    enabled: params !== null && Boolean(params.instrument_id),
    staleTime: 60_000,
    placeholderData: (prev) => prev,
  });
}

export { extractErrorMessage };
