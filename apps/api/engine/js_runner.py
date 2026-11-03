"""자바스크립트 코드 단계 실행(QuickJS, 기능 정의서 §1 데이터 단계).

QuickJS 안에서만 돈다: 파일·네트워크·프로세스 API가 없다. 시간·메모리 제한을 건다.
코드는 inputs로 값을 받고 result에 결과를 넣는다(return으로 돌려줘도 된다).
"""

import json
from typing import Any

from api.config import get_settings
from nodes import NodeError

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


def run_javascript(code: str, inputs: dict[str, Any]) -> dict[str, Any]:
    try:
        import quickjs  # type: ignore[import-untyped]
    except ImportError as exc:  # pragma: no cover - 설치 누락
        raise NodeError(
            "자바스크립트 실행기가 설치되어 있지 않아요. 관리자에게 알려 주세요."
        ) from exc
    timeout = max(1, int(get_settings().genio_code_node_timeout_seconds))
    ctx = quickjs.Context()
    ctx.set_time_limit(timeout)
    ctx.set_memory_limit(MEMORY_LIMIT)
    try:
        fn = ctx.eval(WRAPPER % code)
        raw = fn(json.dumps(inputs, ensure_ascii=False, default=str))
    except quickjs.JSException as exc:
        msg = str(exc).splitlines()[0][:300]
        if "interrupted" in msg:
            raise NodeError(
                f"코드가 {timeout}초 안에 끝나지 않았어요. 반복문을 확인해 주세요."
            ) from None
        if "out of memory" in msg.lower():
            raise NodeError("코드가 메모리를 너무 많이 써서 멈췄어요.") from None
        raise NodeError(f"자바스크립트 코드에서 오류가 났어요: {msg}") from None
    if not isinstance(raw, str):
        return {"value": None}
    if len(raw) > MAX_OUTPUT:
        raise NodeError("코드 결과가 너무 커요(1MB 이하로 줄여 주세요).")
    value = json.loads(raw)
    return value if isinstance(value, dict) else {"value": value}
