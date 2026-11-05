"""v0.9 이미지 만들기·파일 만들기·파일 내려받기.

- 이미지: OpenAI 호환 어댑터의 요청·응답(b64·주소·dall-e-3), 오류 번역, 비용 추정, 단계 실행.
- 파일: 형식별 내용(엑셀·워드·CSV…), 수식 방지, 한도, 파일 이름.
- 내려받기: 로그인한 사람(역할별), 서명 링크(만료·변조·다른 앱·멤버 전용), 챗 답·입력 폼·일괄 실행 결과.
"""

import base64
import io
import json
import time
from typing import Any

import httpx2
import pytest
from fastapi.testclient import TestClient

from api.llm.base import LlmError
from api.llm.openai_adapter import OpenAIAdapter
from api.services import file_export, file_links, run_files
from api.tests.conftest import ROLES, Team, add_llm
from api.tests.fakes import FakeAdapter, tiny_png
from api.tests.test_llm_adapters import Recorder
from api.tests.test_v02_features import chat, deploy, parse_sse
from api.tests.test_v05_engine import make_app, start, validate
from nodes import NodeError

PNG = tiny_png()


# ---------------- 파일 만들기(순수 함수) ----------------
def _build(fmt: str, **kw: Any) -> bytes:
    args: dict[str, Any] = {
        "source": "text",
        "text": "",
        "rows": None,
        "columns": None,
        "bom": True,
        "sheet": "결과",
    }
    args.update(kw)
    return file_export.build_file(fmt, **args)


ROWS = [
    {"이름": "김철수", "점수": 90, "메모": "=SUM(A1:A9)"},
    {"이름": "이영희", "점수": 85.5, "메모": "+1234 @회의"},
    {"이름": "박민수", "점수": None, "메모": {"a": 1}},
]


def test_csv_bom_columns_and_formula_guard() -> None:
    data = _build("csv", source="table", rows=ROWS)
    assert data.startswith(b"\xef\xbb\xbf")
    text = data.decode("utf-8-sig")
    lines = text.splitlines()
    assert lines[0] == "이름,점수,메모"
    assert "'=SUM(A1:A9)" in lines[1] and "'+1234 @회의" in lines[2]
    assert '{""a"": 1}' in lines[3]
    assert not _build("csv", source="table", rows=ROWS, bom=False).startswith(b"\xef\xbb\xbf")
    picked = _build("csv", source="table", rows=ROWS, columns=["점수", "이름"]).decode("utf-8-sig")
    assert picked.splitlines()[0] == "점수,이름"


def test_xlsx_opens_and_formulas_stay_text() -> None:
    from openpyxl import load_workbook

    data = _build("xlsx", source="table", rows=ROWS, sheet="성적/표")
    wb = load_workbook(io.BytesIO(data))
    ws = wb.active
    assert ws is not None and ws.title == "성적 표"
    assert [c.value for c in ws[1]] == ["이름", "점수", "메모"]
    assert ws["A2"].value == "김철수" and ws["B3"].value == "85.5"
    memo = ws["C2"]
    assert memo.value == "=SUM(A1:A9)" and memo.data_type == "s"  # 수식이 아니라 글


def test_docx_markdown_and_table() -> None:
    import docx

    md = "# 주간 보고\n\n이번 주는 **중요한** 일이 있었어요.\n계속 이어지는 글.\n\n- 첫째 할 일\n- 둘째 할 일\n1. 순서 하나\n\n## 다음 주\n끝."
    d = docx.Document(io.BytesIO(_build("docx", text=md)))
    styles = [p.style.name if p.style else "" for p in d.paragraphs]
    texts = [p.text for p in d.paragraphs]
    assert texts[0] == "주간 보고" and styles[0].startswith("Heading 1")
    para = next(p for p in d.paragraphs if p.text.startswith("이번 주는"))
    assert any(r.bold and r.text == "중요한" for r in para.runs)
    assert para.text == "이번 주는 중요한 일이 있었어요. 계속 이어지는 글."
    assert styles.count("List Bullet") == 2 and "List Number" in styles
    assert "다음 주" in texts and any(s.startswith("Heading 2") for s in styles)
    t = docx.Document(io.BytesIO(_build("docx", source="table", rows=ROWS))).tables[0]
    assert t.rows[0].cells[0].text == "이름" and t.rows[1].cells[1].text == "90"
    assert any(r.bold for r in t.rows[0].cells[0].paragraphs[0].runs)


