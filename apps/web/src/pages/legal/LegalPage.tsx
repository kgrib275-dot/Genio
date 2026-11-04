// v0.6 이용약관·개인정보 처리방침(로그인 없이 볼 수 있다). 초안이라 맨 위에 법률 검토 필요 표시를 둔다.
import { AlertTriangle, ArrowLeft } from "lucide-react";
import { Link } from "react-router-dom";
import { PRIVACY, TERMS, type LegalDoc } from "@/pages/legal/legalText";

function LegalView({ doc }: { doc: LegalDoc }) {
  return (
    <div className="min-h-[100dvh] bg-slate-50 px-4 py-8 text-slate-800 sm:py-12">
      <article className="mx-auto max-w-3xl rounded-2xl border border-slate-200 bg-white p-6 shadow-card sm:p-10">
        <Link
          to="/login"
          className="mb-6 inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-800"
        >
          <ArrowLeft className="h-4 w-4" /> 제니오로 돌아가기
        </Link>
        <h1 className="text-2xl font-bold tracking-tight text-slate-900">{doc.title}</h1>
        <p className="mt-1 text-sm text-slate-500">
          판 {doc.version} · {doc.effective}
        </p>
        <div
          role="note"
          className="mt-5 flex gap-2 rounded-lg bg-amber-50 px-4 py-3 text-sm text-amber-900"
        >
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <p>
            <b>초안(DRAFT)이에요.</b> [대괄호] 칸은 서비스 회사 정보로 채워야 하고, 공개 전에 반드시
            법률 검토를 받아야 해요.
          </p>
        </div>
        <div className="mt-8 space-y-7">
          {doc.sections.map((s) => (
            <section key={s.heading}>
              <h2 className="text-base font-semibold text-slate-900">{s.heading}</h2>
              <ul className="mt-2 list-disc space-y-1.5 pl-5 text-sm leading-relaxed text-slate-700 marker:text-slate-300">
                {s.body.map((b) => (
                  <li key={b}>{b}</li>
                ))}
              </ul>
            </section>
          ))}
        </div>
        <p className="mt-10 border-t border-slate-100 pt-4 text-xs text-slate-400">
          <Link to="/terms" className="hover:underline">
            이용약관
          </Link>
          <span className="mx-1.5">·</span>
          <Link to="/privacy" className="font-semibold hover:underline">
            개인정보 처리방침
          </Link>
        </p>
      </article>
    </div>
  );
}

export function TermsPage() {
  return <LegalView doc={TERMS} />;
}

export function PrivacyPage() {
  return <LegalView doc={PRIVACY} />;
}
