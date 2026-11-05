// 캔버스 오른쪽 위 도구 막대: 메모, 되돌리기·다시 하기, 끄기, 복제, 자동 정렬, 미니맵, 단축키 도움말.
import {
  Copy,
  Keyboard,
  Layers,
  Map as MapIcon,
  Network,
  Power,
  Redo2,
  StickyNote,
  Undo2,
  X,
} from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { cn } from "@/lib/cn";
import { CANVAS_SHORTCUTS, MOD } from "@/lib/shortcuts";

function Tool({
  label,
  onClick,
  disabled,
  active,
  children,
}: {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  active?: boolean;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      disabled={disabled}
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        "inline-flex h-8 w-8 items-center justify-center rounded-md text-slate-600 transition-colors hover:bg-slate-100 hover:text-slate-900 disabled:opacity-30 disabled:hover:bg-transparent",
        active && "bg-indigo-50 text-indigo-700",
      )}
    >
      {children}
    </button>
  );
}

const SHORTCUTS = CANVAS_SHORTCUTS;

function ShortcutHelp({ onClose }: { onClose: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("mousedown", onDown);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("mousedown", onDown);
      window.removeEventListener("keydown", onKey);
    };
  }, [onClose]);
  return (
    <div
      ref={ref}
      role="dialog"
      aria-label="단축키"
      className="absolute right-0 top-10 z-20 w-72 rounded-xl border border-slate-200 bg-white p-3 text-xs shadow-lift"
    >
      <div className="mb-2 flex items-center justify-between">
        <p className="font-semibold text-slate-800">단축키</p>
        <button
          type="button"
          onClick={onClose}
          aria-label="닫기"
          className="rounded p-0.5 text-slate-400 hover:bg-slate-100"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5">
        {SHORTCUTS.map(([k, v]) => (
          <div key={k} className="contents">
            <dt>
              <kbd className="rounded border border-slate-200 bg-slate-50 px-1.5 py-0.5 font-mono text-[11px] text-slate-700">
                {k}
              </kbd>
            </dt>
            <dd className="text-slate-600">{v}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

export function CanvasToolbar({
  readOnly,
  canUndo,
  canRedo,
  hasSelection,
  allDisabled,
  minimap,
  onAddNote,
  onUndo,
  onRedo,
  onToggleDisabled,
  onDuplicate,
  onSaveSnippet,
  onArrange,
  onToggleMinimap,
}: {
  readOnly?: boolean;
  canUndo: boolean;
  canRedo: boolean;
  hasSelection: boolean;
  allDisabled: boolean;
  minimap: boolean;
  onAddNote: () => void;
  onUndo: () => void;
  onRedo: () => void;
  onToggleDisabled: () => void;
  onDuplicate: () => void;
  onSaveSnippet: () => void;
  onArrange: () => void;
  onToggleMinimap: () => void;
}) {
  const [help, setHelp] = useState(false);
  return (
    <div
      role="toolbar"
      aria-label="캔버스 도구"
      className="absolute right-3 top-3 z-10 flex items-center gap-0.5 rounded-lg border border-slate-200 bg-white p-0.5 shadow-lift"
    >
      {!readOnly && (
        <>
          <Tool label="메모 추가" onClick={onAddNote}>
            <StickyNote className="h-4 w-4" />
          </Tool>
          <span className="mx-0.5 h-5 w-px bg-slate-200" />
          <Tool label={`되돌리기 (${MOD}+Z)`} onClick={onUndo} disabled={!canUndo}>
            <Undo2 className="h-4 w-4" />
          </Tool>
          <Tool label={`다시 하기 (${MOD}+Shift+Z)`} onClick={onRedo} disabled={!canRedo}>
            <Redo2 className="h-4 w-4" />
          </Tool>
          <span className="mx-0.5 hidden h-5 w-px bg-slate-200 sm:block" />
          <span className="hidden items-center sm:flex">
            <Tool
              label={allDisabled ? "고른 단계 켜기 (D)" : "고른 단계 끄기 (D)"}
              onClick={onToggleDisabled}
              disabled={!hasSelection}
              active={hasSelection && allDisabled}
            >
              <Power className="h-4 w-4" />
            </Tool>
            <Tool label={`복제 (${MOD}+D)`} onClick={onDuplicate} disabled={!hasSelection}>
              <Copy className="h-4 w-4" />
            </Tool>
            <Tool
              label="고른 단계를 스니펫으로 저장"
              onClick={onSaveSnippet}
              disabled={!hasSelection}
            >
              <Layers className="h-4 w-4" />
            </Tool>
          </span>
          <Tool label="자동 정렬" onClick={onArrange}>
            <Network className="h-4 w-4" />
          </Tool>
        </>
      )}
      <Tool
        label={minimap ? "미니맵 숨기기" : "미니맵 보기"}
        onClick={onToggleMinimap}
        active={minimap}
      >
        <MapIcon className="h-4 w-4" />
      </Tool>
      <span className="relative hidden sm:block">
        <Tool label="단축키" onClick={() => setHelp((v) => !v)} active={help}>
          <Keyboard className="h-4 w-4" />
        </Tool>
        {help && <ShortcutHelp onClose={() => setHelp(false)} />}
      </span>
    </div>
  );
}
