"""LLM 어댑터를 실제 SDK로 돌리되, 전송 계층에서 준비한 응답을 돌려준다(키·네트워크 없이).

확인하는 것: 요청 형식(모델, 툴, 베타 헤더, fallbacks, effort, temperature 미전송),
스트리밍 텍스트·툴 호출 파싱, 거절·인증 오류를 한국어 LlmError로 바꾸는지.
"""

import json
from typing import Any

import httpx2
import pytest

from api.llm.anthropic_adapter import FALLBACK_BETA, AnthropicAdapter
from api.llm.base import LlmError, ToolDef
from api.llm.openai_adapter import OpenAIAdapter

TOOLS = [
    ToolDef(
        "add_node",
        "단계 추가",
        {"type": "object", "properties": {"type": {"type": "string"}}, "required": ["type"]},
    )
]


def sse(events: list[tuple[str, dict[str, Any]]]) -> bytes:
    return "".join(
        f"event: {e}\ndata: {json.dumps(d, ensure_ascii=False)}\n\n" for e, d in events
    ).encode()


def anthropic_stream(text: str, tool_input: dict[str, Any] | None) -> bytes:
    msg: dict[str, Any] = {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": "claude-sonnet-5-5",
        "content": [],
        "stop_reason": None,
        "stop_sequence": None,
        "usage": {"input_tokens": 120, "output_tokens": 1},
    }
    ev: list[tuple[str, dict[str, Any]]] = [
        ("message_start", {"type": "message_start", "message": msg})
    ]
    ev += [
        (
            "content_block_start",
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "text", "text": ""},
            },
        ),
        (
            "content_block_delta",
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": text[:3]},
            },
        ),
        (
            "content_block_delta",
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": text[3:]},
            },
        ),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
    ]
    stop = "end_turn"
    if tool_input is not None:
        raw = json.dumps(tool_input, ensure_ascii=False)
        ev += [
            (
                "content_block_start",
                {
                    "type": "content_block_start",
                    "index": 1,
                    "content_block": {
                        "type": "tool_use",
                        "id": "toolu_1",
                        "name": "add_node",
                        "input": {},
                    },
                },
            ),
            (
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": 1,
                    "delta": {"type": "input_json_delta", "partial_json": raw[:5]},
                },
            ),
            (
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": 1,
                    "delta": {"type": "input_json_delta", "partial_json": raw[5:]},
                },
            ),
            ("content_block_stop", {"type": "content_block_stop", "index": 1}),
        ]
        stop = "tool_use"
    ev += [
        (
            "message_delta",
            {
                "type": "message_delta",
                "delta": {"stop_reason": stop, "stop_sequence": None},
                "usage": {"output_tokens": 30},
            },
        ),
        ("message_stop", {"type": "message_stop"}),
    ]
    return sse(ev)


class Recorder:
    def __init__(self, responder: Any) -> None:
        self.requests: list[httpx2.Request] = []
        self.responder = responder

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        resp: httpx2.Response = self.responder(request)
        return resp

    def body(self, i: int = -1) -> dict[str, Any]:
        data: dict[str, Any] = json.loads(self.requests[i].content)
        return data


def anthropic_adapter(rec: Recorder) -> AnthropicAdapter:
    return AnthropicAdapter(
        "sk-ant-test", http_client=httpx2.Client(transport=httpx2.MockTransport(rec))
    )


def test_anthropic_chat_streams_text_and_tool_call() -> None:
    rec = Recorder(
        lambda r: httpx2.Response(
            200,
            content=anthropic_stream("단계를 추가할게요.", {"type": "llm"}),
            headers={"content-type": "text/event-stream"},
        )
    )
    deltas: list[str] = []
    turn = anthropic_adapter(rec).chat(
        model="claude-sonnet-5-5",
        system="시스템",
        messages=[{"role": "user", "content": "만들어 줘"}],
        tools=TOOLS,
        on_text=deltas.append,
    )
    assert "".join(deltas) == "단계를 추가할게요." and len(deltas) == 2
    assert turn.text == "단계를 추가할게요."
    assert [(c.name, c.input) for c in turn.tool_calls] == [("add_node", {"type": "llm"})]
    assert turn.stop_reason == "tool_use" and turn.input_tokens == 120 and turn.output_tokens == 30

    req = rec.requests[0]
    body = rec.body()
    assert req.url.path == "/v1/messages"
    assert FALLBACK_BETA in req.headers.get("anthropic-beta", "")
    assert body["fallbacks"] == "default"
    assert body["output_config"] == {"effort": "medium"}
    assert body["stream"] is True
    assert body["tools"][0]["eager_input_streaming"] is True
    assert "temperature" not in body and "tool_choice" not in body
    assert body["system"] == "시스템"


def test_anthropic_tool_results_are_grouped_into_one_user_message() -> None:
    rec = Recorder(
        lambda r: httpx2.Response(
            200, content=anthropic_stream("끝", None), headers={"content-type": "text/event-stream"}
        )
    )
    adapter = anthropic_adapter(rec)
    first = [
        {"type": "tool_use", "id": "t1", "name": "add_node", "input": {}},
        {"type": "tool_use", "id": "t2", "name": "add_node", "input": {}},
    ]
    adapter.chat(
        model="claude-sonnet-5-5",
        system="s",
        messages=[
            {"role": "user", "content": "요청"},
            {"role": "assistant", "content": "", "tool_calls": [], "native": first},
            {
                "role": "tool",
                "tool_call_id": "t1",
                "name": "add_node",
                "content": "{}",
                "is_error": False,
            },
            {
                "role": "tool",
                "tool_call_id": "t2",
                "name": "add_node",
                "content": "{}",
                "is_error": True,
            },
        ],
        tools=TOOLS,
    )
    msgs = rec.body()["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant", "user"]
    assert [b["tool_use_id"] for b in msgs[2]["content"]] == ["t1", "t2"]
    assert msgs[2]["content"][1]["is_error"] is True


