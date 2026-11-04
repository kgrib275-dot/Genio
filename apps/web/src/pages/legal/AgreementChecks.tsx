// v0.6 가입·초대 수락 때 받는 약관 동의(둘 다 필수). 내용은 새 탭에서 열어 본다.
import { Link } from "react-router-dom";

export interface AgreementValue {
  terms: boolean;
  privacy: boolean;
}

export function AgreementChecks({
  value,
  onChange,
}: {
  value: AgreementValue;
  onChange: (v: AgreementValue) => void;
}) {
  const all = value.terms && value.privacy;
  return (
    <fieldset className="space-y-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-3 text-sm">
      <legend className="sr-only">약관 동의</legend>
      <label className="flex items-center gap-2 font-medium text-slate-800">
        <input
          type="checkbox"
          checked={all}
          onChange={(e) => onChange({ terms: e.target.checked, privacy: e.target.checked })}
        />
        모두 동의해요
      </label>
      <div className="space-y-1.5 border-t border-slate-200 pl-6 pt-2 text-slate-600">
        <label className="flex flex-wrap items-center gap-2">
          <input
            type="checkbox"
            required
            checked={value.terms}
            onChange={(e) => onChange({ ...value, terms: e.target.checked })}
          />
          (필수) 이용약관에 동의해요
          <Link
            to="/terms"
            target="_blank"
            className="text-xs text-indigo-600 underline underline-offset-2"
          >
            보기
          </Link>
        </label>
        <label className="flex flex-wrap items-center gap-2">
          <input
            type="checkbox"
            required
            checked={value.privacy}
            onChange={(e) => onChange({ ...value, privacy: e.target.checked })}
          />
          (필수) 개인정보 수집·이용에 동의해요
          <Link
            to="/privacy"
            target="_blank"
            className="text-xs text-indigo-600 underline underline-offset-2"
          >
            보기
          </Link>
        </label>
      </div>
    </fieldset>
  );
}

export function LegalLinks({ className }: { className?: string }) {
  return (
    <p className={className ?? "mt-3 text-center text-xs text-slate-400"}>
      <Link to="/terms" className="hover:text-slate-600 hover:underline">
        이용약관
      </Link>
      <span className="mx-1.5">·</span>
      <Link to="/privacy" className="font-semibold hover:text-slate-600 hover:underline">
        개인정보 처리방침
      </Link>
    </p>
  );
}
