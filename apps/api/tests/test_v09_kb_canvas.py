"""v0.9 지식 처리 캔버스(번역·요약 붙이기·이미지 설명 단계, 처리 순서 모음)와 이미지 포함 문서 색인·검색."""

import io
import json
import time
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from api.db import SessionLocal
from api.models import Chunk, Document, StoredFile
from api.services import kb_images as ki
from api.services import kb_pipeline as pipe
from api.services import storage
from api.tests.conftest import ROLES, Team, add_llm
from api.tests.fakes import FakeAdapter
from api.tests.test_v02_features import chat, deploy, faq_app

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


# ---------------- 시험용 그림·문서 만들기 ----------------
def png(color: tuple[int, int, int], size: tuple[int, int] = (240, 180), seed: int = 0) -> bytes:
    """색과 무늬(seed)가 다른 PNG. 같은 색·같은 seed면 같은 바이트(중복 시험용)."""
    from PIL import Image, ImageDraw

    im = Image.new("RGB", size, color)
    d = ImageDraw.Draw(im)
    for i in range(seed + 1):
        d.rectangle((i * 3, i * 2, i * 3 + 20, i * 2 + 12), fill=(255 - color[0], 40, i * 7 % 255))
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def docx_with(images: list[bytes], text: str = "문서 본문입니다.") -> bytes:
    import docx

    d = docx.Document()
    d.add_paragraph(text)
    for im in images:
        d.add_picture(io.BytesIO(im))
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def with_junk_media(docx_bytes: bytes) -> bytes:
    """DOCX 안에 그림이 아닌 파일(.png 이름)을 끼워 넣는다(깨진 그림 시험)."""
    import zipfile

    src = zipfile.ZipFile(io.BytesIO(docx_bytes))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for item in src.infolist():
            z.writestr(item, src.read(item.filename))
        z.writestr("word/media/junk.png", b"not-an-image")
    return out.getvalue()


def pptx_with(slides: list[list[bytes]]) -> bytes:
    from pptx import Presentation
    from pptx.util import Inches

    prs = Presentation()
    for imgs in slides:
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        for n, im in enumerate(imgs):
            slide.shapes.add_picture(io.BytesIO(im), Inches(1 + n), Inches(1), width=Inches(2))
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


def xlsx_with(images: list[bytes]) -> bytes:
    from openpyxl import Workbook
    from openpyxl.drawing.image import Image as XLImage

    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws["A1"] = "표 머리"
    for n, im in enumerate(images):
        ws.add_image(XLImage(io.BytesIO(im)), f"B{2 + n * 12}")
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def pdf_with(images: list[bytes]) -> bytes:
    from PIL import Image

    pages = [Image.open(io.BytesIO(b)).convert("RGB") for b in images]
    buf = io.BytesIO()
    pages[0].save(buf, format="PDF", save_all=True, append_images=pages[1:])
    return buf.getvalue()


A, B, C = png((200, 30, 30), seed=1), png((30, 200, 30), seed=2), png((30, 30, 200), seed=3)


# ---------------- 그림 뽑기 ----------------
def test_extract_docx_dedupes_and_filters() -> None:
    small = png((9, 9, 9), size=(40, 40))
    data = with_junk_media(docx_with([A, B, small]))
    rep = ki.extract_images(data, "a.docx", DOCX)
    assert [i.mime for i in rep.images] == ["image/png", "image/png"]
    assert rep.too_small == 1 and rep.unsupported == 1
    assert len({i.sha for i in rep.images}) == 2
    assert all(i.width >= 100 and i.height >= 100 for i in rep.images)
    # 같은 그림이 두 번 들어 있으면 한 번만 센다(엑셀은 같은 그림도 따로 저장한다)
    dup = ki.extract_images(xlsx_with([A, A, B]), "d.xlsx", XLSX)
    assert len(dup.images) == 2 and dup.duplicates == 1


