"""코드 한 건을 자식 프로세스에서 실행한다(파이썬: RestrictedPython, 자바스크립트: QuickJS).

- 실행마다 새 프로세스: 무한 반복·메모리 폭주가 서버를 멈추지 못한다(벽시계 시간이 지나면 죽인다).
- 리눅스에서는 자식에 CPU·메모리·파일 수·파일 크기·프로세스 수 제한을 건다(limits_wrapper).
- 결과 크기 상한. 비밀값(환경 변수)은 자식에 넘기지 않는다.
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ALLOWED_IMPORTS = ("json", "math", "re", "datetime", "statistics", "random", "string", "itertools")
MAX_OUTPUT_BYTES = 1024 * 1024  # 결과 1MB 상한(자바스크립트 실행기 상한과 같다)
MIN_TIMEOUT, MAX_TIMEOUT = 1.0, 60.0
DEFAULT_MEMORY_MB = 512


def memory_mb() -> int:
    try:
        return max(128, int(os.environ.get("SANDBOX_MEMORY_MB", DEFAULT_MEMORY_MB)))
    except ValueError:
        return DEFAULT_MEMORY_MB


def python_child() -> Path:
    """파이썬 실행기. 컨테이너에서는 py_child.py(= API의 _code_sandbox.py 복사본), 저장소에서는 원본."""
    local = HERE / "py_child.py"
    if local.is_file():
        return local
    return HERE.parent / "api" / "engine" / "_code_sandbox.py"


def _env() -> dict[str, str]:
    env = {"PYTHONIOENCODING": "utf-8"}
    for key in ("SYSTEMROOT", "PATH"):  # 윈도에서 파이썬이 시작하려면 필요
        if key in os.environ:
            env[key] = os.environ[key]
    return env


def clamp_timeout(value: Any) -> float:
    try:
        t = float(value)
    except (TypeError, ValueError):
        t = 10.0
    return max(MIN_TIMEOUT, min(t, MAX_TIMEOUT))


def _spawn(child: Path, payload: dict[str, Any], timeout: float) -> tuple[str, bytes]:
    """('ok'|'timeout'|'output', 표준 출력). 자식은 resource 제한을 건 뒤 실행기를 돌린다."""
    cmd = [
        sys.executable,
        "-I",
        str(HERE / "limits_wrapper.py"),
        str(int(timeout) + 1),
        str(memory_mb()),
        str(child),
    ]
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    proc = subprocess.Popen(  # noqa: S603 - 고정된 인터프리터와 우리 스크립트만 실행
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=_env(),
        close_fds=True,
    )
    try:
        out, _ = proc.communicate(data, timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        return "timeout", b""
    if len(out) > MAX_OUTPUT_BYTES:
        return "output", b""
    return "ok", out


def _parse(raw: bytes) -> dict[str, Any]:
    text = raw.decode("utf-8", errors="replace").strip()
    try:
        data = json.loads(text.splitlines()[-1]) if text else {}
    except (json.JSONDecodeError, IndexError):
        data = {}
    if not isinstance(data, dict) or "ok" not in data:
        return {
            "ok": False,
            "kind": "error",
            "error": "코드 실행 결과를 읽지 못했어요. result에 dict를 넣었는지 확인해 주세요.",
        }
    return data


def run_code(language: str, code: str, inputs: dict[str, Any], timeout: float) -> dict[str, Any]:
    """{'ok': True, 'result': {...}} 또는 {'ok': False, 'kind': 'error|timeout|memory|output', 'error': str}"""
    timeout = clamp_timeout(timeout)
    if language == "python":
        child = python_child()
        payload: dict[str, Any] = {
            "code": code,
            "inputs": inputs,
            "allowed": list(ALLOWED_IMPORTS),
        }
    elif language == "javascript":
        child = HERE / "js_child.py"
        payload = {"code": code, "inputs": inputs, "timeout": int(timeout)}
    else:
        return {"ok": False, "kind": "error", "error": "지원하지 않는 언어예요."}
    status, out = _spawn(child, payload, timeout)
    if status == "timeout":
        return {"ok": False, "kind": "timeout", "error": f"{timeout:.0f}초 안에 끝나지 않았어요."}
    if status == "output":
        return {"ok": False, "kind": "output", "error": "결과가 너무 커요."}
    data = _parse(out)
    if not data.get("ok"):
        kind = str(data.get("kind") or "error")
        err = str(data.get("error") or "알 수 없는 오류")[:300]
        if kind == "error" and "MemoryError" in err:
            kind = "memory"
        return {"ok": False, "kind": kind, "error": err}
    result = data.get("result")
    return {"ok": True, "result": result if isinstance(result, dict) else {"value": result}}
