import { useQuery } from "@tanstack/react-query";

import { apiFetch } from "./api";
import type { components } from "@/types/api";

export type StrategyMeta = components["schemas"]["StrategyMeta"];
export type StrategyListResponse =
  components["schemas"]["StrategyListResponse"];
export type StrategyResult = components["schemas"]["StrategyResult"];
export type Metric = components["schemas"]["Metric"];
export type ChartSpec = components["schemas"]["ChartSpec"];
export type TabSpec = components["schemas"]["TabSpec"];
export type TableSpec = components["schemas"]["TableSpec"];
export type ColumnSpec = components["schemas"]["ColumnSpec"];

export function useStrategyList() {
  return useQuery({
    queryKey: ["strategies"],
    queryFn: () => apiFetch<StrategyListResponse>("/api/strategies"),
    staleTime: 5 * 60_000,
  });
}

export function useComputeQuery(
  strategyId: string,
  params: Record<string, unknown> | null,
) {
  return useQuery({
    queryKey: ["compute", strategyId, params],
    queryFn: () =>
      apiFetch<StrategyResult>(`/api/strategies/${strategyId}/compute`, {
        method: "POST",
        body: JSON.stringify(params),
      }),
    enabled: params !== null,
    staleTime: 60_000,
    placeholderData: (prev) => prev,
  });
}

export function useSummaryQuery(
  strategyId: string,
  params: Record<string, unknown> | null,
  enabled: boolean,
) {
  return useQuery({
    queryKey: ["summary", strategyId, params],
    queryFn: () =>
      apiFetch<StrategyResult>(`/api/strategies/${strategyId}/summary`, {
        method: "POST",
        body: JSON.stringify(params),
      }),
    enabled: enabled && params !== null,
    staleTime: 120_000,
    placeholderData: (prev) => prev,
  });
}
