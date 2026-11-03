"""마켓 번들 검증과 코드 로딩(설계서 §8).

검증: manifest 필수 항목, 타입별 파일, 파이썬 코드의 import 허용 목록, 위험한 이름 사용 금지,
네트워크 권한 선언 형식. 프로토타입 수준의 정적 검사이며, 정식 버전은 격리 실행으로 바꾼다.
"""

import ast
import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

ITEM_TYPES = ("template", "node", "connector", "prompt_pack")
REQUIRED_FILES = {
    "template": "template.json",
    "node": "node.py",
    "connector": "connector.py",
    "prompt_pack": "prompts.json",
}
ALLOWED_IMPORTS = {
    "json",
    "re",
    "math",
    "datetime",
    "typing",
    "base64",
    "urllib.parse",
    "string",
    "collections",
    "dataclasses",
    "nodes",
    "nodes.spec",
}
FORBIDDEN_NAMES = {
    "eval",
    "exec",
    "compile",
    "open",
    "__import__",
    "globals",
    "locals",
    "vars",
    "breakpoint",
    "input",
}


class BundleError(Exception):
    pass


def read_manifest(path: Path) -> dict[str, Any]:
    try:
        data = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise BundleError("manifest.json이 없어요.") from exc
    except json.JSONDecodeError as exc:
        raise BundleError("manifest.json 형식이 올바르지 않아요.") from exc
    if not isinstance(data, dict):
        raise BundleError("manifest.json은 객체여야 해요.")
    return data


def allowed_domains(manifest: dict[str, Any]) -> list[str]:
    out = []
    for p in manifest.get("permissions", []):
        if isinstance(p, str) and p.startswith("network:"):
            out.append(p.split(":", 1)[1].strip().lower())
    return out


def _check_python(file: Path) -> None:
    try:
        tree = ast.parse(file.read_text(encoding="utf-8"), filename=file.name)
    except SyntaxError as exc:
        raise BundleError(f"{file.name}에 문법 오류가 있어요: {exc.msg}") from exc
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name not in ALLOWED_IMPORTS:
                    raise BundleError(f"{file.name}: '{alias.name}' 모듈은 쓸 수 없어요.")
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if node.level or mod not in ALLOWED_IMPORTS:
                raise BundleError(f"{file.name}: '{mod}' 모듈은 쓸 수 없어요.")
        elif isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            raise BundleError(f"{file.name}: '{node.id}'는 쓸 수 없어요.")
        elif isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            raise BundleError(f"{file.name}: 밑줄 두 개로 시작하는 속성은 쓸 수 없어요.")


def validate_bundle(path: Path, manifest: dict[str, Any]) -> None:
    for key in ("key", "type", "name", "version"):
        if not manifest.get(key):
            raise BundleError(f"manifest.json에 '{key}'가 없어요.")
    item_type = manifest["type"]
    if item_type not in ITEM_TYPES:
        raise BundleError(f"알 수 없는 아이템 종류예요: {item_type}")
    required = path / REQUIRED_FILES[item_type]
    if not required.exists():
        raise BundleError(f"{REQUIRED_FILES[item_type]} 파일이 없어요.")
    for p in manifest.get("permissions", []):
        if not (isinstance(p, str) and p.startswith("network:") and "." in p):
            raise BundleError(f"권한 선언 형식이 올바르지 않아요: {p}")
    for py in path.glob("*.py"):
        _check_python(py)
    if item_type == "connector":
        actions = manifest.get("actions")
        if not isinstance(actions, list) or not actions:
            raise BundleError("커넥터는 actions를 하나 이상 선언해야 해요.")
        if not allowed_domains(manifest) and not manifest.get("smtp"):
            raise BundleError("커넥터는 접속할 네트워크 도메인(permissions)을 선언해야 해요.")
    if item_type in ("template", "prompt_pack"):
        try:
            json.loads(required.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise BundleError(f"{required.name} 형식이 올바르지 않아요.") from exc


_modules: dict[tuple[str, float], ModuleType] = {}


def load_module(file: Path, name: str) -> ModuleType:
    """검증을 통과한 번들 파이썬 파일을 불러온다(파일이 바뀌면 다시 읽음)."""
    key = (str(file), file.stat().st_mtime)
    if key in _modules:
        return _modules[key]
    _check_python(file)
    spec = importlib.util.spec_from_file_location(f"genio_market_{name}", file)
    if spec is None or spec.loader is None:
        raise BundleError(f"{file.name}을(를) 불러오지 못했어요.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _modules[key] = module
    return module


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))