def test_extract_pptx_pages_xlsx_png_pdf() -> None:
    rep = ki.extract_images(pptx_with([[A], [B, C]]), "d.pptx", PPTX)
    assert [i.page for i in rep.images] == [1, 2, 2]
    assert len(ki.extract_images(xlsx_with([A, B]), "t.xlsx", XLSX).images) == 2
    single = ki.extract_images(A, "photo.png", "image/png")
    assert len(single.images) == 1 and single.images[0].page is None
    pdf = ki.extract_images(pdf_with([A, B]), "x.pdf", "application/pdf")
    assert [i.page for i in pdf.images] == [1, 2]


def test_extract_caps_at_twenty_and_reports() -> None:
    many = [png((i * 9 % 256, 80, 120), seed=i) for i in range(25)]
    rep = ki.extract_images(docx_with(many), "m.docx", DOCX)
    assert len(rep.images) == 20 and rep.truncated == 5
    one = ki.extract_images(docx_with(many), "m.docx", DOCX, max_images=3)
    assert len(one.images) == 3


def test_extract_broken_documents_are_empty_not_errors() -> None:
    assert ki.extract_images(b"broken", "x.docx", DOCX).images == []
    assert ki.extract_images(b"broken", "x.pdf", "application/pdf").images == []
    assert ki.extract_images(b"hi", "x.txt", "text/plain").images == []


# ---------------- 처리 순서 형식 ----------------
def test_pipeline_has_new_stages_in_order_and_old_settings_still_load() -> None:
    p = pipe.normalize_pipeline(None)
    assert [s["type"] for s in p] == [
        "extract",
        "clean",
        "split",
        "translate",
        "summarize",
        "metadata",
        "image",
        "store",
    ]
    assert not any(s["enabled"] for s in p if s["type"] in ("translate", "summarize", "image"))
    # v0.6 저장 형식(5단계)도 읽힌다
    old = pipe.normalize_pipeline(
        [{"type": "clean", "enabled": True, "mask_urls": True}, {"type": "store", "enabled": False}]
    )
    assert len(old) == 8 and old[1]["mask_urls"] is True and old[-1]["enabled"] is True
    odd = pipe.normalize_pipeline(
        [
            {"type": "image", "enabled": True, "max_images": 99, "min_size": 5},
            {"type": "translate", "enabled": True, "target_language": "  "},
        ]
    )
    img = next(s for s in odd if s["type"] == "image")
    assert img["max_images"] == 20 and img["min_size"] == 50
    assert next(s for s in odd if s["type"] == "translate")["target_language"] == "영어"


def test_templates_are_valid_and_listed(client: TestClient, team: Team) -> None:
    assert client.get("/api/v1/knowledge-pipeline-templates").status_code == 401
    for role in ROLES:
        r = client.get("/api/v1/knowledge-pipeline-templates", headers=team.h(role))
        assert r.status_code == 200
    t = r.json()
    assert [x["id"] for x in t] == ["general", "rules", "faq", "minutes"]
    assert [x["name"] for x in t] == [
        "일반 문서",
        "규정집(머리글·바닥글 제거)",
        "FAQ 표",
        "회의록(날짜 꼬리표 추출)",
    ]
    kb = _kb(client, team)
    for tpl in t:
        assert len(tpl["settings"]["pipeline"]) == 8
        res = client.patch(
            f"/api/v1/knowledge-bases/{kb['id']}",
            json={"settings": tpl["settings"]},
            headers=team.h("builder"),
        )
        assert res.status_code == 200, (tpl["id"], res.text)
    minutes = next(x for x in t if x["id"] == "minutes")
    meta = next(s for s in minutes["settings"]["pipeline"] if s["type"] == "metadata")
    assert pipe.pipeline_metadata("2026-11-05_주간회의.docx", meta)["날짜"] == "2026-11-05"


# ---------------- 공통 도우미 ----------------
def _kb(client: TestClient, team: Team, name: str = "그림 지식") -> dict[str, Any]:
    out: dict[str, Any] = client.post(
        f"/api/v1/workspaces/{team.ws}/knowledge-bases",
        json={"name": name},
        headers=team.h("builder"),
    ).json()
    return out


def _set_pipeline(client: TestClient, team: Team, kb_id: str, **steps: dict[str, Any]) -> None:
    pipeline = [{"type": t, **cfg} for t, cfg in steps.items()]
    r = client.patch(
        f"/api/v1/knowledge-bases/{kb_id}",
        json={"settings": {"pipeline": pipeline}},
        headers=team.h("builder"),
    )
    assert r.status_code == 200, r.text


