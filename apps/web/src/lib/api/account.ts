// v0.7 계정 스스로 관리: 비밀번호 찾기·이메일 인증·2단계 인증·기기·내 데이터·탈퇴·시스템 메일
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { API_PREFIX, api, authHeaders, setTokens } from "@/lib/api/client";
import type { Tokens } from "@/lib/api/types";

/** 로그인·가입 결과: 토큰, 또는 '메일 확인 필요', 또는 '2단계 인증 코드 필요' */
export type LoginResult =
  Tokens | { verify_required: true; email: string } | { mfa_required: true; mfa_token: string };

export function hasTokens(r: LoginResult): r is Tokens {
  return "access_token" in r;
}

export interface Notice {
  ok: boolean;
  message: string;
  hint?: string;
}

export function useForgotPassword() {
  return useMutation({
    mutationFn: (email: string) =>
      api.post<Notice>("/auth/password/forgot", { email: email.trim() }),
  });
}

export function useResetPassword() {
  return useMutation({
    mutationFn: (v: { token: string; password: string }) =>
      api.post<Notice>("/auth/password/reset", v),
  });
}

export function useVerifyEmail() {
  return useMutation({
    mutationFn: (token: string) => api.post<Notice>("/auth/verify-email", { token }),
  });
}

export function useResendVerifyPublic() {
  return useMutation({
    mutationFn: (email: string) =>
      api.post<Notice>("/auth/verify-email/resend", { email: email.trim() }),
  });
}

export function useResendVerifyMe() {
  return useMutation({ mutationFn: () => api.post<Notice>("/me/verify-email/resend") });
}

export function useLoginMfa() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { mfa_token: string; code: string }) => api.post<Tokens>("/auth/login/mfa", v),
    onSuccess: (tokens) => {
      setTokens(tokens);
      void qc.invalidateQueries();
    },
  });
}

// ---------------- 2단계 인증 ----------------
export function useSetup2fa() {
  return useMutation({
    mutationFn: () => api.post<{ secret: string; otpauth_uri: string }>("/me/2fa/setup"),
  });
}

export function useEnable2fa() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (code: string) =>
      api.post<{ enabled: boolean; recovery_codes: string[] }>("/me/2fa/enable", { code }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["me"] }),
  });
}

export function useDisable2fa() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { password: string; code: string }) =>
      api.post<{ enabled: boolean }>("/me/2fa/disable", v),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["me"] }),
  });
}

export function useNewRecoveryCodes() {
  return useMutation({
    mutationFn: (password: string) =>
      api.post<{ recovery_codes: string[] }>("/me/2fa/recovery-codes", { password }),
  });
}

// ---------------- 로그인 기기 ----------------
export interface SessionRow {
  id: string;
  user_agent: string;
  ip: string;
  created_at: string;
  last_seen_at: string;
  current: boolean;
}

export function useSessions() {
  return useQuery({
    queryKey: ["my-sessions"],
    queryFn: () => api.get<SessionRow[]>("/me/sessions"),
  });
}

export function useRevokeSession() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.del(`/me/sessions/${id}`),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["my-sessions"] }),
  });
}

export function useRevokeAllSessions() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<Tokens>("/me/sessions/revoke-all"),
    onSuccess: (tokens) => {
      setTokens(tokens); // 이 기기는 새 토큰으로 계속 쓴다
      void qc.invalidateQueries({ queryKey: ["my-sessions"] });
    },
  });
}

// ---------------- 내 데이터·탈퇴 ----------------
export async function downloadMyData(): Promise<void> {
  const res = await fetch(`${API_PREFIX}/me/export`, { headers: authHeaders() });
  if (!res.ok) throw new Error("내 데이터를 내려받지 못했어요.");
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "genio-my-data.json";
  a.click();
  URL.revokeObjectURL(url);
}

export function useDeleteAccount() {
  return useMutation({
    mutationFn: (v: { password: string; confirm: string }) => api.post<Notice>("/me/delete", v),
  });
}

// ---------------- 시스템 메일(인스턴스 관리자) ----------------
export interface MailSettings {
  host: string;
  port: number;
  username: string;
  password_masked: string;
  from_addr: string;
  from_name: string;
  security: "starttls" | "ssl" | "none";
  configured: boolean;
}

export function useMailSettings(enabled: boolean) {
  return useQuery({
    queryKey: ["system-mail"],
    queryFn: () => api.get<MailSettings>("/admin/system/mail"),
    enabled,
  });
}

export function useSaveMailSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: Partial<MailSettings> & { password?: string }) =>
      api.put<MailSettings>("/admin/system/mail", v),
    onSuccess: (d) => qc.setQueryData(["system-mail"], d),
  });
}

export function useTestMail() {
  return useMutation({ mutationFn: () => api.post<Notice>("/admin/system/mail/test") });
}

export function useResetMember2fa(ws: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (memberId: string) =>
      api.post<{ ok: boolean }>(`/workspaces/${ws}/members/${memberId}/reset-2fa`),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["members", ws] }),
  });
}
