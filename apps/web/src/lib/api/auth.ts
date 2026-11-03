import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, setTokens } from "@/lib/api/client";
import type { InvitationInfo, Me, Tokens } from "@/lib/api/types";

export function useMe(enabled = true) {
  return useQuery({ queryKey: ["me"], queryFn: () => api.get<Me>("/me"), enabled });
}

function useTokenMutation<V>(fn: (v: V) => Promise<Tokens>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: (tokens) => {
      setTokens(tokens);
      void qc.invalidateQueries();
    },
  });
}

export function useLogin() {
  return useTokenMutation((v: { email: string; password: string }) =>
    api.post<Tokens>("/auth/login", { ...v, email: v.email.trim() }),
  );
}

export interface DemoAccounts {
  enabled: boolean;
  password: string;
  accounts: { email: string; name: string; role: string }[];
}

/** 데모 모드일 때 로그인 화면에 보여 줄 공개 데모 계정 */
export function useDemoAccounts() {
  return useQuery({
    queryKey: ["demo-accounts"],
    queryFn: () => api.get<DemoAccounts>("/auth/demo-accounts"),
    staleTime: Infinity,
    retry: false,
  });
}

export function useSignup() {
  return useTokenMutation(
    (v: { email: string; password: string; name: string; workspace_name?: string }) =>
      api.post<Tokens>("/auth/signup", v),
  );
}

export function useInvitationInfo(token: string) {
  return useQuery({
    queryKey: ["invitation", token],
    queryFn: () => api.get<InvitationInfo>(`/auth/invitations/${token}`),
    retry: false,
  });
}

export function useAcceptInvitation(token: string) {
  return useTokenMutation((v: { name: string; password: string }) =>
    api.post<Tokens>(`/auth/invitations/${token}/accept`, v),
  );
}
