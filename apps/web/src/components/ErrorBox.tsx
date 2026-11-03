import { errorLines } from "@/lib/api/client";

/** 오류는 항상 두 줄: 무엇이 문제인지 + 어떻게 하면 되는지 */
export function ErrorBox({ error }: { error: unknown }) {
  if (!error) return null;
  const { message, hint } = errorLines(error);
  return (
    <div role="alert" className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm">
      <p className="font-medium text-red-900">{message}</p>
      {hint && <p className="mt-0.5 text-red-700">{hint}</p>}
    </div>
  );
}

export function Loading({ label = "불러오는 중…" }: { label?: string }) {
  return <p className="py-6 text-center text-sm text-slate-500">{label}</p>;
}