def test_text_json_formats_and_filenames() -> None:
    assert _build("txt", text="안녕").decode() == "안녕"
    assert _build("md", text="# 제목").decode() == "# 제목"
    assert json.loads(_build("json", source="table", rows=ROWS))[0]["이름"] == "김철수"
    assert json.loads(_build("json", text='{"a": 1}')) == {"a": 1}
    assert json.loads(_build("json", text="그냥 글")) == {"text": "그냥 글"}
    # 글에서 표를 만들면 줄마다 한 칸
    assert _build("csv", text="가\n나\n").decode("utf-8-sig").splitlines() == ["내용", "가", "나"]
    assert file_export.safe_filename("../../etc/passwd", "txt") == "etc passwd.txt"
    assert file_export.safe_filename('보고서: "최종"/v2.xlsx', "xlsx") == "보고서 최종 v2.xlsx"
    assert file_export.safe_filename("   ", "csv") == "파일.csv"
    assert len(file_export.safe_filename("가" * 500, "docx")) <= 105


def test_file_caps_and_empty_table(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(NodeError, match="비어 있어요"):
        _build("xlsx", source="table", rows=[])
    monkeypatch.setattr(file_export, "MAX_ROWS", 3)
    with pytest.raises(NodeError, match="줄이 너무 많아요"):
        _build("csv", source="table", rows=[{"a": i} for i in range(4)])
    monkeypatch.setattr(file_export, "MAX_ROWS", 50_000)
    monkeypatch.setattr(file_export, "MAX_FILE_BYTES", 100)
    with pytest.raises(NodeError, match="파일이 너무 커요"):
        _build("txt", text="가" * 100)
    with pytest.raises(NodeError, match="파일 형식"):
        _build("pdf", text="x")


# ---------------- 이미지 어댑터(진짜 SDK + 가짜 전송) ----------------
def _img_adapter(rec: Recorder) -> OpenAIAdapter:
    return OpenAIAdapter("sk-test", http_client=httpx2.Client(transport=httpx2.MockTransport(rec)))


B64 = base64.b64encode(PNG).decode()


def test_gpt_image_request_and_b64_response() -> None:
    rec = Recorder(
        lambda r: httpx2.Response(
            200,
            json={
                "created": 1,
                "data": [{"b64_json": B64}, {"b64_json": B64, "revised_prompt": "다듬은 글"}],
                "usage": {"input_tokens": 30, "output_tokens": 1000, "total_tokens": 1030},
            },
        )
    )
    res = _img_adapter(rec).generate_images(
        model="gpt-image-1", prompt="고양이", size="1536x1024", count=2
    )
    body = rec.body()
    assert rec.requests[0].url.path.endswith("/images/generations")
    assert body == {"model": "gpt-image-1", "prompt": "고양이", "size": "1536x1024", "n": 2}
    assert [i.b64 for i in res.images] == [B64, B64]
    assert res.images[1].revised_prompt == "다듬은 글"
    assert (res.input_tokens, res.output_tokens) == (30, 1000)


def test_dall_e_3_one_per_call_and_native_size() -> None:
    rec = Recorder(
        lambda r: httpx2.Response(200, json={"created": 1, "data": [{"url": "https://x/y.png"}]})
    )
    res = _img_adapter(rec).generate_images(
        model="dall-e-3", prompt="산", size="1536x1024", count=3
    )
    assert len(rec.requests) == 3 and len(res.images) == 3
    assert rec.body()["n"] == 1 and rec.body()["size"] == "1792x1024"
    assert res.images[0].url == "https://x/y.png" and res.images[0].b64 is None


def _err(status: int, code: str, message: str) -> Recorder:
    return Recorder(
        lambda r: httpx2.Response(
            status, json={"error": {"message": message, "type": "x", "code": code}}
        )
    )


@pytest.mark.parametrize(
    ("status", "code", "message", "expect"),
    [
        (400, "content_policy_violation", "blocked by safety system", "안전 규칙"),
        (400, "invalid_value", "Invalid size '999x999'", "이미지 크기"),
        (400, "bad", "something else", "받아들이지 않았어요"),
        (404, "model_not_found", "The model does not exist", "이미지 모델"),
        (429, "insufficient_quota", "You exceeded your current quota", "한도를 넘었어요"),
        (401, "invalid_api_key", "Incorrect API key sk-test-secret", "권한이 없거나"),
    ],
)
def test_image_error_mapping(status: int, code: str, message: str, expect: str) -> None:
    adapter = _img_adapter(_err(status, code, message))
    with pytest.raises(LlmError) as exc:
        adapter.generate_images(model="gpt-image-1", prompt="x", size="1024x1024", count=1)
    assert expect in exc.value.message and exc.value.hint
    assert "sk-test" not in exc.value.message + exc.value.hint  # 키·원문 오류 노출 금지
    assert "Incorrect" not in exc.value.message + exc.value.hint


# ---------------- 앱 만들기 도우미 ----------------
IMG_NODE: dict[str, Any] = {
    "id": "img",
    "type": "image_generate",
    "data": {"label": "그림", "prompt": "{{n1.subject}} 사진", "style": "수채화", "count": 2},
}


def _wf(
    nodes: list[dict[str, Any]], edges: list[tuple[str, str]], fields: list[str]
) -> dict[str, Any]:
    return {
        "nodes": [
            {"id": "n1", "type": "input", "data": {"fields": [{"key": k} for k in fields]}},
            *nodes,
        ],
        "edges": [{"id": f"e{i}", "source": a, "target": b} for i, (a, b) in enumerate(edges)],
    }


def _image_app(client: TestClient, team: Team, *, chat_app: bool = False) -> str:
    field = "message" if chat_app else "subject"
    prompt = "{{n1.message}}" if chat_app else "{{n1.subject}} 사진"
    graph = _wf(
        [
            {**IMG_NODE, "data": {**IMG_NODE["data"], "prompt": prompt}},
            {
                "id": "out",
                "type": "output",
                "data": {"template": "그림 {{img.count}}장을 만들었어요"},
            },
        ],
        [("n1", "img"), ("img", "out")],
        [field],
    )
    h = team.h("builder")
    app_id: str = client.post(
        f"/api/v1/workspaces/{team.ws}/apps",
        json={
            "name": "그림 챗" if chat_app else "그림 만들기",
            "type": "chat" if chat_app else "workflow",
        },
        headers=h,
    ).json()["id"]
    assert (
        client.put(f"/api/v1/apps/{app_id}/draft", json={"graph": graph}, headers=h).status_code
        == 200
    )
    client.post(f"/api/v1/apps/{app_id}/versions", json={}, headers=h)
    return app_id


# ---------------- 이미지 만들기 단계 ----------------
def test_image_step_saves_files_and_estimates_cost(
    client: TestClient, team: Team, fake_llm: FakeAdapter
) -> None:
    add_llm(client, team, provider="openai", model="gpt-4o-mini")
    app_id = _image_app(client, team)
    assert validate(client, team, app_id)["valid"]
    d = start(client, team, app_id, {"subject": "고양이"})
    assert d["status"] == "succeeded", d["error"]
    call = next(c for c in fake_llm.calls if c["kind"] == "image")
    assert call["model"] == "gpt-image-1" and call["count"] == 2 and call["size"] == "1024x1024"
    assert "고양이 사진" in call["prompt"] and "[스타일·피할 것] 수채화" in call["prompt"]
    step = next(s for s in d["steps"] if s["node_id"] == "img")
    out = step["output"]
    assert out["count"] == 2 and out["first_file_id"] == out["files"][0]["id"]
    assert out["revised_prompt"].startswith("다듬은 설명")
    assert "이미지 2장" in step["summary"]
    # 비용은 장당 추정(0.04 × 2), 토큰은 올리지 않는다
    assert d["cost"] == pytest.approx(0.08)
    # 실행 상세가 파일 목록을 준다
    assert [f["id"] for f in d["files"]] == [f["id"] for f in out["files"]]
    assert all(f["kind"] == "image" and f["mime"] == "image/png" for f in d["files"])
    # 로그인한 사람은 내려받는다
    h = team.h("builder")
    r = client.get(f"/api/v1/runs/{d['id']}/files/{d['files'][0]['id']}?inline=1", headers=h)
    assert r.status_code == 200 and r.content == PNG
    assert r.headers["content-type"] == "image/png" and r.headers["content-disposition"].startswith(
        "inline"
    )
    assert r.headers["x-content-type-options"] == "nosniff"
    r = client.get(f"/api/v1/runs/{d['id']}/files/{d['files'][0]['id']}", headers=h)
    assert r.headers["content-disposition"].startswith("attachment")


def test_image_step_errors_are_two_lines(
    client: TestClient, team: Team, fake_llm: FakeAdapter
) -> None:
    add_llm(client, team, provider="openai", model="gpt-4o-mini")
    app_id = _image_app(client, team)
    fake_llm.image_error = LlmError(
        "이미지 만들기 요청이 AI의 안전 규칙에 걸렸어요.", "표현을 바꿔 다시 시도하세요."
    )
    d = start(client, team, app_id, {"subject": "x"})
    assert d["status"] == "failed" and "안전 규칙" in d["error"] and "표현을 바꿔" in d["error"]
    fake_llm.image_error = None
    fake_llm.image_bytes = b"<html>not an image</html>"
    d = start(client, team, app_id, {"subject": "x"})
    assert d["status"] == "failed" and "그림이 아닌 내용" in d["error"]


def test_image_step_needs_capable_connection(
    client: TestClient, team: Team, fake_llm: FakeAdapter
) -> None:
    app_id = _image_app(client, team)
    d = start(client, team, app_id, {"subject": "x"})
    assert d["status"] == "failed" and "AI 연결이 없어요" in d["error"]
    add_llm(client, team, provider="anthropic", model="claude-sonnet-5-5")
    d = start(client, team, app_id, {"subject": "x"})
    assert d["status"] == "failed" and "이미지를 만들 수 있는 AI 연결" in d["error"]


def test_image_download_over_limit_and_url_path(
    client: TestClient, team: Team, fake_llm: FakeAdapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    from api.services import image_gen

    add_llm(client, team, provider="openai", model="gpt-4o-mini")
    app_id = _image_app(client, team)
    monkeypatch.setattr(image_gen, "MAX_IMAGE_BYTES", 10)
    d = start(client, team, app_id, {"subject": "x"})
    assert d["status"] == "failed" and "너무 커요" in d["error"]


def test_node_test_marks_image_and_file_nodes_risky(client: TestClient, team: Team) -> None:
    app_id = _image_app(client, team)
    r = client.post(
        f"/api/v1/apps/{app_id}/nodes/img/test-inputs", json={}, headers=team.h("builder")
    )
    assert r.status_code == 200 and r.json()["risky"] is True and "그림" in r.json()["warn"]


# ---------------- 파일 만들기 단계 ----------------
def _export_graph(fmt: str = "xlsx", **data: Any) -> dict[str, Any]:
    node = {
        "id": "f",
        "type": "file_export",
        "data": {"format": fmt, "filename": "{{n1.name}}-보고서", **data},
    }
    return _wf(
        [node, {"id": "out", "type": "output", "data": {"template": "{{f.filename}}"}}],
        [("n1", "f"), ("f", "out")],
        ["name"],
    )


def _file_app(
    client: TestClient, team: Team, graph: dict[str, Any], name: str = "보고서 파일"
) -> str:
    app_id = make_app(client, team, graph, name=name)
    client.post(f"/api/v1/apps/{app_id}/versions", json={}, headers=team.h("builder"))
    return app_id


def test_file_export_step_xlsx_table(client: TestClient, team: Team) -> None:
    app_id = _file_app(
        client,
        team,
        _export_graph(
            "xlsx", source="table", rows=json.dumps(ROWS, ensure_ascii=False), columns="이름, 점수"
        ),
    )
    d = start(client, team, app_id, {"name": "주간"})
    assert d["status"] == "succeeded", d["error"]
    assert d["output"]["text"] == "주간-보고서.xlsx"
    f = d["files"][0]
    assert (
        f["filename"] == "주간-보고서.xlsx"
        and f["kind"] == "file"
        and f["mime"] == file_export.XLSX_MIME
    )
    r = client.get(f"/api/v1/runs/{d['id']}/files/{f['id']}", headers=team.h("operator"))
    assert r.status_code == 200
    from openpyxl import load_workbook

    ws = load_workbook(io.BytesIO(r.content)).active
    assert (
        ws is not None
        and [c.value for c in ws[1]] == ["이름", "점수"]
        and ws["A2"].value == "김철수"
    )
    assert (
        "attachment" in r.headers["content-disposition"]
        and "filename*=UTF-8''" in r.headers["content-disposition"]
    )
    step = next(s for s in d["steps"] if s["node_id"] == "f")
    assert "'주간-보고서.xlsx' 파일을 만들었어요" in step["summary"]


def test_file_export_step_errors(client: TestClient, team: Team) -> None:
    empty = _file_app(client, team, _export_graph("md", text="  "), name="빈 내용")
    d = start(client, team, empty, {"name": "a"})
    assert d["status"] == "failed" and "내용" in d["error"]
    no_rows = _file_app(client, team, _export_graph("csv", source="table", rows="[]"), name="빈 표")
    d = start(client, team, no_rows, {"name": "a"})
    assert d["status"] == "failed" and "목록이 비어 있어요" in d["error"]


def test_files_listed_only_from_this_run_and_not_uploads(client: TestClient, team: Team) -> None:
    app_id = _file_app(client, team, _export_graph("txt", text="안녕 {{n1.name}}"))
    d1 = start(client, team, app_id, {"name": "하나"})
    d2 = start(client, team, app_id, {"name": "둘"})
    ids1 = {f["id"] for f in d1["files"]}
    ids2 = {f["id"] for f in d2["files"]}
    assert ids1 and ids2 and not ids1 & ids2
    # 다른 실행의 파일 id로는 받을 수 없다
    other = next(iter(ids2))
    r = client.get(f"/api/v1/runs/{d1['id']}/files/{other}", headers=team.h("builder"))
    assert r.status_code == 404
    # 입력으로 올린 파일 id 글자만 든 단계 출력은 결과 파일로 치지 않는다
    up = client.post(
        f"/api/v1/workspaces/{team.ws}/files",
        files={"file": ("a.txt", io.BytesIO(b"hi"), "text/plain")},
        headers=team.h("builder"),
    ).json()["id"]
    assert run_files._candidates({"file": up, "file_id": up}) == []


@pytest.mark.parametrize("role", ROLES)
def test_run_file_endpoints_permissions(client: TestClient, team: Team, role: str) -> None:
    app_id = _file_app(client, team, _export_graph("txt", text="안녕"))
    d = start(client, team, app_id, {"name": "권한"})
    fid = d["files"][0]["id"]
    allowed = role in ("owner", "admin", "builder", "operator")
    lst = client.get(f"/api/v1/runs/{d['id']}/files", headers=team.h(role))
    dl = client.get(f"/api/v1/runs/{d['id']}/files/{fid}", headers=team.h(role))
    assert (lst.status_code == 200) == allowed, (role, lst.status_code)
    assert (dl.status_code == 200) == allowed, (role, dl.status_code)
    if allowed:
        assert dl.content == "안녕".encode()


def test_run_file_endpoints_reject_anonymous_and_outsider(
    client: TestClient, team: Team, outsider: dict[str, str]
) -> None:
    app_id = _file_app(client, team, _export_graph("txt", text="안녕"))
    d = start(client, team, app_id, {"name": "x"})
    fid = d["files"][0]["id"]
    assert client.get(f"/api/v1/runs/{d['id']}/files").status_code == 401
    assert client.get(f"/api/v1/runs/{d['id']}/files/{fid}").status_code == 401
    for url in (f"/api/v1/runs/{d['id']}/files", f"/api/v1/runs/{d['id']}/files/{fid}"):
        assert client.get(url, headers=outsider).status_code in (403, 404)


# ---------------- 서명 링크 ----------------
def test_link_signature_rules() -> None:
    link = file_links.sign("app-1", "file-1")
    assert file_links.verify("app-1", "file-1", str(link["sig"]), int(link["exp"]))
    assert not file_links.verify("app-2", "file-1", str(link["sig"]), int(link["exp"]))
    assert not file_links.verify("app-1", "file-2", str(link["sig"]), int(link["exp"]))
    assert not file_links.verify("app-1", "file-1", "0" * 40, int(link["exp"]))
    assert not file_links.verify("app-1", "file-1", str(link["sig"]), int(link["exp"]) + 5)
    old = file_links.sign("app-1", "file-1", ttl=-5)
    assert not file_links.verify("app-1", "file-1", str(old["sig"]), int(old["exp"]))
    far = file_links.sign("app-1", "file-1", ttl=10 * 24 * 3600)
    assert not file_links.verify("app-1", "file-1", str(far["sig"]), int(far["exp"]))


def _public_url(token: str, f: dict[str, Any], **extra: str) -> str:
    q = f"sig={f['sig']}&exp={f['exp']}" + "".join(f"&{k}={v}" for k, v in extra.items())
    return f"/api/v1/public/apps/{token}/files/{f['id']}?{q}"


def test_public_chat_answer_carries_signed_files(
    client: TestClient, team: Team, fake_llm: FakeAdapter
) -> None:
    add_llm(client, team, provider="openai", model="gpt-4o-mini")
    app_id = _image_app(client, team, chat_app=True)
    token = deploy(client, team, app_id)
    ev = chat(client, token, "바다")
    answer = next(d for n, d in ev if n == "answer")
    files = answer["files"]
    assert len(files) == 2 and all(f["kind"] == "image" and f["sig"] and f["exp"] for f in files)
    assert all("node_id" not in f for f in files)  # 내부 단계 이름은 내보내지 않는다
    f = files[0]
    r = client.get(_public_url(token, f, inline="1"))
    assert (
        r.status_code == 200
        and r.content == PNG
        and r.headers["content-disposition"].startswith("inline")
    )
    assert "sandbox" in r.headers["content-security-policy"]
    assert client.get(_public_url(token, f)).headers["content-disposition"].startswith("attachment")
    # 변조·만료·서명 없음
    bad = {**f, "sig": "0" * 40}
    assert client.get(_public_url(token, bad)).status_code == 403
    assert client.get(_public_url(token, {**f, "exp": int(f["exp"]) + 1})).status_code == 403
    expired = file_links.sign(app_id, f["id"], ttl=-60)
    assert client.get(_public_url(token, {"id": f["id"], **expired})).status_code == 403
    assert client.get(f"/api/v1/public/apps/{token}/files/{f['id']}").status_code == 403
    denied = client.get(_public_url(token, bad)).json()["detail"]
    assert denied["message"] and denied["hint"]
    # 없는 파일·다른 앱의 파일은 받을 수 없다(서명이 있어도)
    assert (
        client.get(
            _public_url(token, {"id": "nope", **file_links.sign(app_id, "nope")})
        ).status_code
        == 404
    )
    other = _file_app(client, team, _export_graph("txt", text="다른 앱"), name="다른 앱")
    od = start(client, team, other, {"name": "x"})
    other_file = od["files"][0]["id"]
    forged = {"id": other_file, **file_links.sign(app_id, other_file)}
    assert client.get(_public_url(token, forged)).status_code == 404
    # 다른 앱의 토큰으로 이 앱의 서명 링크는 안 통한다
    other_token = deploy(client, team, other)
    assert client.get(_public_url(other_token, f)).status_code in (403, 404)
    # 지난 대화를 다시 열면 새로 서명한 링크가 온다
    sid = next(d for n, d in ev if n == "session")["session_id"]
    hist = client.get(f"/api/v1/public/apps/{token}/sessions/{sid}/messages").json()
    with_files = [m for m in hist if m.get("files")]
    assert with_files and with_files[0]["files"][0]["id"] == f["id"]
    assert client.get(_public_url(token, with_files[0]["files"][0])).status_code == 200


def test_members_only_app_needs_login_for_files(
    client: TestClient, team: Team, fake_llm: FakeAdapter
) -> None:
    add_llm(client, team, provider="openai", model="gpt-4o-mini")
    app_id = _image_app(client, team, chat_app=True)
    h = team.h("builder")
    dep = client.post(
        f"/api/v1/apps/{app_id}/deployments",
        json={"channel": "share_link", "access": "roles", "allowed_roles": ["member", "operator"]},
        headers=h,
    ).json()
    token = dep["public_token"]
    # 로그인한 멤버가 챗으로 답을 받는다
    res = client.post(
        f"/api/v1/public/apps/{token}/chat", json={"message": "산"}, headers=team.h("member")
    )
    assert res.status_code == 200
    ev = parse_sse(res.text)
    f = next(d for n, d in ev if n == "answer")["files"][0]
    assert client.get(_public_url(token, f)).status_code == 401  # 로그인 없이는 안 됨
    assert client.get(_public_url(token, f), headers=team.h("member")).status_code == 200
    assert client.get(_public_url(token, f), headers=team.h("builder")).status_code in (200, 403)


def test_public_form_result_has_signed_files(client: TestClient, team: Team) -> None:
    app_id = _file_app(
        client,
        team,
        _export_graph("csv", source="table", rows=json.dumps(ROWS, ensure_ascii=False)),
    )
    token = deploy(client, team, app_id)
    r = client.post(f"/api/v1/public/apps/{token}/runs", json={"input": {"name": "폼"}})
    assert r.status_code == 202, r.text
    rid = r.json()["run_id"]
    res = client.get(f"/api/v1/public/apps/{token}/runs/{rid}").json()
    assert res["status"] == "succeeded" and res["files"][0]["filename"] == "폼-보고서.csv"
    got = client.get(_public_url(token, res["files"][0]))
    assert got.status_code == 200 and got.content.startswith(b"\xef\xbb\xbf")


# ---------------- 일괄 실행 결과 ----------------
def _wait_batch(
    client: TestClient, url: str, headers: dict[str, str] | None = None
) -> dict[str, Any]:
    for _ in range(40):
        st: dict[str, Any] = client.get(url, headers=headers or {}).json()
        if st.get("done"):
            return st
        time.sleep(0.1)
    raise AssertionError("일괄 실행이 끝나지 않았어요")


def test_batch_results_include_files_column(client: TestClient, team: Team) -> None:
    app_id = _file_app(client, team, _export_graph("md", text="안녕 {{n1.name}}"))
    h = team.h("builder")
    rows = [{"row": 1, "values": {"name": "가"}}, {"row": 2, "values": {"name": "나"}}]
    b = client.post(f"/api/v1/apps/{app_id}/batches", json={"rows": rows}, headers=h)
    assert b.status_code == 201, b.text
    base = f"/api/v1/apps/{app_id}/batches/{b.json()['batch_id']}"
    st = _wait_batch(client, base, h)
    assert [r["status"] for r in st["rows"]] == ["succeeded", "succeeded"]
    first = st["rows"][0]["files"][0]
    assert first["filename"] == "가-보고서.md" and first["url"].endswith(
        f"/runs/{st['rows'][0]['run_id']}"
    )
    csv_text = client.get(f"{base}/results.csv", headers=h).content.decode("utf-8-sig")
    header = csv_text.splitlines()[0].split(",")
    assert "파일" in header and "가-보고서.md" in csv_text and "나-보고서.md" in csv_text


def test_batch_without_files_keeps_old_csv(client: TestClient, team: Team) -> None:
    graph = _wf(
        [{"id": "out", "type": "output", "data": {"template": "안녕 {{n1.name}}"}}],
        [("n1", "out")],
        ["name"],
    )
    app_id = _file_app(client, team, graph, name="파일 없음")
    h = team.h("builder")
    b = client.post(
        f"/api/v1/apps/{app_id}/batches",
        json={"rows": [{"row": 1, "values": {"name": "가"}}]},
        headers=h,
    ).json()
    base = f"/api/v1/apps/{app_id}/batches/{b['batch_id']}"
    _wait_batch(client, base, h)
    header = (
        client.get(f"{base}/results.csv", headers=h).content.decode("utf-8-sig").splitlines()[0]
    )
    assert "파일" not in header.split(",")


def test_public_batch_files_use_signed_links(client: TestClient, team: Team) -> None:
    app_id = _file_app(client, team, _export_graph("txt", text="공개 {{n1.name}}"))
    token = deploy(client, team, app_id)
    b = client.post(
        f"/api/v1/public/apps/{token}/batches",
        json={"rows": [{"row": 1, "values": {"name": "다"}}]},
    )
    assert b.status_code == 200 or b.status_code == 201, b.text
    base = f"/api/v1/public/apps/{token}/batches/{b.json()['batch_id']}"
    st = _wait_batch(client, base)
    assert "run_id" not in st["rows"][0]
    link = st["rows"][0]["files"][0]["url"]
    assert "/api/v1/public/apps/" in link and "sig=" in link and "exp=" in link
    path = link[link.index("/api/v1/") :]
    assert client.get(path).content == "공개 다".encode()
    assert "다-보고서.txt" in client.get(f"{base}/results.csv").content.decode("utf-8-sig")


# ---------------- 단계 등록·미리 보기 ----------------
def test_new_nodes_are_registered_and_listed(client: TestClient, team: Team) -> None:
    from nodes import registry

    specs = {t: registry.get(t) for t in ("image_generate", "file_export")}
    img, exp = specs["image_generate"], specs["file_export"]
    assert img is not None and img.label and img.outputs is not None
    assert exp is not None and exp.label and exp.outputs is not None
    assert img.outputs({}) == ["files", "first_file_id", "count", "revised_prompt"]
    assert exp.outputs({}) == ["file", "file_id", "filename"]
    listed = client.get(f"/api/v1/workspaces/{team.ws}/node-types", headers=team.h("builder"))
    if listed.status_code == 200:
        types = {n["type"] for n in listed.json()}
        assert {"image_generate", "file_export"} <= types


def test_presets_mark_image_capable_providers(client: TestClient, team: Team) -> None:
    r = client.get("/api/v1/llm/providers", headers=team.h("builder"))
    assert r.status_code == 200
    by_key = {p["key"]: p for p in r.json()}
    assert (
        by_key["openai"]["image"] is True and by_key["openai"]["image_models"][0] == "gpt-image-1"
    )
    assert by_key["anthropic"]["image"] is False
    assert by_key["azure"]["image"] is True and by_key["azure"]["image_models"] == []
