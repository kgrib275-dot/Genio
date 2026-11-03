"""코드 단계 샌드박스 프로세스(code_runner가 `python -I`로 실행). stdin JSON → stdout JSON 한 줄."""

import json
import sys
from typing import Any


def main() -> None:
    req = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    allowed = set(req["allowed"])
    try:
        from RestrictedPython import compile_restricted, limited_builtins, safe_builtins
        from RestrictedPython.Eval import default_guarded_getitem, default_guarded_getiter
        from RestrictedPython.Guards import (
            full_write_guard,
            guarded_iter_unpack_sequence,
            guarded_unpack_sequence,
            safer_getattr,
        )
    except ImportError:
        print(json.dumps({"ok": False, "error": "실행 환경에 RestrictedPython이 없어요."}))
        return

    def _import(
        name: str, globals_: Any = None, locals_: Any = None, fromlist: Any = (), level: int = 0
    ) -> Any:
        if name.split(".")[0] not in allowed:
            raise ImportError(
                f"'{name}' 모듈은 쓸 수 없어요. 쓸 수 있는 모듈: {', '.join(sorted(allowed))}"
            )
        return __import__(name, globals_, locals_, fromlist, level)

    builtins = dict(safe_builtins)
    builtins.update(limited_builtins)
    builtins.update(
        {
            "__import__": _import,
            "dict": dict,
            "list": list,
            "set": set,
            "sum": sum,
            "min": min,
            "max": max,
            "sorted": sorted,
            "enumerate": enumerate,
            "any": any,
            "all": all,
            "map": map,
            "filter": filter,
            "reversed": reversed,
        }
    )
    glb: dict[str, Any] = {
        "__builtins__": builtins,
        "_getattr_": safer_getattr,
        "_getitem_": default_guarded_getitem,
        "_getiter_": default_guarded_getiter,
        "_iter_unpack_sequence_": guarded_iter_unpack_sequence,
        "_unpack_sequence_": guarded_unpack_sequence,
        "_write_": full_write_guard,
        "_inplacevar_": _inplace,
        "inputs": req["inputs"],
        "result": None,
    }
    try:
        byte_code = compile_restricted(req["code"], filename="<code-node>", mode="exec")
        exec(byte_code, glb)  # noqa: S102 - RestrictedPython으로 컴파일된 코드만 실행
        result = glb.get("result")
        json.dumps(result)
        print(json.dumps({"ok": True, "result": result}))
    except SyntaxError as exc:
        print(json.dumps({"ok": False, "error": f"문법 오류: {exc}"}))
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}))


def _inplace(op: str, x: Any, y: Any) -> Any:
    ops = {
        "+=": lambda a, b: a + b,
        "-=": lambda a, b: a - b,
        "*=": lambda a, b: a * b,
        "/=": lambda a, b: a / b,
        "//=": lambda a, b: a // b,
        "%=": lambda a, b: a % b,
    }
    if op not in ops:
        raise ValueError(f"지원하지 않는 연산자: {op}")
    return ops[op](x, y)


if __name__ == "__main__":
    main()
