"""Anthropic(Claude) 어댑터. 공식 SDK(anthropic 2.x)를 쓴다.

- 최신 API 버전은 temperature를 받지 않으므로 보내지 않는다(ADR 0003).
- 최신 모델은 강제 tool_choice를 거부하므로 auto만 쓴다.
- 공식 API로 Claude 5 세대를 부를 때는 거절 시 대체 모델로 넘기는 fallbacks를 켠다.
"""

import json
import re
from typing import Any

import anthropic

from api.llm.base import (
    KIND_AUTH,
    KIND_CONTENT_FILTER,
    KIND_CONTEXT,
    KIND_OTHER,
    KIND_OUTAGE,
    KIND_RATE_LIMIT,
    ChatTurn,
    LlmError,
    Message,
    OnText,
    ToolCall,
    ToolDef,
    json_instruction,
    parse_json_object,
)
from api.llm.vision import ImageInput, anthropic_user_content
from nodes import LlmResult

FALLBACK_BETA = "server-side-fallback-2026-07-01"
_FALLBACK_MODELS = {"claude-sonnet-5-5", "claude-opus-5-5", "claude-opus-5", "claude-fable-5-1"}
_EFFORT_MODEL = re.compile(r"^claude-(opus|sonnet|haiku|fable)-5")


def _map_error(exc: Exception) -> LlmError:
    if isinstance(exc, anthropic.AuthenticationError):
        return LlmError(
            "AI 연결 키가 올바르지 않아요.",
            "워크스페이스 설정에서 Anthropic 키를 다시 등록하세요.",
            kind=KIND_AUTH,
        )
    if isinstance(exc, anthropic.PermissionDeniedError):
        return LlmError(
            "이 키로는 해당 모델을 쓸 수 없어요.",
            "키 권한을 확인하거나 다른 모델을 고르세요.",
            kind=KIND_AUTH,
        )
    if isinstance(exc, anthropic.NotFoundError):
        return LlmError("모델을 찾을 수 없어요.", "모델 이름을 확인하세요(예: claude-sonnet-5-5).")
    if isinstance(exc, anthropic.RateLimitError):
        return LlmError(
            "AI 요청이 너무 많아요.",
            "잠시 후 다시 시도하세요.",
            retryable=True,
            kind=KIND_RATE_LIMIT,
        )
    if isinstance(exc, anthropic.BadRequestError):
        text = str(exc).lower()
        too_long = "prompt is too long" in text or ("context" in text and "exceed" in text)
        return LlmError(
            "AI가 요청 형식을 받아들이지 않았어요.",
            "모델 이름과 단계 설정을 확인하세요.",
            kind=KIND_CONTEXT if too_long else KIND_OTHER,
        )
    if isinstance(exc, anthropic.APIConnectionError):
        return LlmError(
            "AI 서버에 연결하지 못했어요.",
            "네트워크를 확인하고 다시 시도하세요.",
            retryable=True,
            kind=KIND_OUTAGE,
        )
    if isinstance(exc, anthropic.APIStatusError):
        status = int(getattr(exc, "status_code", 0) or 0)
        return LlmError(
            "AI 서버에서 오류가 났어요.",
            "잠시 후 다시 시도하세요.",
            retryable=True,
            kind=KIND_OUTAGE if status >= 500 else KIND_OTHER,
        )
    return LlmError("AI 호출 중 문제가 생겼어요.", "잠시 후 다시 시도하세요.")


def _refusal() -> LlmError:
    return LlmError(
        "AI가 이 요청에는 답하지 않았어요.",
        "요청 내용을 바꿔서 다시 시도하세요.",
        kind=KIND_CONTENT_FILTER,
    )


