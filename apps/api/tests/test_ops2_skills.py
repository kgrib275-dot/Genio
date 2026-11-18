"""스킬(SKILL.md): 읽기·가져오기·권한, 에이전트가 필요할 때만 본문을 읽는다."""

import io
import zipfile
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.engine import safe_http
from api.services import skills as svc
from api.tests.conftest import Team, add_llm
from api.tests.fakes import FakeAdapter, text_turn, tool_turn
from api.tests.test_v02_nodes import chain, inp, out

MD = """---
name: 환불 안내
description: 고객이 환불을 물을 때 따라야 할 순서
---
# 환불
1. 주문 번호를 묻는다.
2. 7일 안이면 환불 가능.
"""


def test_parse_skill_md_variants() -> None:
    p = svc.parse_skill_md(MD)
    assert p["name"] == "환불 안내" and p["description"].startswith("고객이")
    assert p["body"].startswith("# 환불")
    quoted = svc.parse_skill_md(
        '---\nname: "A 스킬"\ndescription: >\n  첫 줄\n  둘째 줄\n---\n본문'
    )
    assert quoted == {"name": "A 스킬", "description": "첫 줄 둘째 줄", "body": "본문"}
    bare = svc.parse_skill_md("# 제목만\n\n내용")
    assert bare["name"] == "제목만" and bare["description"] == ""
    crlf = svc.parse_skill_md(MD.replace("\n", "\r\n"))
    assert crlf["name"] == "환불 안내"


def test_clean_rules() -> None:
    from api.core.errors import AppError

    with pytest.raises(AppError) as e1:
        svc.clean({"name": "x", "description": "", "body": "b"})
    assert "설명" in e1.value.message and e1.value.hint
    with pytest.raises(AppError):
        svc.clean({"name": "", "description": "d", "body": "b"})
    with pytest.raises(AppError):
        svc.clean({"name": "x", "description": "d", "body": "가" * (svc.MAX_BODY + 1)})
    assert svc.clean({"name": "a/b<c>", "description": "d", "body": "b"})["name"] == "abc"


def _zip(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for k, v in files.items():
            z.writestr(k, v)
    return buf.getvalue()


def test_crud_import_and_permissions(client: TestClient, team: Team) -> None:
    base = f"/api/v1/workspaces/{team.ws}/skills"
    b = team.h("builder")
    made = client.post(base, json={"skill_md": MD}, headers=b)
    assert made.status_code == 201, made.text
    sid = made.json()["id"]
    dup = client.post(base, json={"skill_md": MD}, headers=b)
    assert dup.status_code == 409 and "같은 이름" in dup.json()["detail"]["message"]
    listed = client.get(base, headers=b).json()["skills"]
    assert [s["name"] for s in listed] == ["환불 안내"] and "body" not in listed[0]
    assert "7일 안이면" in client.get(f"{base}/{sid}", headers=b).json()["body"]
    up = client.put(
        f"{base}/{sid}",
        json={"name": "환불 안내", "description": "수정됨", "body": "새 본문"},
        headers=b,
    )
    assert up.status_code == 200 and up.json()["description"] == "수정됨"
    z = client.post(
        f"{base}/import",
        files={"file": ("pack.zip", _zip({"x/SKILL.md": MD.replace("환불 안내", "배송 안내")}))},
        headers=b,
    )
    assert z.status_code == 201 and z.json()["name"] == "배송 안내"
    md = client.post(
        f"{base}/import",
        files={"file": ("a.md", MD.replace("환불 안내", "교환 안내").encode())},
        headers=b,
    )
    assert md.status_code == 201
    bad = client.post(f"{base}/import", files={"file": ("a.exe", b"x")}, headers=b)
    assert bad.status_code == 422
    nozip = client.post(
        f"{base}/import", files={"file": ("a.zip", _zip({"readme.txt": "x"}))}, headers=b
    )
    assert nozip.status_code == 422 and "SKILL.md가 없어요" in nozip.json()["detail"]["message"]
    # 권한: 제작자 이상만
    assert client.get(base, headers=team.h("member")).status_code == 403
    assert client.post(base, json={"skill_md": MD}, headers=team.h("operator")).status_code == 403
    assert client.get(base).status_code == 401
    assert client.delete(f"{base}/{sid}", headers=b).status_code == 204
    assert client.get(f"{base}/{sid}", headers=b).status_code == 404


def test_agent_reads_skill_body_only_on_demand(
    client: TestClient, team: Team, fake_llm: FakeAdapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    add_llm(client, team)
    monkeypatch.setattr(
        safe_http, "request", lambda *a, **k: {"status": 200, "body": "", "headers": {}}
    )
    sid = client.post(
        f"/api/v1/workspaces/{team.ws}/skills", json={"skill_md": MD}, headers=team.h("builder")
    ).json()["id"]
    seen: dict[str, Any] = {}

    def second(messages: list[Any]) -> Any:
        seen["tool_result"] = messages[-1]["content"]
        return text_turn("7일 안이면 환불돼요.")(messages)

    fake_llm.script = [tool_turn("요령을 읽어요.", ("use_skill", {"name": "환불 안내"})), second]
    g = chain(
        inp("message"),
        {
            "id": "n2",
            "type": "agent",
            "data": {"query": "{{n1.message}}", "skill_ids": [sid, "지워진-id"]},
        },
        out("{{n2.text}}"),
    )
    app_id = client.post(
        f"/api/v1/workspaces/{team.ws}/apps", json={"name": "스킬앱"}, headers=team.h("builder")
    ).json()["id"]
    client.put(f"/api/v1/apps/{app_id}/draft", json={"graph": g}, headers=team.h("builder"))
    run = client.post(
        f"/api/v1/apps/{app_id}/runs",
        json={"input": {"message": "환불 되나요?"}},
        headers=team.h("builder"),
    ).json()
    d = client.get(f"/api/v1/runs/{run['id']}", headers=team.h("builder")).json()
    assert d["status"] == "succeeded", d["error"]
    assert "7일 안이면 환불 가능" in seen["tool_result"]  # 본문은 요청했을 때만 전달됐다
    assert d["output"]["text"] == "7일 안이면 환불돼요."
