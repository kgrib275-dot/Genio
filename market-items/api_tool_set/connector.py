"""API 도구 묶음: 동작 없이 가져온 도구 목록만 보관한다(호출은 플랫폼이 HTTP와 같은 길로 처리)."""

import json
from typing import Any


def test(secrets: dict[str, Any], net: Any) -> dict[str, Any]:
    try:
        ops = json.loads(str(secrets.get("operations") or "[]"))
    except json.JSONDecodeError:
        return {"message": "도구 목록이 깨졌어요. 명세를 다시 가져와 주세요."}
    base = str(secrets.get("base_url") or "").strip()
    note = "" if base else " 기본 주소가 비어 있어요."
    return {"message": f"도구 {len(ops)}개가 들어 있어요.{note} 실제 호출은 흐름에서 시험하세요."}
