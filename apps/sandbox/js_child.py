"""자바스크립트 실행기 자식 프로세스(QuickJS). stdin JSON → stdout JSON 한 줄.

QuickJS 안에서만 돈다: 파일·네트워크·프로세스 API가 없다. 시간·메모리 제한을 건다.
WRAPPER는 apps/api/engine/js_runner.py의 것과 같아야 한다(시험이 같은지 확인한다).
"""

import json
import sys
from typing import Any

MEMORY_LIMIT = 64 * 1024 * 1024
MAX_OUTPUT = 1_000_000

WRAPPER = """
(function (__inputs_json) {
  const inputs = JSON.parse(__inputs_json);
  const __out = (function (inputs) {
    let result;
    const __ret = (function () {
%s
    })();
    return __ret === undefined ? result : __ret;
  })(inputs);
  return JSON.stringify(__out === undefined ? null : __out);
})
"""


def run(req: dict[str, Any]) -> dict[str, Any]:
    try:
        import quickjs  # type: ignore[import-untyped]
    except ImportError:
        return {
            "ok": False,
            "kind": "error",
            "error": "자바스크립트 실행기가 설치되어 있지 않아요.",
        }
    timeout = max(1, int(req.get("timeout") or 10))
    ctx = quickjs.Context()
    ctx.set_time_limit(timeout)
    ctx.set_memory_limit(MEMORY_LIMIT)
    try:
        fn = ctx.eval(WRAPPER % str(req.get("code", "")))
        raw = fn(json.dumps(req.get("inputs") or {}, ensure_ascii=False, default=str))
    except quickjs.JSException as exc:
        msg = str(exc).splitlines()[0][:300]
        if "interrupted" in msg:
            return {"ok": False, "kind": "timeout", "error": f"{timeout}초 안에 끝나지 않았어요."}
        if "out of memory" in msg.lower():
            return {"ok": False, "kind": "memory", "error": "메모리를 너무 많이 썼어요."}
        return {"ok": False, "kind": "error", "error": msg}
    except MemoryError:
        return {"ok": False, "kind": "memory", "error": "메모리를 너무 많이 썼어요."}
    if not isinstance(raw, str):
        return {"ok": True, "result": {"value": None}}
    if len(raw) > MAX_OUTPUT:
        return {"ok": False, "kind": "output", "error": "결과가 너무 커요."}
    value = json.loads(raw)
    return {"ok": True, "result": value if isinstance(value, dict) else {"value": value}}


def main() -> None:
    req = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    print(json.dumps(run(req), ensure_ascii=False))


if __name__ == "__main__":
    main()