def _upload(
    client: TestClient, team: Team, kb_id: str, name: str, data: bytes, mime: str
) -> dict[str, Any]:
    r = client.post(
        f"/api/v1/knowledge-bases/{kb_id}/documents",
        files={"file": (name, data, mime)},
        headers=team.h("builder"),
    )
    assert r.status_code == 200, r.text
    out: dict[str, Any] = r.json()
    return out


def _preview(
    client: TestClient, team: Team, kb_id: str, name: str, data: bytes, mime: str, **steps: Any
) -> dict[str, Any]:
    pipeline = [{"type": t, **cfg} for t, cfg in steps.items()]
    r = client.post(
        f"/api/v1/knowledge-bases/{kb_id}/preview",
        files={"file": (name, data, mime)},
        data={"settings": json.dumps({"pipeline": pipeline})} if steps else {},
        headers=team.h("builder"),
    )
    assert r.status_code == 200, r.text
    out: dict[str, Any] = r.json()
    return out


LONG_TEXT = "\n\n".join(
    f"{n}번째 문단입니다. 연차와 휴가 규정을 설명하는 긴 문장이 들어 있어요." * 6 for n in range(8)
)


def _llm_calls(fake: FakeAdapter, text: str = "") -> list[dict[str, Any]]:
    return [c for c in fake.calls if c["kind"] == "complete" and text in c["system"]]


# ---------------- 번역·요약 붙이기(AI 단계) ----------------
def test_translate_preview_is_bounded_and_side_effect_free(
    client: TestClient, team: Team, fake_llm: FakeAdapter
) -> None:
    add_llm(client, team, provider="openai", model="gpt-4o-mini")
    kb = _kb(client, team)
    _set_pipeline(client, team, kb["id"], split={})
    res = _preview(
        client,
        team,
        kb["id"],
        "규정.txt",
        LONG_TEXT.encode(),
        "text/plain",
        translate={"enabled": True, "target_language": "영어"},
    )
    st = res["stages"]["translate"]
    assert st["language"] == "영어" and st["calls"] <= 3 and st["calls_full"] >= st["calls"]
    assert st["estimated_cost_usd"] >= 0 and st["samples"]
    assert res["ai_calls"] == st["calls"]
    assert len(_llm_calls(fake_llm, "영어로")) == st["calls"]
    # 맨 앞 세 조각만 번역됐다(번역문은 가짜 AI가 만든 '요약: …'로 시작)
    assert res["chunks"][0]["content"].startswith("요약:")
    assert res["stages"]["split"]["chunks"] == res["total"]
    with SessionLocal() as db:  # 미리 보기는 아무것도 저장하지 않는다
        assert db.query(Chunk).count() == 0 and db.query(Document).count() == 0


def test_summarize_prepends_line_to_embedding_text(
    client: TestClient, team: Team, fake_llm: FakeAdapter
) -> None:
    add_llm(client, team, provider="openai", model="gpt-4o-mini")
    kb = _kb(client, team)
    _set_pipeline(client, team, kb["id"], summarize={"enabled": True})
    doc = _upload(client, team, kb["id"], "규정.txt", LONG_TEXT.encode(), "text/plain")
    assert doc["status"] == "ready" and doc["chunk_count"] >= 2
    with SessionLocal() as db:
        chunks = list(db.scalars(select(Chunk).order_by(Chunk.position)))
        assert all(c.content.startswith("요약:") for c in chunks)
        d = db.get(Document, doc["id"])
        assert d is not None and d.doc_metadata["_ai_usage"]["calls"] == len(chunks)
    # 임베딩에도 요약이 들어갔다
    embeds = [t for x in fake_llm.calls if x["kind"] == "embed" for t in x["texts"]]
    assert embeds and all(t.startswith("요약:") for t in embeds)
    # 화면의 꼬리표에는 내부 기록이 보이지 않는다
    assert not any(k.startswith("_") for k in doc["metadata"])


