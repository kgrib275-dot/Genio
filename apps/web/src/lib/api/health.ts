import { useQuery } from "@tanstack/react-query";
import { apiGet } from "@/lib/api/client";

export interface Health {
  status: string;
  env: string;
}

export function useHealth() {
  return useQuery({ queryKey: ["health"], queryFn: () => apiGet<Health>("/health") });
}