class AnthropicAdapter:
    provider = "anthropic"

    def __init__(
        self, api_key: str, base_url: str | None = None, *, http_client: Any = None
    ) -> None:
        self.base_url = base_url
        kwargs: dict[str, Any] = {"api_key": api_key, "max_retries": 2, "timeout": 120.0}
        if base_url:
            kwargs["base_url"] = base_url
        if http_client is not None:  # 테스트용 전송 계층 주입
            kwargs["http_client"] = http_client
        self.client = anthropic.Anthropic(**kwargs)

    def _extra(self, model: str, effort: str | None) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if effort and _EFFORT_MODEL.match(model):
            params["output_config"] = {"effort": effort}
        if not self.base_url and model in _FALLBACK_MODELS:
            params["betas"] = [FALLBACK_BETA]
            params["fallbacks"] = "default"
        return params

    def complete(
        self,
        *,
        model: str,
        system: str,
        prompt: str,
        temperature: float | None,
        json_schema: dict[str, Any] | None,
        on_delta: OnText | None = None,
        images: list[ImageInput] | None = None,
    ) -> LlmResult:
        del temperature  # 현재 API 버전은 temperature를 받지 않는다(ADR 0003)
        sys_prompt = system + (json_instruction(json_schema) if json_schema else "")
        params: dict[str, Any] = {
            "model": model,
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": anthropic_user_content(prompt, images or [])}],
            **self._extra(model, "low"),
        }
        if sys_prompt.strip():
            params["system"] = sys_prompt
        try:
            if on_delta is not None:
                with self.client.beta.messages.stream(**params) as stream:
                    for event in stream:
                        if event.type == "text":
                            on_delta(event.text)
                    resp = stream.get_final_message()
            else:
                resp = self.client.beta.messages.create(**params)
        except anthropic.APIError as exc:
            raise _map_error(exc) from exc
        if resp.stop_reason == "refusal":
            raise _refusal()
        text = "".join(b.text for b in resp.content if b.type == "text")
        return LlmResult(
            text=text,
            data=parse_json_object(text) if json_schema else None,
            model=resp.model,
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
        )

    def chat(
        self,
        *,
        model: str,
        system: str,
        messages: list[Message],
        tools: list[ToolDef],
        on_text: OnText | None = None,
    ) -> ChatTurn:
        native_tools = [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.input_schema,
                "eager_input_streaming": True,
            }
            for t in tools
        ]
        params: dict[str, Any] = {
            "model": model,
            "max_tokens": 16000,
            "system": system,
            "messages": self._to_native(messages),
            "tools": native_tools,
            **self._extra(model, "medium"),
        }
        try:
            with self.client.beta.messages.stream(**params) as stream:
                for event in stream:
                    if event.type == "text" and on_text is not None:
                        on_text(event.text)
                final = stream.get_final_message()
        except ValueError as exc:
            # 툴 입력 JSON을 아예 읽지 못한 경우(eager 입력 스트리밍)
            raise LlmError(
                "AI 응답을 읽는 중 문제가 생겼어요.",
                "같은 요청을 한 번 더 보내 주세요.",
                retryable=True,
            ) from exc
        except anthropic.APIError as exc:
            raise _map_error(exc) from exc
        if final.stop_reason == "refusal":
            raise _refusal()
        text = ""
        calls: list[ToolCall] = []
        for block in final.content:
            if block.type == "text":
                text += block.text
            elif block.type == "tool_use":
                raw = block.input if isinstance(block.input, dict) else {}
                invalid = None
                if final.stop_reason == "max_tokens":
                    invalid = json.dumps(raw, ensure_ascii=False)
                calls.append(
                    ToolCall(id=block.id, name=block.name, input=raw, invalid_input=invalid)
                )
        return ChatTurn(
            text=text,
            tool_calls=calls,
            stop_reason=str(final.stop_reason),
            input_tokens=final.usage.input_tokens,
            output_tokens=final.usage.output_tokens,
            model=final.model,
            native=final.content,
        )

    @staticmethod
    def _to_native(messages: list[Message]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for m in messages:
            role = m["role"]
            if role == "user":
                out.append({"role": "user", "content": m["content"]})
            elif role == "assistant":
                # 같은 대화 안에서는 원본 단계(생각 단계 포함)을 바꾸지 않고 그대로 돌려준다
                content = m.get("native") if m.get("native") is not None else m["content"]
                out.append({"role": "assistant", "content": content})
            elif role == "tool":
                block = {
                    "type": "tool_result",
                    "tool_use_id": m["tool_call_id"],
                    "content": m["content"],
                    "is_error": bool(m.get("is_error")),
                }
                if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list):
                    out[-1]["content"].append(block)
                else:
                    out.append({"role": "user", "content": [block]})
        return out

    def embed(self, *, model: str, texts: list[str]) -> list[list[float]]:
        raise LlmError(
            "Anthropic 연결로는 문서 임베딩을 만들 수 없어요.",
            "워크스페이스 설정에 OpenAI 연결을 추가하세요(임베딩 기본: text-embedding-3-small).",
        )
