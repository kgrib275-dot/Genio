"""코드 단계 실행기. CodeRunner 인터페이스로 분리해 나중에 컨테이너 샌드박스로 바꿀 수 있게 한다.

지금 구현(RestrictedPythonRunner): 별도 파이썬 프로세스(-I)에서 RestrictedPython으로 실행한다.
- 타임아웃(기본 10초)이 지나면 프로세스를 죽인다.
- import는 허용 목록만. socket·os 등은 못 쓰므로 네트워크·파일 접근이 막힌다.
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Protocol

from api.config import get_settings
from api.engine import sandbox_client
from nodes import NodeError

ALLOWED_IMPORTS = ("json", "math", "re", "datetime", "statistics", "random", "string", "itertools")
_SANDBOX = Path(__file__).with_name("_code_sandbox.py")
MAX_OUTPUT_BYTES = 512 * 1024


def _child_env() -> dict[str, str]:
    env = {"PYTHONIOENCODING": "utf-8"}
    # Windows에서는 SYSTEMROOT가 없으면 파이썬이 시작하지 못한다
    for key in ("SYSTEMROOT", "PATH"):
        if key in os.environ:
            env[key] = os.environ[key]
    return env


class CodeRunner(Protocol):
    def run(self, code: str, inputs: dict[str, Any]) -> dict[str, Any]: ...


class RestrictedPythonRunner:
    def __init__(self, timeout: float | None = None) -> None:
        self.timeout = timeout or get_settings().genio_code_node_timeout_seconds

    def run(self, code: str, inputs: dict[str, Any]) -> dict[str, Any]:
        payload = json.dumps(
            {"code": code, "inputs": inputs, "allowed": list(ALLOWED_IMPORTS)}, ensure_ascii=False
        )
        try:
            proc = subprocess.run(  # noqa: S603 - 고정된 인터프리터와 스크립트만 실행
                [sys.executable, "-I", str(_SANDBOX)],
                input=payload.encode("utf-8"),
                capture_output=True,
                timeout=self.timeout,
                check=False,
                env=_child_env(),
            )
        except subprocess.TimeoutExpired as exc:
            raise NodeError(
                f"코드가 {self.timeout:.0f}초 안에 끝나지 않았어요. 반복문을 확인해 주세요."
            ) from exc
        out = proc.stdout[:MAX_OUTPUT_BYTES].decode("utf-8", errors="replace").strip()
        try:
            data = json.loads(out.splitlines()[-1]) if out else {}
        except (json.JSONDecodeError, IndexError) as exc:
            raise NodeError(
                "코드 실행 결과를 읽지 못했어요. result에 dict를 넣었는지 확인해 주세요."
            ) from exc
        if not isinstance(data, dict):
            raise NodeError("코드 실행 결과 형식이 올바르지 않아요.")
        if not data.get("ok"):
            raise NodeError(f"코드 실행 중 오류: {data.get('error', '알 수 없는 오류')}")
        result = data.get("result")
        if not isinstance(result, dict):
            return {"value": result}
        return result


class SandboxRunner:
    """v0.8: 별도 컨테이너의 코드 실행 서버(GENIO_SANDBOX_URL)에서 실행한다."""

    def __init__(self, timeout: float | None = None) -> None:
        self.timeout = timeout or get_settings().genio_code_node_timeout_seconds

    def run(self, code: str, inputs: dict[str, Any]) -> dict[str, Any]:
        return sandbox_client.run_remote("python", code, inputs, self.timeout)


def get_code_runner() -> CodeRunner:
    # 격리 서버를 설정했으면 그쪽으로, 아니면 지금처럼 서버 안에서 실행한다
    if sandbox_client.enabled():
        return SandboxRunner()
    return RestrictedPythonRunner()
