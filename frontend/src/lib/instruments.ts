import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import { API_BASE, ApiError, apiFetch } from "./api";
import type { components } from "@/types/api";

export type InstrumentKind = components["schemas"]["InstrumentKind"];
export type Instrument = components["schemas"]["Instrument"];
export type InstrumentList = components["schemas"]["InstrumentList"];
export type InstrumentSeries = components["schemas"]["InstrumentSeries"];

const instrumentsKey = (kind: InstrumentKind) => ["instruments", kind] as const;

export function useInstruments(kind: InstrumentKind) {
  return useQuery({
    queryKey: instrumentsKey(kind),
    queryFn: () =>
      apiFetch<InstrumentList>(`/api/instruments?kind=${kind}`),
    staleTime: 30_000,
  });
}

export function useSectors() {
  return useQuery({
    queryKey: ["sectors"],
    queryFn: () => apiFetch<string[]>("/api/instruments/sectors"),
    staleTime: 5 * 60_000,
  });
}

export interface AddYfinanceInput {
  ticker: string;
  kind: InstrumentKind;
  sector?: string | null;
}

export function useAddYfinance() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: AddYfinanceInput) =>
      apiFetch<{ instrument: Instrument }>("/api/instruments/yfinance", {
        method: "POST",
        body: JSON.stringify(input),
      }),
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: instrumentsKey(variables.kind) });
    },
  });
}

export interface AddUploadInput {
  label: string;
  kind: InstrumentKind;
  sector?: string | null;
  file: File;
}

export function useAddUpload() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (input: AddUploadInput) => {
      const form = new FormData();
      form.append("label", input.label);
      form.append("kind", input.kind);
      if (input.sector) form.append("sector", input.sector);
      form.append("file", input.file);
      const res = await fetch(`${API_BASE}/api/instruments/upload`, {
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
      return (await res.json()) as { instrument: Instrument };
    },
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: instrumentsKey(variables.kind) });
    },
  });
}

export function useDeleteInstrument() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({
      kind,
      id,
    }: {
      kind: InstrumentKind;
      id: string;
    }) => {
      const res = await fetch(
        `${API_BASE}/api/instruments/${kind}/${id}`,
        { method: "DELETE" },
      );
      if (!res.ok) {
        throw new ApiError(
          `${res.status} ${res.statusText}`,
          res.status,
          await res.text().catch(() => null),
        );
      }
    },
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: instrumentsKey(variables.kind) });
    },
  });
}

export function useUpdateSector() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, sector }: { id: string; sector: string }) =>
      apiFetch<Instrument>(`/api/instruments/vol/${id}/sector`, {
        method: "PATCH",
        body: JSON.stringify({ sector }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: instrumentsKey("vol") });
    },
  });
}

export function extractErrorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    const body = err.body as { detail?: string } | null;
    return body?.detail ?? err.message;
  }
  if (err instanceof Error) return err.message;
  return String(err);
}
