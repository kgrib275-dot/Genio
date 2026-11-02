import { Route, Routes } from "react-router-dom";
import { useHealth } from "@/lib/api/health";

function Home() {
  const { data, isError } = useHealth();
  return (
    <main className="mx-auto max-w-xl p-8">
      <h1 className="text-2xl font-bold">제니오</h1>
      <p className="mt-2 text-gray-600">말로 만드는 나만의 앱</p>
      <p className="mt-6 text-sm" data-testid="server-status">
        {isError ? "서버에 연결하지 못했어요." : data ? "서버 연결됨" : "서버 확인 중…"}
      </p>
    </main>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Home />} />
    </Routes>
  );
}
