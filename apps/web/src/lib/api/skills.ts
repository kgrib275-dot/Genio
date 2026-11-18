// 후속(Y2): 스킬(업무 요령) — SKILL.md 가져오기·관리
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api/client";

export interface Skill {
  id: string;
  name: string;
  description: string;
  size: number;
}

export interface SkillFull extends Skill {
  body: string;
}

export function useSkills(ws: string) {
  return useQuery({
    queryKey: ["skills", ws],
    queryFn: () => api.get<{ skills: Skill[]; max_skills: number }>(`/workspaces/${ws}/skills`),
    enabled: Boolean(ws),
  });
}

export function useCreateSkill(ws: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { skill_md?: string; name?: string; description?: string; body?: string }) =>
      api.post<SkillFull>(`/workspaces/${ws}/skills`, v),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["skills", ws] }),
  });
}

export function useDeleteSkill(ws: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.del(`/workspaces/${ws}/skills/${id}`),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["skills", ws] }),
  });
}

/** SKILL.md(.md)나 .zip·.skill 파일 올리기 */
export function useImportSkill(ws: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (file: File) => {
      const form = new FormData();
      form.append("file", file);
      return api.upload<SkillFull>(`/workspaces/${ws}/skills/import`, form);
    },
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["skills", ws] }),
  });
}

export const SKILL_MD_EXAMPLE = `---
name: 환불 안내
description: 고객이 환불·반품을 물을 때 따라야 할 안내 순서
---
1. 주문 번호부터 물어봅니다.
2. 수령 후 7일 안이면 환불이 가능하다고 안내합니다.
3. 개봉한 식품은 환불되지 않는다고 정중히 알립니다.
`;
