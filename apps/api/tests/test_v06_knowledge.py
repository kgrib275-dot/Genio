"""v0.6 지식베이스: 질문·답 형식(표 가져오기·AI로 만들기)과 문서 처리 순서(파이프라인)·미리 보기."""

import io
import json
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from api.db import SessionLocal
from api.models import Chunk, Document
from api.services import kb_pipeline as pipe
from api.tests.conftest import ROLES, Team, add_llm
from api.tests.fakes import FakeAdapter
from nodes import LlmResult

CSV = "번호,질문,답\n1,연차는 며칠인가요?,입사 1년 뒤 15일이에요.\n2,재택근무 되나요?,주 2회까지 돼요.\n3,,빈 질문\n".encode()


def _xlsx(rows: list[list[str]]) -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    assert ws is not None
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _kb(client: TestClient, team: Team, name: str = "규정") -> dict[str, Any]:
    out: dict[str, Any] = client.post(
        f"/api/v1/workspaces/{team.ws}/knowledge-bases",
        json={"name": name},
        headers=team.h("builder"),
    ).json()
    return out


# ---------------- 질문·답 표 ----------------
def test_qa_columns_and_csv_import_search(
    client: TestClient, team: Team, fake_llm: FakeAdapter
) -> None:
    add_llm(client, team, provider="openai", model="gpt-4o-mini")
    kb = _kb(client, team)
    cols = client.post(
        f"/api/v1/knowledge-bases/{kb['id']}/qa/columns",
        files={"file": ("faq.csv", CSV, "text/csv")},
        headers=team.h("builder"),
    )
    assert cols.status_code == 200, cols.text
    c = cols.json()
    assert c["columns"] == ["번호", "질문", "답"]
    assert c["question_column"] == "질문" and c["answer_column"] == "답"
    assert c["row_count"] == 3
    res = client.post(
        f"/api/v1/knowledge-bases/{kb['id']}/documents/qa",
        files={"file": ("faq.csv", CSV, "text/csv")},
        data={"question_column": "질문", "answer_column": "답"},
        headers=team.h("builder"),
    )
    assert res.status_code == 200, res.text
    doc = res.json()
    assert doc["status"] == "ready" and doc["chunk_count"] == 2  # 빈 질문 줄은 뺀다
    # 임베딩은 질문으로만 만든다
    embeds = [x for x in fake_llm.calls if x["kind"] == "embed"]
    assert any("연차는 며칠인가요?" in t for x in embeds for t in x["texts"])
    assert not any("15일이에요" in t for x in embeds for t in x["texts"])
    hits = client.post(
        f"/api/v1/knowledge-bases/{kb['id']}/search",
        json={"query": "연차 며칠", "method": "keyword", "top_k": 1},
        headers=team.h("builder"),
    ).json()
    assert hits[0]["question"] == "연차는 며칠인가요?"
    assert hits[0]["answer"] == "입사 1년 뒤 15일이에요."
    assert "입사 1년 뒤 15일" in hits[0]["content"]  # context로 쓰는 글에 답이 들어 있다


def test_qa_xlsx_import_with_mapping(client: TestClient, team: Team, fake_llm: FakeAdapter) -> None:
    add_llm(client, team, provider="openai", model="gpt-4o-mini")
    kb = _kb(client, team)
    data = _xlsx([["Q", "A", "비고"], ["주차 되나요?", "지하 2층에 돼요.", ""]])
    mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    res = client.post(
        f"/api/v1/knowledge-bases/{kb['id']}/documents/qa",
        files={"file": ("faq.xlsx", data, mime)},
        data={"question_column": "Q", "answer_column": "A"},
        headers=team.h("builder"),
    )
    assert res.status_code == 200, res.text
    assert res.json()["chunk_count"] == 1
    with SessionLocal() as db:
        ch = db.scalars(select(Chunk)).one()
        assert ch.content == "주차 되나요?"
        assert ch.metadata_["qa"] is True and ch.metadata_["answer"] == "지하 2층에 돼요."


def test_qa_import_errors(client: TestClient, team: Team) -> None:
    kb = _kb(client, team)
    bad = client.post(
        f"/api/v1/knowledge-bases/{kb['id']}/documents/qa",
        files={"file": ("faq.txt", b"x", "text/plain")},
        headers=team.h("builder"),
    )
    assert bad.status_code == 415 and bad.json()["detail"]["hint"]
    nocol = client.post(
        f"/api/v1/knowledge-bases/{kb['id']}/documents/qa",
        files={"file": ("faq.csv", "가,나\n1,2\n".encode(), "text/csv")},
        headers=team.h("builder"),
    )
    assert nocol.status_code == 422
    assert "열" in nocol.json()["detail"]["message"] and nocol.json()["detail"]["hint"]


