"""v0.6 AI 공급자 20곳+(OpenAI 호환 preset)와 비전(이미지) 입력."""

import base64
import io
from typing import Any

import httpx2
import pytest
from fastapi.testclient import TestClient

from api.llm import google_adapter as google_mod
from api.llm.anthropic_adapter import AnthropicAdapter
from api.llm.openai_adapter import OpenAIAdapter
from api.llm.presets import PRESETS, provider_list
from api.llm.registry import default_factory
from api.llm.vision import ImageError, ImageInput, check_image, sniff_mime
from api.tests.conftest import Team
from api.tests.fakes import FakeAdapter
from api.tests.test_llm_adapters import Recorder, completion
from api.tests.test_v05_engine import make_app, start

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 64


# ---------------- 공급자 preset ----------------
def test_provider_list_has_20_plus_with_base_urls(client: TestClient, team: Team) -> None:
    items = client.get("/api/v1/llm/providers", headers=team.h("member")).json()
    keys = {p["key"] for p in items}
    assert len(items) >= 20
    assert {"openai", "anthropic", "google", "azure", "openai-compatible"} <= keys
    assert {"deepseek", "mistral", "groq", "openrouter", "upstage", "qwen"} <= keys
    for p in items:
        if not p["native"]:
            assert p["base_url"].startswith("https://") and p["default_model"], p["key"]
    # 묶음 순서: 기본이 먼저
    assert items[0]["group"] == "기본"
    assert client.get("/api/v1/llm/providers").status_code == 401
    assert provider_list() == items


def test_preset_resolves_to_openai_compatible_adapter() -> None:
    a = default_factory("deepseek", "sk-x", None)
    assert isinstance(a, OpenAIAdapter) and a.provider == "deepseek"
    assert str(a.client.base_url).startswith("https://api.deepseek.com/v1")
    # 주소를 바꿔 넣으면 그 주소를 쓴다
    b = default_factory("groq", "k", "https://proxy.example.com/v1")
    assert isinstance(b, OpenAIAdapter)
    assert str(b.client.base_url).startswith("https://proxy.example.com/v1")


def test_add_preset_provider_masks_key_and_runs(
    client: TestClient, team: Team, fake_llm: FakeAdapter
) -> None:
    url = f"/api/v1/workspaces/{team.ws}/llm-providers"
    body = {
        "provider": "upstage",
        "label": "솔라",
        "api_key": "up-secret-key-1234",
        "default_model": PRESETS["upstage"].default_model,
    }
    res = client.post(url, json=body, headers=team.h("owner"))
    assert res.status_code == 200, res.text
    assert "up-secret-key-1234" not in res.text and res.json()["api_key_masked"].endswith("1234")
    # 목록에 없는 공급자는 두 줄 오류
    bad = client.post(url, json={**body, "provider": "nope-ai"}, headers=team.h("owner"))
    assert bad.status_code == 422 and bad.json()["detail"]["hint"]
    # 권한: 빌더는 키를 등록할 수 없다
    assert client.post(url, json=body, headers=team.h("builder")).status_code == 403


def test_catalog_includes_preset_models(client: TestClient, team: Team) -> None:
    cat = client.get("/api/v1/llm/catalog", headers=team.h("member")).json()
    by = {(m["provider"], m["model"]): m for m in cat}
    assert ("deepseek", "deepseek-chat") in by
    assert by[("mistral", "pixtral-large-latest")]["vision"] is True
    assert by[("deepseek", "deepseek-chat")]["input_price"] == 0.0  # 단가 모름 → 0


