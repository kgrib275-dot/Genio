"""OpenAI 및 OpenAI 호환(openai-compatible) 어댑터."""

import json
from typing import Any, cast

import openai

from api.llm.base import (
    ChatTurn,
    LlmError,
    Message,
    OnText,
    ToolCall,
    ToolDef,
    json_instruction,
    parse_json_object,
)
from nodes import LlmResult


def _map_error(exc: Exception) -> LlmError:
    if isinstance(exc, openai.AuthenticationError):
        return LlmError(
            "AI 연결 키가 올바르지 않아요.", "워크스페이스 설정에서 키를 다시 등록하세요."
        )
    if isinstance(exc, openai.NotFoundError):
        return LlmError("모델을 찾을 수 없어요.", "모델 이름을 확인하세요(예: gpt-4o-mini).")
    if isinstance(exc, openai.RateLimitError):
        return LlmError(
            "AI 요청이 너무 많거나 사용 한도를 넘었어요.",
            "잠시 후 다시 시도하거나 결제 한도를 확인하세요.",
            retryable=True,
        )
    if isinstance(exc, openai.BadRequestError):
        return LlmError(
            "AI가 요청 형식을 받아들이지 않았어요.", "모델 이름과 노드 설정을 확인하세요."
        )
    if isinstance(exc, openai.APIConnectionError):
        return LlmError(
            "AI 서버에 연결하지 못했어요.",
            "주소(base URL)와 네트워크를 확인하세요.",
            retryable=True,
        )
    if isinstance(exc, openai.APIStatusError):
        return LlmError("AI 서버에서 오류가 났어요.", "잠시 후 다시 시도하세요.", retryable=True)
    return LlmError("AI 호출 중 문제가 생겼어요.", "잠시 후 다시 시도하세요.")


class OpenAIAdapter:
    def __init__(
        self,
        api_key: str,
        base_url: str | None = None,
        provider: str = "openai",
        *,
        http_client: Any = None,
    ) -> None:
        self.provider = provider
        kwargs: dict[str, Any] = {"api_key": api_key, "max_retries": 2, "timeout": 120.0}
        if base_url:
            kwargs["base_url"] = base_url
        if http_client is not None:  # 테스트용 전송 계층 주입
            kwargs["http_client"] = http_client
        self.client = openai.OpenAI(**kwargs)

    def complete(
        self,
        *,
        model: str,
        system: str,
        prompt: str,
        temperature: float | None,
        json_schema: dict[str, Any] | None,
    ) -> LlmResult:
        sys_prompt = system + (json_instruction(json_schema) if json_schema else "")
        msgs: list[dict[str, Any]] = []
        if sys_prompt.strip():
            msgs.append({"role": "system", "content": sys_prompt})
        msgs.append({"role": "user", "content": prompt})
        params: dict[str, Any] = {"model": model, "messages": msgs}
        if temperature is not None:
            params["temperature"] = temperature
        if json_schema:
            params["response_format"] = {"type": "json_object"}
        try:
            try:
                resp = self.client.chat.completions.create(**params)
            except openai.BadRequestError:
                # 일부 모델은 temperature/response_format을 받지 않는다 → 빼고 한 번 더
                params.pop("temperature", None)
                params.pop("response_format", None)
                resp = self.client.chat.completions.create(**params)
        except openai.OpenAIError as exc:
            raise _map_error(exc) from exc
        text = resp.choices[0].message.content or "" if resp.choices else ""
        usage = resp.usage
        return LlmResult(
            text=text,
            data=parse_json_object(text) if json_schema else None,
            model=resp.model,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
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
        native: list[dict[str, Any]] = [{"role": "system", "content": system}]
        for m in messages:
            if m["role"] == "user":
                native.append({"role": "user", "content": m["content"]})
            elif m["role"] == "assistant":
                entry: dict[str, Any] = {"role": "assistant", "content": m["content"] or None}
                if m.get("tool_calls"):
                    entry["tool_calls"] = [
                        {
                            "id": c.id,
                            "type": "function",
                            "function": {
                                "name": c.name,
                                "arguments": json.dumps(c.input, ensure_ascii=False),
                            },
                        }
                        for c in m["tool_calls"]
                    ]
                native.append(entry)
            elif m["role"] == "tool":
                native.append(
                    {"role": "tool", "tool_call_id": m["tool_call_id"], "content": m["content"]}
                )
        native_tools = [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.input_schema,
                },
            }
            for t in tools
        ]
        try:
            resp = self.client.chat.completions.create(
                model=model,
                messages=cast(Any, native),
                tools=cast(Any, native_tools),
                tool_choice="auto",
            )
        except openai.OpenAIError as exc:
            raise _map_error(exc) from exc
        choice = resp.choices[0]
        text = choice.message.content or ""
        if text and on_text is not None:
            on_text(text)
        calls: list[ToolCall] = []
        for tc in choice.message.tool_calls or []:
            fn = getattr(tc, "function", None)
            if fn is None:
                continue
            try:
                args = json.loads(fn.arguments or "{}")
                calls.append(
                    ToolCall(id=tc.id, name=fn.name, input=args if isinstance(args, dict) else {})
                )
            except json.JSONDecodeError:
                calls.append(ToolCall(id=tc.id, name=fn.name, input={}, invalid_input=fn.arguments))
        usage = resp.usage
        return ChatTurn(
            text=text,
            tool_calls=calls,
            stop_reason="tool_use" if calls else "end_turn",
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
            model=resp.model,
        )

    def embed(self, *, model: str, texts: list[str]) -> list[list[float]]:
        try:
            resp = self.client.embeddings.create(model=model, input=texts)
        except openai.OpenAIError as exc:
            raise _map_error(exc) from exc
        return [list(d.embedding) for d in resp.data]
