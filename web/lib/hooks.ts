"use client";

import { useQuery } from "@tanstack/react-query";

import { type AreaDetail, type AreaRow, type KpiEnvelope, type ScreenerRow, api } from "./api";
import { useShell } from "@/components/Providers";

/** One place for the query keys, so nothing refetches under a slightly different name. */
export const keys = {
  market: ["market"] as const,
  areas: ["areas"] as const,
  area: (key: string) => ["area", key] as const,
  screener: (params: string) => ["screener", params] as const,
  result: (name: string) => ["result", name] as const,
  memos: ["memos"] as const,
  sources: ["ask-sources"] as const,
  providers: ["ask-providers"] as const,
  freshness: ["freshness"] as const,
};

export function useMarket() {
  return useQuery({ queryKey: keys.market, queryFn: () => api.get<KpiEnvelope>("/market") });
}

export function useAreas() {
  return useQuery({
    queryKey: keys.areas,
    queryFn: () =>
      api.get<{ areas: AreaRow[]; provenance: string; without_location: number }>("/areas"),
    staleTime: 5 * 60_000,
  });
}

export function useArea(areaKey: string | null) {
  return useQuery({
    queryKey: keys.area(areaKey ?? ""),
    queryFn: () => api.get<AreaDetail>(`/areas/${encodeURIComponent(areaKey!)}`),
    enabled: Boolean(areaKey),
  });
}

export function useScreener(params: { min_sales?: number; property_type?: string; rooms?: number }) {
  const search = new URLSearchParams();
  if (params.min_sales) search.set("min_sales", String(params.min_sales));
  if (params.property_type) search.set("property_type", params.property_type);
  if (params.rooms !== undefined) search.set("rooms", String(params.rooms));
  const qs = search.toString();
  return useQuery({
    queryKey: keys.screener(qs),
    queryFn: () =>
      api.get<{ rows: ScreenerRow[]; total_matching: number; sql: string; provenance: string }>(
        `/screener?${qs}`,
      ),
  });
}

/** Model outputs published by the pipeline, served straight through by the API. */
export function useResult<T>(path: string) {
  return useQuery({ queryKey: keys.result(path), queryFn: () => api.get<T>(path) });
}

export function useRole() {
  return useShell().role;
}
