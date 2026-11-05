// v0.8 공개 API 문서: 서버가 밖에 내보내도 되는 API만 담은 OpenAPI 문서를 읽는다(로그인 없이).
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import type { OpenApiDoc } from "@/lib/openapi";

export function usePublicOpenApi() {
  return useQuery({
    queryKey: ["openapi-public"],
    queryFn: () => api.get<OpenApiDoc>("/openapi-public.json"),
    staleTime: 5 * 60_000,
  });
}
