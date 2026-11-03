"""v0.5 지식베이스: DOCX·PPTX·XLSX·HTML 올리기, 문서 켜기·끄기, KB별 임베딩 모델 고정."""

import io

import pytest
from fastapi.testclient import TestClient

from api.llm.base import LlmError
from api.services import knowledge as svc
from api.tests.conftest import Team, add_llm
from api.tests.fakes import FakeAdapter


def _docx() -> bytes:
    import docx

    d = docx.Document()
    d.add_paragraph("연차는 입사 1년 뒤 15일이 생겨요.")
    t = d.add_table(rows=1, cols=2)
    t.rows[0].cells[0].text = "복지"
    t.rows[0].cells[1].text = "건강검진 연 1회"
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def _pptx() -> bytes:
    from pptx import Presentation
    from pptx.util import Inches

    prs = Presentation()
    s = prs.slides.add_slide(prs.slide_layouts[5])
    s.shapes.title.text = "보안 교육"
    s.shapes.add_textbox(
        Inches(1), Inches(2), Inches(5), Inches(1)
    ).text_frame.text = "비밀번호는 90일마다 바꿔요."
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


def _xlsx() -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "연락처"
    ws.append(["부서", "담당", "내선"])
    ws.append(["인사팀", "김인사", 1234])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


FILES = [
    ("규정.docx", _docx, svc.DOCX_MIME, ["15일", "건강검진 연 1회"]),
    ("교육.pptx", _pptx, svc.PPTX_MIME, ["[슬라이드 1]", "90일"]),
    ("연락처.xlsx", _xlsx, svc.XLSX_MIME, ["[시트 연락처]", "인사팀 | 김인사 | 1234"]),
    (
        "안내.html",
        lambda: (
            "<html><head><title>사내 안내</title></head><body><p>주차는 B2층</p><script>x()</script></body></html>".encode()
        ),
        "text/html",
        ["사내 안내", "B2층"],
    ),
]


@pytest.mark.parametrize(("name", "make", "mime", "expect"), FILES)
def test_extract_formats(name: str, make: object, mime: str, expect: list[str]) -> None:
    text = svc.extract_text(make(), name, mime)  # type: ignore[operator]
    for e in expect:
        assert e in text, (name, text)
    assert "x()" not in text


def test_broken_office_file_two_line_error() -> None:
    with pytest.raises(ValueError, match="DOCX"):
        svc.extract_text(b"not a zip", "x.docx", svc.DOCX_MIME)


def test_upload_formats_toggle_and_embedding_model(
    client: TestClient, team: Team, fake_llm: FakeAdapter
) -> None:
    add_llm(client, team, provider="openai", model="gpt-4o-mini")
    models = client.get("/api/v1/llm/embedding-models", headers=team.h("member")).json()
    assert "text-embedding-3-small" in {m["model"] for m in models}
    bad = client.post(
        f"/api/v1/workspaces/{team.ws}/knowledge-bases",
        json={"name": "x", "embedding_model": "drop table;"},
        headers=team.h("builder"),
    )
    assert bad.status_code == 422
    kb = client.post(
        f"/api/v1/workspaces/{team.ws}/knowledge-bases",
        json={"name": "사내 규정", "embedding_model": "text-embedding-3-large"},
        headers=team.h("builder"),
    ).json()
    assert kb["embedding_model"] == "text-embedding-3-large"
    docs = {}
    for name, make, mime, _ in FILES:
        res = client.post(
            f"/api/v1/knowledge-bases/{kb['id']}/documents",
            files={"file": (name, make(), mime)},
            headers=team.h("builder"),
        )
        assert res.status_code == 200, res.text
        d = res.json()
        assert d["status"] == "ready" and d["enabled"] is True, d
        docs[name] = d
    # 문서를 만들 때·검색할 때 모두 KB의 모델을 쓴다
    embeds = [c for c in fake_llm.calls if c["kind"] == "embed"]
    assert embeds and all(c["model"] == "text-embedding-3-large" for c in embeds)

    def files_found(q: str) -> set[str]:
        hits = client.post(
            f"/api/v1/knowledge-bases/{kb['id']}/search",
            json={"query": q, "method": "keyword", "top_k": 10},
            headers=team.h("builder"),
        ).json()
        return {h["filename"] for h in hits}

    assert "규정.docx" in files_found("연차 15일")
    off = client.patch(
        f"/api/v1/documents/{docs['규정.docx']['id']}",
        json={"enabled": False},
        headers=team.h("builder"),
    )
    assert off.status_code == 200 and off.json()["enabled"] is False
    assert "규정.docx" not in files_found("연차 15일")
    # 메타데이터만 고쳐도 켜기 상태는 그대로
    client.patch(
        f"/api/v1/documents/{docs['규정.docx']['id']}",
        json={"metadata": {"부서": "인사"}},
        headers=team.h("builder"),
    )
    again = client.get(
        f"/api/v1/knowledge-bases/{kb['id']}/documents", headers=team.h("builder")
    ).json()
    row = next(d for d in again if d["filename"] == "규정.docx")
    assert row["enabled"] is False and row["metadata"] == {"부서": "인사"}
    assert (
        client.patch(
            f"/api/v1/documents/{docs['규정.docx']['id']}",
            json={"enabled": True},
            headers=team.h("operator"),
        ).status_code
        == 403
    )


def test_embedding_vectors_fit_storage() -> None:
    assert svc._fit([1.0, 2.0], 4) == [1.0, 2.0, 0.0, 0.0]
    with pytest.raises(LlmError):
        svc._fit([0.0] * 5, 4)


def test_unsupported_upload_message(client: TestClient, team: Team) -> None:
    kb = client.post(
        f"/api/v1/workspaces/{team.ws}/knowledge-bases",
        json={"name": "k"},
        headers=team.h("builder"),
    ).json()
    res = client.post(
        f"/api/v1/knowledge-bases/{kb['id']}/documents",
        files={"file": ("a.exe", b"MZ", "application/octet-stream")},
        headers=team.h("builder"),
    )
    assert res.status_code == 415 and "DOCX" in res.json()["detail"]["message"]
