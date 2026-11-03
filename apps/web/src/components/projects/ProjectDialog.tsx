// 프로젝트 만들기·고치기 대화상자. 이름·설명·색·공개 범위·(비공개일 때) 구성원·삭제를 한 곳에서 다룬다.
import { Check, Lock, Users } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input, Textarea } from "@/components/ui/input";
import { toast } from "@/components/ui/toast-store";
import type { Project, ProjectColor } from "@/lib/api/types";
import {
  PROJECT_COLORS,
  useCreateProject,
  useDeleteProject,
  useSetProjectMembers,
  useUpdateProject,
} from "@/lib/api/v3";
import { useMembers } from "@/lib/api/workspace";
import { cn } from "@/lib/cn";

const COLOR_NAMES: Record<ProjectColor, string> = {
  indigo: "남색",
  sky: "하늘",
  emerald: "초록",
  amber: "노랑",
  rose: "분홍",
  violet: "보라",
  slate: "회색",
};

export function ProjectDot({ color, className }: { color: ProjectColor; className?: string }) {
  return (
    <span
      aria-hidden
      className={cn(
        "inline-block h-2.5 w-2.5 shrink-0 rounded-full",
        PROJECT_COLORS[color] ?? PROJECT_COLORS.slate,
        className,
      )}
    />
  );
}