# ---------------- 이미지 검사 ----------------
def test_check_image_sniffs_and_limits() -> None:
    assert sniff_mime(PNG) == "image/png" and sniff_mime(JPG) == "image/jpeg"
    assert sniff_mime(b"GIF89a....") == "image/gif"
    assert sniff_mime(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == "image/webp"
    assert check_image(PNG, "a.png").mime == "image/png"
    with pytest.raises(ImageError) as e:
        check_image(b"%PDF-1.7", "a.pdf")
    assert "PNG" in e.value.hint
    with pytest.raises(ImageError):
        check_image(PNG + b"\x00" * (5 * 1024 * 1024), "big.png")


# ---------------- 공급자별 요청 형식 ----------------
def test_openai_sends_image_url_parts() -> None:
    rec = Recorder(lambda r: httpx2.Response(200, json=completion("고양이")))
    a = OpenAIAdapter("sk", http_client=httpx2.Client(transport=httpx2.MockTransport(rec)))
    a.complete(
        model="gpt-4o-mini",
        system="",
        prompt="뭐가 보여?",
        temperature=None,
        json_schema=None,
        images=[ImageInput("image/png", PNG)],
    )
    content = rec.body()["messages"][-1]["content"]
    assert content[0] == {"type": "text", "text": "뭐가 보여?"}
    url = content[1]["image_url"]["url"]
    assert url.startswith("data:image/png;base64,")
    assert base64.b64decode(url.split(",", 1)[1]) == PNG


def test_openai_without_images_keeps_plain_string() -> None:
    rec = Recorder(lambda r: httpx2.Response(200, json=completion("ok")))
    a = OpenAIAdapter("sk", http_client=httpx2.Client(transport=httpx2.MockTransport(rec)))
    a.complete(model="m", system="", prompt="hi", temperature=None, json_schema=None)
    assert rec.body()["messages"][-1]["content"] == "hi"


def test_anthropic_sends_base64_image_block() -> None:
    reply = {
        "id": "m",
        "type": "message",
        "role": "assistant",
        "model": "claude-sonnet-5-5",
        "content": [{"type": "text", "text": "영수증이에요"}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 10, "output_tokens": 3},
    }
    rec = Recorder(lambda r: httpx2.Response(200, json=reply))
    a = AnthropicAdapter(
        "sk-ant",
        "https://proxy.example.com",
        http_client=httpx2.Client(transport=httpx2.MockTransport(rec)),
    )
    out = a.complete(
        model="claude-sonnet-5-5",
        system="",
        prompt="무엇인가요?",
        temperature=None,
        json_schema=None,
        images=[ImageInput("image/jpeg", JPG)],
    )
    assert out.text == "영수증이에요"
    content = rec.body()["messages"][0]["content"]
    assert content[0]["type"] == "image"
    assert content[0]["source"]["media_type"] == "image/jpeg"
    assert base64.b64decode(content[0]["source"]["data"]) == JPG
    assert content[-1] == {"type": "text", "text": "무엇인가요?"}


def test_google_sends_inline_data(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    class Resp:
        status_code = 200

        def json(self) -> dict[str, Any]:
            return {"candidates": [{"content": {"parts": [{"text": "강아지"}]}}]}

    def fake_post(url: str, json: dict[str, Any], **kw: Any) -> Resp:
        seen["body"] = json
        return Resp()

    monkeypatch.setattr("api.llm.google_adapter.httpx.post", fake_post)
    out = google_mod.GoogleAdapter("g-key").complete(
        model="gemini-2.0-flash",
        system="",
        prompt="뭐야?",
        temperature=None,
        json_schema=None,
        images=[ImageInput("image/png", PNG)],
    )
    assert out.text == "강아지"
    parts = seen["body"]["contents"][0]["parts"]
    assert parts[0]["inline_data"]["mime_type"] == "image/png"
    assert parts[-1] == {"text": "뭐야?"}


# ---------------- 흐름에서: 입력 파일 → AI 단계 이미지 ----------------
VISION_GRAPH: dict[str, Any] = {
    "nodes": [
        {
            "id": "n1",
            "type": "input",
            "data": {"fields": [{"key": "photo", "type": "file", "required": True}]},
        },
        {
            "id": "n2",
            "type": "llm",
            "data": {"prompt": "사진을 설명해 줘", "images": ["{{n1.photo}}"]},
        },
        {"id": "n3", "type": "output", "data": {"template": "{{n2.text}}"}},
    ],
    "edges": [
        {"id": "e1", "source": "n1", "target": "n2"},
        {"id": "e2", "source": "n2", "target": "n3"},
    ],
}


def _upload(client: TestClient, team: Team, name: str, data: bytes, mime: str) -> str:
    res = client.post(
        f"/api/v1/workspaces/{team.ws}/files",
        files={"file": (name, io.BytesIO(data), mime)},
        headers=team.h("builder"),
    )
    assert res.status_code in (200, 201), res.text
    fid: str = res.json()["id"]
    return fid


def _add_key(client: TestClient, team: Team) -> None:
    res = client.post(
        f"/api/v1/workspaces/{team.ws}/llm-providers",
        json={
            "provider": "openai",
            "label": "기본",
            "api_key": "sk-test-1",
            "default_model": "gpt-4o-mini",
        },
        headers=team.h("owner"),
    )
    assert res.status_code == 200, res.text


def test_flow_sends_uploaded_image_to_ai(
    client: TestClient, team: Team, fake_llm: FakeAdapter
) -> None:
    _add_key(client, team)
    app_id = make_app(client, team, VISION_GRAPH)
    v = client.post(f"/api/v1/apps/{app_id}/validate", json={}, headers=team.h("builder")).json()
    assert v["valid"], v["errors"]
    fid = _upload(client, team, "cat.png", PNG, "image/png")
    d = start(client, team, app_id, {"photo": fid})
    assert d["status"] == "succeeded", d["error"]
    assert d["output"]["text"] == "이미지 1장을 봤어요(image/png)."
    imgs = fake_llm.calls[-1]["images"]
    assert len(imgs) == 1 and imgs[0].data == PNG


def test_flow_rejects_non_image_with_two_line_error(
    client: TestClient, team: Team, fake_llm: FakeAdapter
) -> None:
    _add_key(client, team)
    app_id = make_app(client, team, VISION_GRAPH)
    fid = _upload(client, team, "note.txt", "그냥 글".encode(), "text/plain")
    d = start(client, team, app_id, {"photo": fid})
    assert d["status"] == "failed"
    assert "이미지가 아니에요" in d["error"] and "PNG" in d["error"]


def test_too_many_images_rejected(client: TestClient, team: Team, fake_llm: FakeAdapter) -> None:
    _add_key(client, team)
    graph = {
        **VISION_GRAPH,
        "nodes": [
            VISION_GRAPH["nodes"][0],
            {
                "id": "n2",
                "type": "llm",
                "data": {"prompt": "x", "images": ["{{n1.photo}}"]},
            },
            VISION_GRAPH["nodes"][2],
        ],
    }
    app_id = make_app(client, team, graph)
    ids = [_upload(client, team, f"p{i}.png", PNG, "image/png") for i in range(5)]
    d = start(client, team, app_id, {"photo": ids})
    assert d["status"] == "failed" and "4장까지" in d["error"]


def test_llm_images_schema_validation(client: TestClient, team: Team) -> None:
    graph = {
        **VISION_GRAPH,
        "nodes": [
            VISION_GRAPH["nodes"][0],
            {"id": "n2", "type": "llm", "data": {"prompt": "x", "images": "{{n1.photo}}"}},
            VISION_GRAPH["nodes"][2],
        ],
    }
    app_id = make_app(client, team, graph)
    v = client.post(f"/api/v1/apps/{app_id}/validate", json={}, headers=team.h("builder")).json()
    assert not v["valid"] and any(e["field"] == "images" for e in v["errors"])


def test_image_url_follows_private_network_block(
    client: TestClient, team: Team, fake_llm: FakeAdapter
) -> None:
    _add_key(client, team)
    graph = {
        **VISION_GRAPH,
        "nodes": [
            {"id": "n1", "type": "input", "data": {"fields": [{"key": "m"}]}},
            {
                "id": "n2",
                "type": "llm",
                "data": {"prompt": "x", "images": ["http://localhost/secret.png"]},
            },
            VISION_GRAPH["nodes"][2],
        ],
    }
    app_id = make_app(client, team, graph)
    d = start(client, team, app_id, {"m": "a"})
    assert d["status"] == "failed" and "localhost" in d["error"]
    assert fake_llm.calls == []