# ---------------- AI로 질문·답 만들기 ----------------
def _qa_adapter(fake: FakeAdapter, monkeypatch: pytest.MonkeyPatch) -> None:
    def complete(**kw: Any) -> LlmResult:
        fake.calls.append({"kind": "complete", "prompt": kw["prompt"]})
        data = {
            "pairs": [
                {"question": "출장비는 얼마인가요?", "answer": "하루 5만 원이에요."},
                {"question": "출장 보고는 언제?", "answer": "다녀온 뒤 3일 안에요."},
            ]
        }
        return LlmResult(
            text=json.dumps(data, ensure_ascii=False),
            data=data,
            model=kw["model"],
            input_tokens=10,
            output_tokens=5,
        )

    monkeypatch.setattr(fake, "complete", complete)


def test_generated_qa_from_document(
    client: TestClient, team: Team, fake_llm: FakeAdapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    add_llm(client, team, provider="openai", model="gpt-4o-mini")
    _qa_adapter(fake_llm, monkeypatch)
    kb = _kb(client, team)
    r = client.patch(
        f"/api/v1/knowledge-bases/{kb['id']}",
        json={"settings": {"chunk_mode": "qa", "qa_pairs_per_chunk": 2}},
        headers=team.h("builder"),
    )
    assert r.status_code == 200 and r.json()["settings"]["chunk_mode"] == "qa"
    res = client.post(
        f"/api/v1/knowledge-bases/{kb['id']}/documents",
        files={"file": ("출장.txt", "출장비는 하루 5만 원. 보고는 3일 안.".encode(), "text/plain")},
        headers=team.h("builder"),
    )
    d = res.json()
    assert d["status"] == "ready", d
    assert d["chunk_count"] == 2
    prompts = [c["prompt"] for c in fake_llm.calls if c["kind"] == "complete"]
    assert prompts and "2쌍" in prompts[0] and "<<<자료 시작>>>" in prompts[0]


def test_generated_qa_without_ai_key_two_line_error(
    client: TestClient, team: Team, fake_llm: FakeAdapter
) -> None:
    del fake_llm
    kb = _kb(client, team)
    client.patch(
        f"/api/v1/knowledge-bases/{kb['id']}",
        json={"settings": {"chunk_mode": "qa"}},
        headers=team.h("builder"),
    )
    res = client.post(
        f"/api/v1/knowledge-bases/{kb['id']}/preview",
        files={"file": ("a.txt", "본문 글".encode(), "text/plain")},
        headers=team.h("builder"),
    )
    assert res.status_code == 422
    detail = res.json()["detail"]
    assert detail["message"] and detail["hint"]


# ---------------- 처리 순서 단계 ----------------
def test_normalize_pipeline_order_and_validation() -> None:
    p = pipe.normalize_pipeline(
        [
            {"type": "store", "enabled": False},
            {"type": "clean", "enabled": True, "mask_urls": True, "evil": 1},
            {"type": "nope"},
        ]
    )
    assert [s["type"] for s in p] == list(pipe.STEP_ORDER)
    assert p[-1]["enabled"] is True  # 저장은 끌 수 없다
    clean = pipe.step_of(p, "clean")
    assert clean["enabled"] and clean["mask_urls"] and "evil" not in clean
    with pytest.raises(pipe.PipelineError):
        pipe.normalize_pipeline([{"type": "clean", "remove_patterns": ["(("]}])
    with pytest.raises(pipe.PipelineError):
        pipe.normalize_pipeline([{"type": "metadata", "filename_pattern": "[x"}])


def test_clean_step() -> None:
    page = "회사 머리글\n본문 {n}  내용 https://a.example/x 메일 kim@corp.kr\n쪽 번호 끝\n"
    text = "".join(page.replace("{n}", str(i)) for i in range(3))
    out = pipe.clean_text(
        text,
        {
            "collapse_spaces": True,
            "mask_urls": True,
            "mask_emails": True,
            "remove_repeated_lines": True,
            "remove_patterns": [r"본문 \d"],
        },
    )
    assert "회사 머리글" not in out and "쪽 번호 끝" not in out
    assert "[주소]" in out and "[이메일]" in out
    assert "본문 1" not in out and "  " not in out


def test_metadata_step() -> None:
    meta = pipe.pipeline_metadata(
        "인사_2026_규정.pdf",
        {"fixed": {"출처": "사내"}, "filename_pattern": r"(?P<부서>[^_]+)_(?P<연도>\d{4})"},
    )
    assert meta == {"출처": "사내", "부서": "인사", "연도": "2026"}


def test_pipeline_applied_on_processing(
    client: TestClient, team: Team, fake_llm: FakeAdapter
) -> None:
    add_llm(client, team, provider="openai", model="gpt-4o-mini")
    kb = _kb(client, team)
    pipeline = [
        {"type": "clean", "enabled": True, "mask_emails": True},
        {"type": "metadata", "enabled": True, "fixed": {"출처": "사내"}},
    ]
    r = client.patch(
        f"/api/v1/knowledge-bases/{kb['id']}",
        json={"settings": {"pipeline": pipeline}},
        headers=team.h("builder"),
    )
    assert r.status_code == 200
    saved = r.json()["settings"]["pipeline"]
    assert pipe.step_of(saved, "clean")["enabled"] is True
    bad = client.patch(
        f"/api/v1/knowledge-bases/{kb['id']}",
        json={"settings": {"pipeline": [{"type": "clean", "remove_patterns": ["(("]}]}},
        headers=team.h("builder"),
    )
    assert bad.status_code == 422 and bad.json()["detail"]["hint"]
    doc = client.post(
        f"/api/v1/knowledge-bases/{kb['id']}/documents",
        files={"file": ("a.txt", "문의는 kim@corp.kr 로 주세요.".encode(), "text/plain")},
        headers=team.h("builder"),
    ).json()
    assert doc["status"] == "ready" and doc["metadata"] == {"출처": "사내"}
    chunks = client.get(f"/api/v1/documents/{doc['id']}/chunks", headers=team.h("builder")).json()
    assert "[이메일]" in chunks[0]["content"] and "kim@corp.kr" not in chunks[0]["content"]
    # 전체 다시 나누기
    rp = client.post(f"/api/v1/knowledge-bases/{kb['id']}/reprocess", headers=team.h("builder"))
    assert rp.status_code == 200 and rp.json() == {"queued": 1}


def test_preview_does_not_persist(client: TestClient, team: Team, fake_llm: FakeAdapter) -> None:
    add_llm(client, team, provider="openai", model="gpt-4o-mini")
    kb = _kb(client, team)
    text = "\n\n".join(f"문단 {i} " + "가나다라 " * 30 for i in range(6))
    settings = json.dumps(
        {
            "chunk_size": 200,
            "chunk_overlap": 0,
            "pipeline": [{"type": "metadata", "enabled": True, "fixed": {"팀": "운영"}}],
        }
    )
    res = client.post(
        f"/api/v1/knowledge-bases/{kb['id']}/preview",
        files={"file": ("a.txt", text.encode(), "text/plain")},
        data={"settings": settings},
        headers=team.h("builder"),
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["total"] >= 3 and body["chunks"][0]["content"].startswith("문단 0")
    assert body["metadata"] == {"팀": "운영"} and body["log"]
    calls_before = len([c for c in fake_llm.calls if c["kind"] == "embed"])
    assert calls_before == 0  # 미리 보기는 임베딩도 하지 않는다
    with SessionLocal() as db:
        assert db.scalar(select(func.count(Document.id))) == 0
        assert db.scalar(select(func.count(Chunk.id))) == 0
    # 설정도 저장되지 않는다
    kb2 = client.get(f"/api/v1/workspaces/{team.ws}/knowledge-bases", headers=team.h("builder"))
    assert kb2.json()[0]["settings"]["chunk_size"] == 800
    # 이미 있는 문서로 미리 보기, 질문·답 표도 미리 볼 수 있다
    doc = client.post(
        f"/api/v1/knowledge-bases/{kb['id']}/documents/qa",
        files={"file": ("faq.csv", CSV, "text/csv")},
        headers=team.h("builder"),
    ).json()
    pv = client.post(
        f"/api/v1/knowledge-bases/{kb['id']}/preview",
        data={"document_id": doc["id"]},
        headers=team.h("builder"),
    ).json()
    assert pv["total"] == 2 and pv["chunks"][0]["question"] == "연차는 며칠인가요?"
    with SessionLocal() as db:
        assert db.scalar(select(func.count(Chunk.id))) == 2
    none = client.post(f"/api/v1/knowledge-bases/{kb['id']}/preview", headers=team.h("builder"))
    assert none.status_code == 422


@pytest.mark.parametrize("role", ROLES)
def test_v06_kb_permissions(client: TestClient, team: Team, role: str) -> None:
    kb = _kb(client, team)
    allowed = role in ("owner", "admin", "builder")
    h = team.h(role)
    calls = [
        client.post(
            f"/api/v1/knowledge-bases/{kb['id']}/qa/columns",
            files={"file": ("faq.csv", CSV, "text/csv")},
            headers=h,
        ),
        client.post(
            f"/api/v1/knowledge-bases/{kb['id']}/preview",
            files={"file": ("faq.csv", CSV, "text/csv")},
            headers=h,
        ),
        client.post(f"/api/v1/knowledge-bases/{kb['id']}/reprocess", headers=h),
    ]
    for res in calls:
        assert (res.status_code == 200) == allowed, (role, res.status_code, res.text)
        if not allowed:
            assert res.status_code == 403