export function ProjectDialog({
  ws,
  open,
  onClose,
  project,
  myUserId,
  onSaved,
  onDeleted,
}: {
  ws: string;
  open: boolean;
  onClose: () => void;
  /** 비우면 새로 만든다 */
  project?: Project | null;
  myUserId?: string;
  onSaved?: (p: Project) => void;
  onDeleted?: () => void;
}) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [color, setColor] = useState<ProjectColor>("indigo");
  const [visibility, setVisibility] = useState<"workspace" | "private">("workspace");
  const [memberIds, setMemberIds] = useState<string[]>([]);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const members = useMembers(open ? ws : "");
  const create = useCreateProject(ws);
  const update = useUpdateProject(ws);
  const remove = useDeleteProject(ws);
  const setMembers = useSetProjectMembers(ws);

  useEffect(() => {
    if (!open) return;
    setName(project?.name ?? "");
    setDescription(project?.description ?? "");
    setColor(project?.color ?? "indigo");
    setVisibility(project?.visibility ?? "workspace");
    setMemberIds(project?.members.map((m) => m.user_id) ?? []);
    setConfirmDelete(false);
  }, [open, project]);

  const busy = create.isPending || update.isPending || setMembers.isPending || remove.isPending;

  async function save() {
    const body = { name: name.trim(), description: description.trim(), color, visibility };
    try {
      let saved = project
        ? await update.mutateAsync({ id: project.id, ...body })
        : await create.mutateAsync(body);
      if (visibility === "private") {
        const before = (project?.members ?? [])
          .map((m) => m.user_id)
          .sort()
          .join(",");
        const after = [...memberIds].sort().join(",");
        if (before !== after) {
          saved = await setMembers.mutateAsync({ id: saved.id, user_ids: memberIds });
        }
      }
      toast.success(project ? "프로젝트를 저장했어요." : "프로젝트를 만들었어요.");
      onSaved?.(saved);
      onClose();
    } catch (e) {
      toast.error(e);
    }
  }

  async function doDelete() {
    if (!project) return;
    try {
      await remove.mutateAsync(project.id);
      toast.success("프로젝트를 지웠어요. 안에 있던 앱은 ‘프로젝트 없음’으로 옮겼어요.");
      onDeleted?.();
      onClose();
    } catch (e) {
      toast.error(e);
    }
  }

  const others = (members.data ?? []).filter((m) => m.user_id !== myUserId);

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={project ? "프로젝트 설정" : "새 프로젝트"}
      footer={
        <>
          {project && !confirmDelete && (
            <Button
              variant="ghost"
              className="mr-auto text-red-600 hover:bg-red-50"
              onClick={() => setConfirmDelete(true)}
              disabled={busy}
            >
              삭제
            </Button>
          )}
          {confirmDelete && (
            <div className="mr-auto flex flex-wrap items-center gap-2">
              <span className="text-xs text-red-700">
                앱·지식은 지우지 않고 ‘프로젝트 없음’으로 옮겨요.
              </span>
              <Button variant="danger" size="sm" onClick={doDelete} disabled={busy}>
                정말 삭제
              </Button>
              <Button variant="ghost" size="sm" onClick={() => setConfirmDelete(false)}>
                취소
              </Button>
            </div>
          )}
          <Button variant="outline" onClick={onClose}>
            닫기
          </Button>
          <Button onClick={save} disabled={busy || !name.trim()}>
            {project ? "저장" : "만들기"}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <Field label="이름" htmlFor="project-name">
          <Input
            id="project-name"
            value={name}
            maxLength={60}
            autoFocus
            placeholder="예: 고객 지원 챗봇"
            onChange={(e) => setName(e.target.value)}
          />
        </Field>
        <Field label="설명 (선택)" htmlFor="project-desc">
          <Textarea
            id="project-desc"
            value={description}
            maxLength={300}
            className="min-h-[64px]"
            placeholder="이 프로젝트에서 무엇을 만드는지 짧게 적어 주세요."
            onChange={(e) => setDescription(e.target.value)}
          />
        </Field>
        <div className="space-y-1.5">
          <p className="text-sm font-medium text-slate-700">색</p>
          <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="프로젝트 색">
            {(Object.keys(PROJECT_COLORS) as ProjectColor[]).map((c) => (
              <button
                key={c}
                type="button"
                role="radio"
                aria-checked={color === c}
                aria-label={COLOR_NAMES[c]}
                title={COLOR_NAMES[c]}
                onClick={() => setColor(c)}
                className={cn(
                  "flex h-8 w-8 items-center justify-center rounded-full ring-offset-2 ring-offset-[color:rgb(var(--surface))] transition",
                  PROJECT_COLORS[c],
                  color === c ? "ring-2 ring-slate-400" : "hover:scale-110",
                )}
              >
                {color === c && <Check className="h-4 w-4 text-white" />}
              </button>
            ))}
          </div>
        </div>
        <fieldset className="space-y-2">
          <legend className="mb-1.5 text-sm font-medium text-slate-700">누가 볼 수 있나요?</legend>
          <VisibilityOption
            checked={visibility === "workspace"}
            onSelect={() => setVisibility("workspace")}
            icon={<Users className="h-4 w-4" />}
            title="워크스페이스 전체"
            body="이 워크스페이스의 모든 사람이 프로젝트와 안의 앱을 볼 수 있어요."
          />
          <VisibilityOption
            checked={visibility === "private"}
            onSelect={() => setVisibility("private")}
            icon={<Lock className="h-4 w-4" />}
            title="나와 고른 사람만"
            body="만든 사람과 아래에서 고른 사람만 볼 수 있어요. 소유자·관리자는 언제나 볼 수 있어요."
          />
        </fieldset>
        {visibility === "private" && (
          <div className="space-y-1.5">
            <p className="text-sm font-medium text-slate-700">함께 볼 사람</p>
            {members.isLoading ? (
              <p className="text-xs text-slate-500">구성원을 불러오는 중…</p>
            ) : others.length === 0 ? (
              <p className="text-xs text-slate-500">함께할 다른 구성원이 아직 없어요.</p>
            ) : (
              <ul className="max-h-48 divide-y divide-slate-100 overflow-y-auto rounded-lg border border-slate-200">
                {others.map((m) => {
                  const on = memberIds.includes(m.user_id);
                  return (
                    <li key={m.user_id}>
                      <label className="flex cursor-pointer items-center gap-3 px-3 py-2 text-sm hover:bg-slate-50">
                        <input
                          type="checkbox"
                          className="h-4 w-4 rounded border-slate-300 text-indigo-600"
                          checked={on}
                          onChange={() =>
                            setMemberIds((ids) =>
                              on ? ids.filter((x) => x !== m.user_id) : [...ids, m.user_id],
                            )
                          }
                        />
                        <span className="min-w-0 flex-1 truncate">
                          {m.name} <span className="text-xs text-slate-500">{m.email}</span>
                        </span>
                      </label>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        )}
      </div>
    </Dialog>
  );
}

function VisibilityOption({
  checked,
  onSelect,
  icon,
  title,
  body,
}: {
  checked: boolean;
  onSelect: () => void;
  icon: ReactNode;
  title: string;
  body: string;
}) {
  return (
    <label
      className={cn(
        "flex cursor-pointer gap-3 rounded-lg border p-3 text-sm transition-colors",
        checked ? "border-indigo-400 bg-indigo-50/60" : "border-slate-200 hover:bg-slate-50",
      )}
    >
      <input
        type="radio"
        name="project-visibility"
        className="mt-0.5 h-4 w-4 text-indigo-600"
        checked={checked}
        onChange={onSelect}
      />
      <span className="min-w-0">
        <span className="flex items-center gap-1.5 font-medium text-slate-900">
          {icon}
          {title}
        </span>
        <span className="mt-0.5 block text-xs text-slate-500">{body}</span>
      </span>
    </label>
  );
}