def test_anthropic_complete_parses_json_and_skips_temperature() -> None:
    reply = {
        "id": "msg_2",
        "type": "message",
        "role": "assistant",
        "model": "claude-sonnet-5-5",
        "content": [{"type": "text", "text": '{"category": "billing"}'}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }
    rec = Recorder(lambda r: httpx2.Response(200, json=reply))
    result = anthropic_adapter(rec).complete(
        model="claude-sonnet-5-5",
        system="분류",
        prompt="결제가 두 번",
        temperature=0.2,
        json_schema={"type": "object", "properties": {"category": {"type": "string"}}},
    )
    assert result.data == {"category": "billing"}
    body = rec.body()
    assert "temperature" not in body
    assert body["output_config"] == {"effort": "low"}
    assert "JSON Schema" in body["system"]


def test_anthropic_refusal_and_auth_errors_are_korean() -> None:
    refusal: dict[str, Any] = {
        "id": "m",
        "type": "message",
        "role": "assistant",
        "model": "claude-sonnet-5-5",
        "content": [],
        "stop_reason": "refusal",
        "stop_sequence": None,
        "usage": {"input_tokens": 1, "output_tokens": 0},
    }
    with pytest.raises(LlmError) as exc:
        anthropic_adapter(Recorder(lambda r: httpx2.Response(200, json=refusal))).complete(
            model="claude-sonnet-5-5", system="", prompt="x", temperature=None, json_schema=None
        )
    assert exc.value.message == "AI가 이 요청에는 답하지 않았어요."
    err = {
        "type": "error",
        "error": {"type": "authentication_error", "message": "invalid x-api-key"},
    }
    with pytest.raises(LlmError) as exc:
        anthropic_adapter(Recorder(lambda r: httpx2.Response(401, json=err))).complete(
            model="claude-sonnet-5-5", system="", prompt="x", temperature=None, json_schema=None
        )
    assert exc.value.message == "AI 연결 키가 올바르지 않아요."
    assert "invalid" not in exc.value.message + exc.value.hint


def test_anthropic_custom_base_url_disables_fallbacks() -> None:
    rec = Recorder(
        lambda r: httpx2.Response(
            200, content=anthropic_stream("ok", None), headers={"content-type": "text/event-stream"}
        )
    )
    adapter = AnthropicAdapter(
        "k",
        "https://proxy.example.com",
        http_client=httpx2.Client(transport=httpx2.MockTransport(rec)),
    )
    adapter.chat(
        model="claude-sonnet-5-5",
        system="s",
        messages=[{"role": "user", "content": "x"}],
        tools=TOOLS,
    )
    assert "fallbacks" not in rec.body()
    assert FALLBACK_BETA not in rec.requests[0].headers.get("anthropic-beta", "")


# ---------------- OpenAI ----------------
def openai_adapter(rec: Recorder) -> OpenAIAdapter:
    return OpenAIAdapter("sk-test", http_client=httpx2.Client(transport=httpx2.MockTransport(rec)))


def completion(
    content: str | None, tool_calls: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    return {
        "id": "c1",
        "object": "chat.completion",
        "created": 1,
        "model": "gpt-4o-mini",
        "choices": [
            {
                "index": 0,
                "finish_reason": "tool_calls" if tool_calls else "stop",
                "message": {"role": "assistant", "content": content, "tool_calls": tool_calls},
            }
        ],
        "usage": {"prompt_tokens": 50, "completion_tokens": 7, "total_tokens": 57},
    }


def test_openai_chat_tool_calls_and_message_format() -> None:
    call = {
        "id": "call_1",
        "type": "function",
        "function": {"name": "add_node", "arguments": '{"type": "output"}'},
    }
    rec = Recorder(lambda r: httpx2.Response(200, json=completion("추가할게요", [call])))
    turn = openai_adapter(rec).chat(
        model="gpt-4o-mini", system="s", messages=[{"role": "user", "content": "x"}], tools=TOOLS
    )
    assert turn.tool_calls[0].input == {"type": "output"} and turn.stop_reason == "tool_use"
    body = rec.body()
    assert body["tool_choice"] == "auto"
    assert body["tools"][0]["function"]["name"] == "add_node"
    assert body["messages"][0] == {"role": "system", "content": "s"}


def test_openai_complete_retries_without_temperature_on_400() -> None:
    def respond(r: httpx2.Request) -> httpx2.Response:
        if "temperature" in json.loads(r.content):
            return httpx2.Response(
                400,
                json={
                    "error": {
                        "message": "temperature not supported",
                        "type": "invalid_request_error",
                    }
                },
            )
        return httpx2.Response(200, json=completion('{"category": "tech"}'))

    rec = Recorder(respond)
    result = openai_adapter(rec).complete(
        model="o4-mini", system="", prompt="x", temperature=0.2, json_schema={"type": "object"}
    )
    assert result.data == {"category": "tech"}
    assert len(rec.requests) == 2 and "temperature" not in rec.body(1)


def test_openai_embeddings() -> None:
    rec = Recorder(
        lambda r: httpx2.Response(
            200,
            json={
                "object": "list",
                "model": "text-embedding-3-small",
                "data": [{"object": "embedding", "index": 0, "embedding": [0.1, 0.2]}],
                "usage": {"prompt_tokens": 2, "total_tokens": 2},
            },
        )
    )
    assert openai_adapter(rec).embed(model="text-embedding-3-small", texts=["안녕"]) == [[0.1, 0.2]]
    assert rec.requests[0].url.path.endswith("/embeddings")
