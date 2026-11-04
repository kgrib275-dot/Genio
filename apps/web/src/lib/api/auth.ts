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

export function useSignup() {
  return useTokenMutation(
    (v: {
      email: string;
      password: string;
      name: string;
      workspace_name?: string;
      agree_terms: boolean;
      agree_privacy: boolean;
    }) => api.post<Tokens>("/auth/signup", v),
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
  return useTokenMutation(
    (v: { name: string; password: string; agree_terms?: boolean; agree_privacy?: boolean }) =>
      api.post<Tokens>(`/auth/invitations/${token}/accept`, v),
  );
}
