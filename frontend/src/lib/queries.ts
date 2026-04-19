import { useQuery } from "@tanstack/react-query";

import { apiFetch } from "./api";

export interface HealthResponse {
  status: string;
  service: string;
  version: string;
}

export function useHealthQuery() {
  return useQuery({
    queryKey: ["health"],
    queryFn: () => apiFetch<HealthResponse>("/api/health"),
    refetchInterval: 10_000,
    staleTime: 5_000,
  });
}
