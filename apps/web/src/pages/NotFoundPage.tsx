// v0.6 없는 주소로 왔을 때(두 줄 안내 + 처음 화면·사용설명서로 가는 길)
import { Compass } from "lucide-react";
import { Link } from "react-router-dom";

export default function NotFoundPage() {
  return (
    <div className="flex min-h-[70vh] items-center justify-center px-4 py-12">
      <div className="max-w-md text-center">
        <span className="mx-auto mb-4 inline-flex h-12 w-12 items-center justify-center rounded-2xl bg-indigo-50 text-indigo-600">
          <Compass className="h-6 w-6" />
        </span>
        <p className="text-sm font-semibold text-indigo-600">404</p>
        <h1 className="mt-1 text-lg font-bold text-slate-900">찾는 화면이 없어요.</h1>
        <p className="mt-1 text-sm text-slate-600">
          주소가 바뀌었거나 지워졌을 수 있어요. 처음 화면에서 다시 찾아 주세요.
        </p>
        <div className="mt-6 flex flex-wrap justify-center gap-2">
          <Link
            to="/"
            className="inline-flex items-center rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500"
          >
            처음 화면으로
          </Link>
          <Link
            to="/help"
            className="inline-flex items-center rounded-lg border border-slate-200 px-4 py-2 text-sm text-slate-700 hover:bg-slate-100"
          >
            사용설명서 보기
          </Link>
        </div>
      </div>
    </div>
  );
}
