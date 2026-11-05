// AI 자동 전환 순서 편집기(워크스페이스 설정과 앱 기능이 함께 쓴다).
// 끌어다 놓기 없이 위·아래 화살표로 순서를 바꾸고, 넘어갈 조건을 체크한다.
import { ArrowDown, ArrowUp, Plus, X } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/input";
import {
  MAX_LINKS,
  TRIGGERS,
  addLink,
  moveLink,
  removeLink,
  setLinkModel,
  type ChainLink,
  type TriggerKey,
} from "@/lib/llmChain";

export interface ChainConnection {
  id: string;
  label: string;
  provider: string;
  default_model: string;
}

export function ChainEditor({
  connections,
  links,
  triggers,
  onLinks,
  onTriggers,
  readOnly = false,
  idPrefix = "chain",
}: {
  connections: ChainConnection[];
  links: ChainLink[];
  triggers: Record<TriggerKey, boolean>;
  onLinks: (next: ChainLink[]) => void;
  onTriggers: (next: Record<TriggerKey, boolean>) => void;
  readOnly?: boolean;
  idPrefix?: string;
}) {
  const [pick, setPick] = useState("");
  const byId = new Map(connections.map((c) => [c.id, c]));
  const free = connections.filter((c) => !links.some((l) => l.provider_id === c.id));
  const full = links.length >= MAX_LINKS;

  return (
    <div className="space-y-4">
      <div>
        <p className="mb-1.5 text-sm font-medium text-slate-700">
          넘어갈 순서{" "}
          <span className="font-normal text-slate-400">(위에서부터 차례로 시도해요)</span>
        </p>
        {links.length === 0 ? (
          <p className="rounded-lg border border-dashed border-slate-300 px-3 py-3 text-sm text-slate-500">
            아직 대체 연결이 없어요. 아래에서 AI 연결을 골라 추가하세요. 기본 연결(단계에서 고른
            연결)이 안 될 때 여기 적은 순서로 넘어가요.
          </p>
        ) : (
          <ol className="space-y-2">
            {links.map((l, i) => {
              const c = byId.get(l.provider_id);
              return (
                <li
                  key={l.provider_id}
                  className="flex flex-wrap items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2"
                >
                  <span className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-indigo-100 text-xs font-bold text-indigo-700">
                    {i + 1}
                  </span>
                  <span className="min-w-0 flex-1 basis-32 truncate text-sm font-medium text-slate-800">
                    {c?.label ?? "(지워진 연결)"}
                    {c && (
                      <span className="ml-1.5 text-xs font-normal text-slate-400">
                        {c.provider}
                      </span>
                    )}
                  </span>
                  <Input
                    aria-label={`${c?.label ?? "연결"} 모델`}
                    className="h-8 w-44 text-xs"
                    placeholder={c ? `${c.default_model} (기본)` : "모델"}
                    value={l.model}
                    disabled={readOnly}
                    onChange={(e) => onLinks(setLinkModel(links, i, e.target.value))}
                  />
                  {!readOnly && (
                    <span className="flex gap-0.5">
                      <Button
                        size="sm"
                        variant="ghost"
                        aria-label={`${c?.label ?? "연결"} 위로`}
                        disabled={i === 0}
                        onClick={() => onLinks(moveLink(links, i, -1))}
                      >
                        <ArrowUp className="h-3.5 w-3.5" />
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        aria-label={`${c?.label ?? "연결"} 아래로`}
                        disabled={i === links.length - 1}
                        onClick={() => onLinks(moveLink(links, i, 1))}
                      >
                        <ArrowDown className="h-3.5 w-3.5" />
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        className="text-red-600"
                        aria-label={`${c?.label ?? "연결"} 빼기`}
                        onClick={() => onLinks(removeLink(links, i))}
                      >
                        <X className="h-3.5 w-3.5" />
                      </Button>
                    </span>
                  )}
                </li>
              );
            })}
          </ol>
        )}
        {!readOnly && (
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <Select
              id={`${idPrefix}-add`}
              aria-label="대체 연결 고르기"
              className="w-60"
              value={pick}
              disabled={full || free.length === 0}
              onChange={(e) => setPick(e.target.value)}
            >
              <option value="">
                {full
                  ? `최대 ${MAX_LINKS}곳까지 넣을 수 있어요`
                  : free.length === 0
                    ? "추가할 연결이 없어요"
                    : "AI 연결 고르기…"}
              </option>
              {free.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.label} · {c.default_model}
                </option>
              ))}
            </Select>
            <Button
              size="sm"
              variant="outline"
              disabled={!pick}
              onClick={() => {
                onLinks(addLink(links, pick));
                setPick("");
              }}
            >
              <Plus className="h-3.5 w-3.5" /> 추가
            </Button>
          </div>
        )}
      </div>

      <fieldset className="space-y-1.5">
        <legend className="mb-1 text-sm font-medium text-slate-700">이럴 때 넘어가요</legend>
        {TRIGGERS.map((t) => (
          <label key={t.key} className="flex items-start gap-2 text-sm text-slate-700">
            <input
              type="checkbox"
              className="mt-0.5 accent-indigo-600"
              checked={triggers[t.key]}
              disabled={readOnly}
              onChange={(e) => onTriggers({ ...triggers, [t.key]: e.target.checked })}
            />
            <span>
              {t.label}
              <span className="ml-1.5 text-xs text-slate-400">{t.hint}</span>
            </span>
          </label>
        ))}
        <p className="pt-1 text-xs text-slate-500">
          JSON 출력·이미지·도구가 필요한 호출은 그것을 지원하는 연결로만 넘어가요. 답이 이미 한
          글자라도 나가기 시작했다면 중간에 바꾸지 않아요.
        </p>
      </fieldset>
    </div>
  );
}
