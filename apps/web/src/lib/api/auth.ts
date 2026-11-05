import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, setTokens } from "@/lib/api/client";
import type { LoginResult } from "@/lib/api/account";
import type { InvitationInfo, Me, Tokens } from "@/lib/api/types";

export function useMe(enabled = true) {
  return useQuery({ queryKey: ["me"], queryFn: () => api.get<Me>("/me"), enabled });
}

/** 로그인 전 화면이 쓰는 설정: 가입을 열어 두었는지 */
export function useAuthConfig() {
  return useQuery({
    queryKey: ["auth-config"],
    queryFn: () => api.get<{ allow_signup: boolean }>("/auth/config"),
    staleTime: 60_000,
  });
}

function useTokenMutation<V, R extends LoginResult = Tokens>(fn: (v: V) => Promise<R>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: (result) => {
      // 메일 확인·2단계 인증이 남았으면 아직 토큰이 없다
      if ("access_token" in result) {
        setTokens(result);
        void qc.invalidateQueries();
      }
    },
  });
}

export function useLogin() {
  return useTokenMutation((v: { email: string; password: string }) =>
    api.post<LoginResult>("/auth/login", { ...v, email: v.email.trim() }),
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
    }) => api.post<LoginResult>("/auth/signup", v),
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
