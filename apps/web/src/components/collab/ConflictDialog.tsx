// '충돌 해결' 창(v0.9): 다른 사람이 먼저 고친 곳과 겹치면 항목마다 내 것·상대 것을 고른다.
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { toast } from "@/components/ui/toast-store";
import type { ConflictItem } from "@/lib/api/collab";
import { adoptTheirs, saveResolved } from "@/lib/collabSave";
import {
  allChosen,
  applyChoices,
  conflictKey,
  fieldLabel,
  groupConflicts,
  kindLabel,
  valueText,
  type Choices,
  type Side,
} from "@/lib/mergeUi";
import { cn } from "@/lib/cn";
import { useCollab } from "@/store/collab";

function Option({
  name,
  checked,
  onChange,
  title,
  value,
}: {
  name: string;
  checked: boolean;
  onChange: () => void;
  title: string;
  value: unknown;
}) {
  return (
    <label
      className={cn(
        "flex cursor-pointer flex-col gap-1 rounded-lg border p-2.5 text-sm transition-colors",
        checked
          ? "border-indigo-400 bg-indigo-50 text-indigo-900"
          : "border-slate-200 bg-white text-slate-700 hover:border-slate-300",
      )}
    >
      <span className="flex items-center gap-2 text-xs font-semibold">
        <input
          type="radio"
          name={name}
          checked={checked}
          onChange={onChange}
          className="accent-indigo-600"
        />
        {title}
      </span>
      <span className="break-words text-[13px] leading-snug">{valueText(value)}</span>
    </label>
  );
}

function ItemRow({
  item,
  choice,
  onPick,
}: {
  item: ConflictItem;
  choice: Side | undefined;
  onPick: (s: Side) => void;
}) {
  const key = conflictKey(item);
  return (
    <fieldset className="space-y-1.5">
      <legend className="text-xs font-medium text-slate-500">{fieldLabel(item)}</legend>
      <div className="grid gap-2 sm:grid-cols-2">
        <Option
          name={key}
          checked={choice === "mine"}
          onChange={() => onPick("mine")}
          title="내 것"
          value={item.mine}
        />
        <Option
          name={key}
          checked={choice === "theirs"}
          onChange={() => onPick("theirs")}
          title="상대 것"
          value={item.theirs}
        />
      </div>
    </fieldset>
  );
}

export function ConflictDialog({ appId }: { appId: string }) {
  const conflict = useCollab((s) => s.conflict);
  const [choices, setChoices] = useState<Choices>({});
  const [busy, setBusy] = useState(false);
  useEffect(() => setChoices({}), [conflict]);

  if (!conflict) return null;
  const close = () => useCollab.getState().setConflict(null);
  const run = async (fn: () => Promise<void> | void, done: string) => {
    setBusy(true);
    try {
      await fn();
      if (!useCollab.getState().conflict) toast.success(done);
    } catch (err) {
      toast.error(err);
    } finally {
      setBusy(false);
    }
  };

  if (conflict.stale) {
    return (
      <Dialog
        open
        onClose={close}
        title="흐름이 많이 바뀌었어요"
        footer={
          <>
            <Button
              variant="outline"
              disabled={busy}
              onClick={() =>
                void run(
                  () => adoptTheirs(conflict.theirs, conflict.rev),
                  "상대가 저장한 흐름을 불러왔어요.",
                )
              }
            >
              상대가 저장한 흐름으로 새로 불러오기
            </Button>
            <Button
              disabled={busy}
              onClick={() =>
                void run(
                  () => saveResolved(appId, conflict.mine, conflict.rev),
                  "내 흐름으로 덮어써서 저장했어요.",
                )
              }
            >
              내 것으로 덮어쓰기
            </Button>
          </>
        }
      >
        <p className="text-sm text-slate-700">
          내가 연 뒤로 흐름이 많이 바뀌어 자동으로 합칠 수 없어요.
        </p>
        <p className="mt-1 text-sm text-slate-500">
          상대가 저장한 흐름을 불러오면 내가 고친 내용은 사라져요. 덮어쓰면 상대가 고친 내용이
          사라져요.
        </p>
      </Dialog>
    );
  }

  const groups = groupConflicts(conflict.conflicts);
  const ready = allChosen(conflict.conflicts, choices);
  const setAll = (side: Side) =>
    setChoices(Object.fromEntries(conflict.conflicts.map((c) => [conflictKey(c), side])));
  return (
    <Dialog
      open
      wide
      onClose={close}
      title="충돌 해결"
      footer={
        <>
          <Button variant="ghost" disabled={busy} onClick={() => setAll("theirs")}>
            모두 상대 것으로
          </Button>
          <Button variant="ghost" disabled={busy} onClick={() => setAll("mine")}>
            모두 내 것으로
          </Button>
          <Button
            disabled={!ready || busy}
            onClick={() =>
              void run(
                () =>
                  saveResolved(
                    appId,
                    applyChoices(conflict.merged, conflict.conflicts, choices),
                    conflict.rev,
                  ),
                "고른 대로 저장했어요.",
              )
            }
          >
            {busy ? "저장하는 중…" : "고른 대로 저장"}
          </Button>
        </>
      }
    >
      <p className="mb-3 text-sm text-slate-600">
        다른 사람이 같은 곳을 먼저 고쳤어요. 겹치는 {conflict.conflicts.length}곳마다 내 것과 상대
        것 중 하나를 골라 주세요. 겹치지 않는 변경은 이미 합쳐졌어요.
      </p>
      <div className="space-y-4">
        {groups.map((g) => (
          <section key={g.id} className="rounded-xl border border-slate-200 p-3">
            <h3 className="mb-2 text-sm font-semibold text-slate-800">
              {kindLabel(g.kind)} · {g.label}
            </h3>
            <div className="space-y-3">
              {g.items.map((item) => (
                <ItemRow
                  key={conflictKey(item)}
                  item={item}
                  choice={choices[conflictKey(item)]}
                  onPick={(s) => setChoices((c) => ({ ...c, [conflictKey(item)]: s }))}
                />
              ))}
            </div>
          </section>
        ))}
      </div>
    </Dialog>
  );
}
