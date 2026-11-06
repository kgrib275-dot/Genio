"""코드 단계 샌드박스 프로세스(code_runner가 `python -I`로 실행). stdin JSON → stdout JSON 한 줄."""

import json
import sys
import types
from typing import Any

# 코드에서 쓸 수 있게 열어 주는 이름(모듈별). 실제 모듈 객체는 코드에 넘기지 않고, 이 이름만 담은
# 껍데기(SimpleNamespace)를 넘긴다. 실제 모듈을 넘기면 `statistics.sys.modules["os"]`처럼 모듈이
# 안에 품은 sys·os 같은 모듈로 빠져나갈 수 있다(2026-11 보안 점검에서 확인).
_SAFE_NAMES: dict[str, tuple[str, ...] | None] = {
    "json": ("dumps", "loads", "JSONDecodeError"),
    "math": None,  # 공개 함수·상수 전부(수학 함수뿐이라 안전)
    "itertools": None,
    "re": (
        "compile",
        "match",
        "fullmatch",
        "search",
        "sub",
        "subn",
        "split",
        "findall",
        "finditer",
        "escape",
        "error",
        "IGNORECASE",
        "I",
        "MULTILINE",
        "M",
        "DOTALL",
        "S",
        "VERBOSE",
        "X",
        "ASCII",
        "A",
        "UNICODE",
        "U",
    ),
    "datetime": ("datetime", "date", "time", "timedelta", "timezone", "MINYEAR", "MAXYEAR"),
    "statistics": (
        "mean",
        "fmean",
        "geometric_mean",
        "harmonic_mean",
        "median",
        "median_low",
        "median_high",
        "median_grouped",
        "mode",
        "multimode",
        "pstdev",
        "pvariance",
        "stdev",
        "variance",
        "quantiles",
        "correlation",
        "covariance",
        "linear_regression",
        "StatisticsError",
    ),
    "random": (
        "random",
        "randint",
        "randrange",
        "choice",
        "choices",
        "sample",
        "shuffle",
        "uniform",
        "gauss",
        "seed",
        "triangular",
        "betavariate",
        "expovariate",
        "normalvariate",
        "lognormvariate",
        "getrandbits",
        "randbytes",
    ),
    # string.Formatter·Template은 속성 경로를 문자열로 따라가 가드를 피할 수 있어 열지 않는다
    "string": (
        "ascii_letters",
        "ascii_lowercase",
        "ascii_uppercase",
        "digits",
        "hexdigits",
        "octdigits",
        "punctuation",
        "printable",
        "whitespace",
        "capwords",
    ),
}


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
        # 하위 모듈(os.path, datetime.sys 등)이나 상대 import는 열지 않는다
        if level or name not in allowed or name not in _SAFE_NAMES:
            raise ImportError(
                f"'{name}' 모듈은 쓸 수 없어요. 쓸 수 있는 모듈: {', '.join(sorted(allowed))}"
            )
        return _proxy(name)

    proxies: dict[str, types.SimpleNamespace] = {}

    def _proxy(name: str) -> types.SimpleNamespace:
        if name not in proxies:
            real = __import__(name)
            names = _SAFE_NAMES[name]
            if names is None:
                names = tuple(n for n in dir(real) if not n.startswith("_"))
            proxies[name] = types.SimpleNamespace(
                **{n: getattr(real, n) for n in names if hasattr(real, n)}
            )
        return proxies[name]

    missing = object()

    def _guarded_getattr(obj: Any, name: str, default: Any = None, getter: Any = getattr) -> Any:
        value = safer_getattr(obj, name, missing, getter)
        if value is missing:
            if default is not None:
                return default
            raise AttributeError(f"'{name}'은(는) 없어요.")
        # 어떤 경로로든 실제 모듈 객체가 코드에 돌아오지 않게 한다(2중 방어)
        if isinstance(value, types.ModuleType):
            raise AttributeError(f"'{name}'은(는) 쓸 수 없어요.")
        return value

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
        "_getattr_": _guarded_getattr,
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