def test_llm_stages_skip_when_budget_exhausted_and_without_connection(
    client: TestClient, team: Team, fake_llm: FakeAdapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    add_llm(client, team, provider="openai", model="gpt-4o-mini")
    kb = _kb(client, team)
    _set_pipeline(client, team, kb["id"], translate={"enabled": True}, summarize={"enabled": True})
    monkeypatch.setattr(
        ki, "budget_block", lambda db, ws: "이번 달 AI 사용 한도를 다 썼어요.\n한도를 늘려 주세요."
    )
    doc = _upload(client, team, kb["id"], "규정.txt", LONG_TEXT.encode(), "text/plain")
    assert doc["status"] == "ready"  # 문서는 AI 단계 없이 처리된다
    assert not _llm_calls(fake_llm, "번역") and not _llm_calls(fake_llm, "요약")
    with SessionLocal() as db:
        assert not any(c.content.startswith("요약:") for c in db.scalars(select(Chunk)))
    pv = _preview(
        client,
        team,
        kb["id"],
        "a.txt",
        LONG_TEXT.encode(),
        "text/plain",
        translate={"enabled": True},
    )
    assert "한도" in pv["stages"]["translate"]["skipped"]


def test_qa_mode_ignores_translate_and_summarize(
    client: TestClient, team: Team, fake_llm: FakeAdapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    add_llm(client, team, provider="openai", model="gpt-4o-mini")
    monkeypatch.setattr(pipe, "generate_qa", lambda db, ws, chunks, per: ([("질문?", "답")], []))
    kb = _kb(client, team)
    r = client.patch(
        f"/api/v1/knowledge-bases/{kb['id']}",
        json={
            "settings": {
                "chunk_mode": "qa",
                "pipeline": [{"type": "translate", "enabled": True}],
            }
        },
        headers=team.h("builder"),
    )
    assert r.status_code == 200
    pv = _preview(client, team, kb["id"], "a.txt", LONG_TEXT.encode(), "text/plain")
    assert any("건너뛰어요" in line for line in pv["log"])
    assert not _llm_calls(fake_llm, "영어로")


# ---------------- 이미지 설명(멀티모달 색인) ----------------
def test_image_preview_bounded_with_thumbnails_and_no_writes(
    client: TestClient, team: Team, fake_llm: FakeAdapter
) -> None:
    add_llm(client, team, provider="openai", model="gpt-4o-mini")
    kb = _kb(client, team)
    data = docx_with([A, B, C, png((90, 90, 30), seed=9)])
    pv = _preview(client, team, kb["id"], "보고.docx", data, DOCX, image={"enabled": True})
    st = pv["stages"]["image"]
    assert st["images"] == 4 and st["described"] == 3 and st["calls"] == 3  # 미리 보기는 3장까지
    assert st["calls_full"] == 4 and st["cut"] == 1
    assert st["estimated_cost_usd"] > 0 and st["model"] == "gpt-4o-mini"
    imgs = [c for c in pv["chunks"] if c["kind"] == "image"]
    assert len(imgs) == 3 and all(c["thumb"].startswith("data:image/png;base64,") for c in imgs)
    assert imgs[0]["content"].startswith("[그림] 이미지 1장을 봤어요")
    with SessionLocal() as db:
        assert db.query(StoredFile).count() == 0 and db.query(Chunk).count() == 0


def test_image_stage_off_by_default_does_nothing(
    client: TestClient, team: Team, fake_llm: FakeAdapter
) -> None:
    add_llm(client, team, provider="openai", model="gpt-4o-mini")
    kb = _kb(client, team)
    doc = _upload(client, team, kb["id"], "보고.docx", docx_with([A, B]), DOCX)
    assert doc["status"] == "ready" and doc["chunk_count"] == 1
    assert doc["image_report"] is None
    assert not [c for c in fake_llm.calls if c.get("images")]
    with SessionLocal() as db:
        assert db.query(StoredFile).count() == 0


def _index_images(
    client: TestClient, team: Team, *, text: str = "분기 매출 보고서입니다."
) -> tuple[dict[str, Any], dict[str, Any]]:
    kb = _kb(client, team)
    _set_pipeline(client, team, kb["id"], image={"enabled": True})
    doc = _upload(client, team, kb["id"], "보고.docx", docx_with([A, B], text), DOCX)
    return kb, doc


def test_image_chunks_are_stored_searchable_and_cleaned_up(
    client: TestClient, team: Team, fake_llm: FakeAdapter
) -> None:
    add_llm(client, team, provider="openai", model="gpt-4o-mini")
    kb, doc = _index_images(client, team)
    assert doc["status"] == "ready" and doc["chunk_count"] == 3  # 글 1 + 그림 2
    assert doc["image_report"] == {
        "found": 2,
        "images": 2,
        "described": 2,
        "failed": 0,
        "calls": 2,
        "truncated": 0,
        "skipped": None,
    }
    assert not any(k.startswith("_") for k in doc["metadata"])
    vision_calls = [c for c in fake_llm.calls if c.get("images")]
    assert len(vision_calls) == 2 and "2~3문장" in vision_calls[0]["prompt"]
    with SessionLocal() as db:
        files = list(db.scalars(select(StoredFile)))
        assert len(files) == 2
        assert all(f.filename.startswith(f"kbimg/{kb['id']}/{doc['id']}/") for f in files)
        chunks = list(db.scalars(select(Chunk).order_by(Chunk.position)))
        imgs = [c for c in chunks if (c.metadata_ or {}).get("kind") == "image"]
        assert len(imgs) == 2 and {c.metadata_["file_id"] for c in imgs} == {f.id for f in files}
        assert all(c.content.startswith("[그림] ") for c in imgs)
        old_ids = {f.id for f in files}
    # 설명 글로 검색된다 → 결과에 그림 참조가 붙는다
    hits = client.post(
        f"/api/v1/knowledge-bases/{kb['id']}/search",
        json={"query": "이미지 1장을 봤어요", "method": "keyword", "top_k": 5},
        headers=team.h("builder"),
    ).json()
    img_hits = [h for h in hits if h.get("kind") == "image"]
    assert img_hits and img_hits[0]["image"]["file_id"] in old_ids
    assert img_hits[0]["image"]["kb_id"] == kb["id"] and img_hits[0]["image"]["caption"]
    assert "page" in img_hits[0]["image"]
    # 조각 목록에도 그림 표시
    chunks_api = client.get(
        f"/api/v1/documents/{doc['id']}/chunks", headers=team.h("builder")
    ).json()
    assert sum(1 for c in chunks_api if c["kind"] == "image") == 2
    # 다시 나누면 그림 파일이 새로 만들어지고 예전 것은 지워진다(새지 않는다)
    r = client.post(f"/api/v1/documents/{doc['id']}/reprocess", headers=team.h("builder"))
    assert r.status_code == 200
    with SessionLocal() as db:
        now = {f.id for f in db.scalars(select(StoredFile))}
        assert len(now) == 2 and now.isdisjoint(old_ids)
    # 문서를 지우면 그림 파일도 사라진다
    assert (
        client.delete(f"/api/v1/documents/{doc['id']}", headers=team.h("builder")).status_code
        == 204
    )
    with SessionLocal() as db:
        assert db.query(StoredFile).count() == 0


def test_delete_kb_removes_image_files(
    client: TestClient, team: Team, fake_llm: FakeAdapter
) -> None:
    add_llm(client, team, provider="openai", model="gpt-4o-mini")
    kb, doc = _index_images(client, team)
    assert doc["status"] == "ready"
    with SessionLocal() as db:
        assert db.query(StoredFile).count() == 2
    assert (
        client.delete(f"/api/v1/knowledge-bases/{kb['id']}", headers=team.h("builder")).status_code
        == 204
    )
    with SessionLocal() as db:
        assert db.query(StoredFile).count() == 0


def test_image_stage_skips_without_vision_model_but_text_still_processes(
    client: TestClient, team: Team, fake_llm: FakeAdapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    add_llm(client, team, provider="openai", model="gpt-4o-mini")
    monkeypatch.setattr(ki, "model_supports_vision", lambda provider, model: False)
    kb, doc = _index_images(client, team)
    assert doc["status"] == "ready" and doc["chunk_count"] == 1  # 글 조각만
    assert doc["image_report"]["skipped"].startswith("그림을 읽을 수 있는 AI 모델이 없어요.")
    assert not [c for c in fake_llm.calls if c.get("images")]
    pv = _preview(client, team, kb["id"], "a.docx", docx_with([A]), DOCX, image={"enabled": True})
    assert "설정 > AI 연결" in pv["stages"]["image"]["skipped"]


def test_image_stage_skips_when_budget_exhausted(
    client: TestClient, team: Team, fake_llm: FakeAdapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    add_llm(client, team, provider="openai", model="gpt-4o-mini")
    monkeypatch.setattr(
        ki, "budget_block", lambda db, ws: "이번 달 AI 사용 한도를 다 썼어요.\n한도를 늘려 주세요."
    )
    _kb, doc = _index_images(client, team)
    assert doc["status"] == "ready" and doc["chunk_count"] == 1
    assert "한도" in doc["image_report"]["skipped"]
    assert not [c for c in fake_llm.calls if c.get("images")]


def test_failed_descriptions_are_reported_per_document(
    client: TestClient, team: Team, fake_llm: FakeAdapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    from api.llm.base import LlmError

    add_llm(client, team, provider="openai", model="gpt-4o-mini")
    real = fake_llm.complete
    seen = {"n": 0}

    def flaky(**kw: Any) -> Any:
        if kw.get("images"):
            seen["n"] += 1
            if seen["n"] == 2:
                raise LlmError("한도 초과예요.", "잠시 뒤 다시 해 보세요.")
        return real(**kw)

    monkeypatch.setattr(fake_llm, "complete", flaky)
    _kb, doc = _index_images(client, team)
    assert doc["status"] == "ready"
    assert doc["image_report"]["described"] == 1 and doc["image_report"]["failed"] == 1
    assert doc["chunk_count"] == 2


def test_standalone_image_file_needs_image_stage(
    client: TestClient, team: Team, fake_llm: FakeAdapter
) -> None:
    add_llm(client, team, provider="openai", model="gpt-4o-mini")
    kb = _kb(client, team)
    off = _upload(client, team, kb["id"], "도표.png", A, "image/png")
    assert off["status"] == "failed" and "이미지 설명" in off["error"]
    _set_pipeline(client, team, kb["id"], image={"enabled": True})
    r = client.post(f"/api/v1/documents/{off['id']}/reprocess", headers=team.h("builder"))
    assert r.json()["status"] == "ready" and r.json()["chunk_count"] == 1
    with SessionLocal() as db:
        assert db.query(StoredFile).count() == 1


# ---------------- 비용 어림(다시 나누기 전) ----------------
def test_image_estimate_endpoint_and_permissions(
    client: TestClient, team: Team, fake_llm: FakeAdapter
) -> None:
    add_llm(client, team, provider="openai", model="gpt-4o-mini")
    kb = _kb(client, team)
    _upload(client, team, kb["id"], "a.docx", docx_with([A, B]), DOCX)
    _upload(client, team, kb["id"], "b.docx", docx_with([B, C]), DOCX)  # B는 문서마다 따로 센다
    url = f"/api/v1/knowledge-bases/{kb['id']}/image-estimate"
    r = client.get(url, headers=team.h("builder"))
    assert r.status_code == 200, r.text
    est = r.json()
    assert est["documents"] == 2 and est["images"] == 4 and est["vision_calls"] == 4
    assert est["estimated_cost_usd"] > 0 and est["model_ok"] and est["enabled"] is False
    assert est["partial"] is False and est["model"] == "gpt-4o-mini"
    for role in ROLES:
        got = client.get(url, headers=team.h(role)).status_code
        assert (got == 200) == (role in ("owner", "admin", "builder")), role
    assert client.get(url).status_code == 401
    small = client.get(url + "?min_size=2000", headers=team.h("builder")).json()
    assert small["images"] == 0


# ---------------- 그림 보기·서명 주소 ----------------
def test_signature_helpers() -> None:
    now = 1_700_000_000.0
    path = ki.signed_path("tok", "file1", ttl=60, now=now)
    assert path.startswith("/api/v1/public/apps/tok/kb-images/file1?exp=")
    exp = int(path.split("exp=")[1].split("&")[0])
    sig = path.split("sig=")[1]
    assert ki.verify_signature("tok", "file1", exp, sig, now=now + 30)
    assert not ki.verify_signature("tok", "file1", exp, sig, now=now + 61)  # 만료
    assert not ki.verify_signature("tok", "file2", exp, sig, now=now)  # 다른 파일
    assert not ki.verify_signature("other", "file1", exp, sig, now=now)  # 다른 앱
    assert not ki.verify_signature("tok", "file1", exp + 5, sig, now=now)  # 만료 시각 조작
    assert not ki.verify_signature("tok", "file1", exp, sig[:-2] + "zz", now=now)
    cites = ki.with_image_urls([{"index": 1, "image": {"file_id": "file1"}}, {"index": 2}], "tok")
    assert cites[0]["image"]["url"].startswith("/api/v1/public/apps/tok/kb-images/file1?")
    assert "image" not in cites[1]
    assert ki.with_image_urls(cites, None)[0]["image"]["url"]  # 토큰 없으면 그대로(복사)


def _image_app(client: TestClient, team: Team) -> tuple[dict[str, Any], dict[str, Any], str, str]:
    add_llm(client, team, provider="openai", model="gpt-4o-mini")
    kb, doc = _index_images(client, team)
    app_id = faq_app(client, team, kb_id=kb["id"])
    client.patch(
        f"/api/v1/apps/{app_id}/features",
        json={"citations": {"enabled": True}},
        headers=team.h("builder"),
    )
    token = deploy(client, team, app_id)
    return kb, doc, app_id, token


def test_public_signed_link_flow(client: TestClient, team: Team, fake_llm: FakeAdapter) -> None:
    _kb, _doc, _app, token = _image_app(client, team)
    with SessionLocal() as db:
        fid = next(f.id for f in db.scalars(select(StoredFile)) if f.size)
        ws_file = db.get(StoredFile, fid)
        assert ws_file is not None
        expected = storage.read_content(ws_file)
    good = ki.signed_path(token, fid)
    r = client.get(good)
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert r.content == expected and r.headers["x-content-type-options"] == "nosniff"
    assert client.head(good).status_code == 200
    # 서명이 없거나 틀리거나 만료되면 로그인 없이는 못 연다
    base = f"/api/v1/public/apps/{token}/kb-images/{fid}"
    assert client.get(base).status_code == 403
    assert client.get(good[:-2] + "zz").status_code == 403
    expired = ki.signed_path(token, fid, ttl=-10)
    r403 = client.get(expired)
    assert r403.status_code == 403 and r403.json()["detail"]["hint"]
    # 다른 배포 토큰으로는 404
    assert client.get(ki.signed_path("nope" + token, fid)).status_code == 404
    # 지식베이스 그림이 아닌 파일은 서명이 맞아도 열 수 없다
    with SessionLocal() as db:
        plain = StoredFile(
            workspace_id=team.ws, filename="업로드.png", mime="image/png", size=3, content=b"abc"
        )
        db.add(plain)
        db.commit()
        plain_id = plain.id
    assert client.get(ki.signed_path(token, plain_id)).status_code == 404
    # 다른 워크스페이스의 그림은 같은 서명으로도 열 수 없다
    with SessionLocal() as db:
        from api.models import Organization, Workspace

        org = Organization(name="다른 회사", slug="other-org")
        db.add(org)
        db.flush()
        ws2 = Workspace(org_id=org.id, name="다른 곳", slug="other-ws2", settings={})
        db.add(ws2)
        db.flush()
        alien = StoredFile(
            workspace_id=ws2.id,
            filename="kbimg/x/y/0.png",
            mime="image/png",
            size=3,
            content=b"abc",
        )
        db.add(alien)
        db.commit()
        alien_id = alien.id
    assert client.get(ki.signed_path(token, alien_id)).status_code == 404


def test_members_only_deployment_does_not_get_signed_links(
    client: TestClient, team: Team, fake_llm: FakeAdapter
) -> None:
    _kb, _doc, app_id, token = _image_app(client, team)
    with SessionLocal() as db:
        fid = next(f.id for f in db.scalars(select(StoredFile)))
    dep = client.get(f"/api/v1/apps/{app_id}/deployments", headers=team.h("builder")).json()[0]
    r = client.patch(
        f"/api/v1/deployments/{dep['id']}",
        json={"access": "workspace"},
        headers=team.h("builder"),
    )
    assert r.status_code == 200, r.text
    # 접근 규칙이 바뀐 뒤에는 예전 서명도 로그인 없이는 못 연다
    assert client.get(ki.signed_path(token, fid)).status_code == 403
    # 로그인한 멤버는 서명 없이도 배포 접근 규칙으로 연다
    ok = client.get(f"/api/v1/public/apps/{token}/kb-images/{fid}", headers=team.h("member"))
    assert ok.status_code == 200 and ok.headers["content-type"] == "image/png"


def test_builder_image_endpoint_per_role(
    client: TestClient, team: Team, fake_llm: FakeAdapter, outsider: dict[str, str]
) -> None:
    add_llm(client, team, provider="openai", model="gpt-4o-mini")
    kb, _doc = _index_images(client, team)
    with SessionLocal() as db:
        fid = next(f.id for f in db.scalars(select(StoredFile)))
    url = f"/api/v1/knowledge-bases/{kb['id']}/images/{fid}"
    for role in ROLES:
        got = client.get(url, headers=team.h(role))
        assert (got.status_code == 200) == (role in ("owner", "admin", "builder", "operator")), role
        if got.status_code == 200:
            assert got.headers["content-type"] == "image/png"
    assert client.get(url).status_code == 401
    assert client.get(url, headers=outsider).status_code in (403, 404)
    other = _kb(client, team, "다른 지식")
    assert (
        client.get(
            f"/api/v1/knowledge-bases/{other['id']}/images/{fid}", headers=team.h("builder")
        ).status_code
        == 404
    )


def test_chat_citations_carry_image_with_signed_url_and_resign_on_reload(
    client: TestClient, team: Team, fake_llm: FakeAdapter
) -> None:
    kb, _doc, _app, token = _image_app(client, team)
    events = chat(client, token, "이미지 1장을 봤어요")
    cites = next((d for n, d in events if n == "citations"), None)
    assert cites, events
    with_img = [c for c in cites if c.get("image")]
    assert with_img, cites
    img = with_img[0]["image"]
    assert img["caption"] and img["kb_id"] == kb["id"]
    assert img["url"].startswith(f"/api/v1/public/apps/{token}/kb-images/{img['file_id']}?exp=")
    # 서명 주소로 실제 그림이 열린다
    assert client.get(img["url"]).status_code == 200
    # 지난 대화를 다시 열면 새 서명 주소가 붙는다(저장된 인용에는 주소를 남기지 않는다)
    sid = next(d for n, d in events if n == "session")["session_id"]
    with SessionLocal() as db:
        from api.models import Message

        stored = [m.citations for m in db.scalars(select(Message)) if m.citations]
        assert stored and all("url" not in (c.get("image") or {}) for c in stored[0])
    time.sleep(1.1)  # exp가 초 단위라 서명이 달라지는지 보려면 1초 이상 흘려야 한다
    msgs = client.get(f"/api/v1/public/apps/{token}/sessions/{sid}/messages").json()
    again = next(m["citations"] for m in msgs if m["citations"])
    url2 = next(c["image"]["url"] for c in again if c.get("image"))
    assert url2 != img["url"] and client.get(url2).status_code == 200


def test_ip_guard_applies_to_image_links(
    client: TestClient, team: Team, fake_llm: FakeAdapter
) -> None:
    _kb, _doc, app_id, token = _image_app(client, team)
    with SessionLocal() as db:
        fid = next(f.id for f in db.scalars(select(StoredFile)))
    dep = client.get(f"/api/v1/apps/{app_id}/deployments", headers=team.h("builder")).json()[0]
    r = client.patch(
        f"/api/v1/deployments/{dep['id']}",
        json={"allowed_ips": ["203.0.113.7"]},
        headers=team.h("builder"),
    )
    assert r.status_code == 200, r.text
    assert client.get(ki.signed_path(token, fid)).status_code == 403
