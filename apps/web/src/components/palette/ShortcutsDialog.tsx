// 단축키 보기(Shift + ?): 어디서나 쓰는 키, 검색창, 만들기 캔버스, 챗 입력의 키를 한눈에.
import { Dialog } from "@/components/ui/dialog";
import {
  CANVAS_SHORTCUTS,
  CHAT_SHORTCUTS,
  GLOBAL_SHORTCUTS,
  PALETTE_SHORTCUTS,
  type ShortcutRow,
} from "@/lib/shortcuts";

const SECTIONS: { title: string; rows: ShortcutRow[] }[] = [
  { title: "어디서나", rows: GLOBAL_SHORTCUTS },
  { title: "검색창 안에서", rows: PALETTE_SHORTCUTS },
  { title: "만들기 화면(캔버스)", rows: CANVAS_SHORTCUTS },
  { title: "챗 입력칸", rows: CHAT_SHORTCUTS },
];

export function ShortcutsDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <Dialog open={open} onClose={onClose} title="단축키 보기" wide>
      <div className="space-y-5">
        {SECTIONS.map((s) => (
          <section key={s.title} aria-label={s.title}>
            <h3 className="mb-2 text-xs font-semibold text-slate-500">{s.title}</h3>
            <dl className="grid grid-cols-[minmax(0,auto)_1fr] items-center gap-x-4 gap-y-2 text-sm">
              {s.rows.map(([keys, what]) => (
                <div key={keys} className="contents">
                  <dt className="flex flex-wrap gap-1">
                    {keys.split(/\s*,\s*/).map((combo) => (
                      <kbd
                        key={combo}
                        className="rounded border border-slate-200 bg-slate-50 px-1.5 py-0.5 font-mono text-[11px] text-slate-700"
                      >
                        {combo}
                      </kbd>
                    ))}
                  </dt>
                  <dd className="text-slate-600">{what}</dd>
                </div>
              ))}
            </dl>
          </section>
        ))}
        <p className="text-xs text-slate-400">
          글을 입력하는 중에는 한 글자 단축키(D 등)가 동작하지 않아요.
        </p>
      </div>
    </Dialog>
  );
}
