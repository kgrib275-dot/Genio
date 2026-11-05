"""OpenAI 및 OpenAI 호환(openai-compatible) 어댑터."""

import json
from typing import Any, cast

import openai

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
from api.llm.image import (
    RawImageResult,
    map_image_error,
    native_size,
    one_image_per_call,
    parse_images_response,
)
from api.llm.vision import ImageInput, openai_user_content
from nodes import LlmResult

AZURE_API_VERSION = "2024-10-21"
EMBEDDING_DIM = 1536


def azure_endpoint(base_url: str) -> tuple[str, str]:
    """'https://x.openai.azure.com/?api-version=2024-10-21' → (주소, api-version)."""
    from urllib.parse import parse_qs, urlparse

    u = urlparse(base_url.strip())
    if u.scheme != "https" or not u.netloc:
        raise LlmError(
            "Azure 주소가 올바르지 않아요.",
            "예: https://my-resource.openai.azure.com/ (api-version은 ?api-version=... 로 덧붙여요)",
        )
    version = (parse_qs(u.query).get("api-version") or [AZURE_API_VERSION])[0]
    return f"https://{u.netloc}/", version


def _bad_request_kind(exc: Exception) -> str:
    """400 오류가 '입력이 너무 길다' / '안전 정책에 걸렸다'인지 코드·문구로 가려낸다."""
    code = str(getattr(exc, "code", "") or "").lower()
    text = f"{code} {exc}".lower()
    if "context_length" in text or "maximum context" in text or "too many tokens" in text:
        return KIND_CONTEXT
    if "content_filter" in text or "content management policy" in text or "safety" in code:
        return KIND_CONTENT_FILTER
    return KIND_OTHER


def _map_error(exc: Exception) -> LlmError:
    if isinstance(exc, openai.AuthenticationError | openai.PermissionDeniedError):
        return LlmError(
            "AI 연결 키가 올바르지 않아요.",
            "워크스페이스 설정에서 키를 다시 등록하세요.",
            kind=KIND_AUTH,
        )
    if isinstance(exc, openai.NotFoundError):
        return LlmError("모델을 찾을 수 없어요.", "모델 이름을 확인하세요(예: gpt-4o-mini).")
    if isinstance(exc, openai.RateLimitError):
        return LlmError(
            "AI 요청이 너무 많거나 사용 한도를 넘었어요.",
            "잠시 후 다시 시도하거나 결제 한도를 확인하세요.",
            retryable=True,
            kind=KIND_RATE_LIMIT,
        )
    if isinstance(exc, openai.BadRequestError):
        return LlmError(
            "AI가 요청 형식을 받아들이지 않았어요.",
            "모델 이름과 단계 설정을 확인하세요.",
            kind=_bad_request_kind(exc),
        )
    if isinstance(exc, openai.APIConnectionError):
        return LlmError(
            "AI 서버에 연결하지 못했어요.",
            "주소(base URL)와 네트워크를 확인하세요.",
            retryable=True,
            kind=KIND_OUTAGE,
        )
    if isinstance(exc, openai.APIStatusError):
        status = int(getattr(exc, "status_code", 0) or 0)
        return LlmError(
            "AI 서버에서 오류가 났어요.",
            "잠시 후 다시 시도하세요.",
            retryable=True,
            kind=KIND_OUTAGE if status >= 500 else KIND_OTHER,
        )
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
        if http_client is not None:  # 테스트용 전송 계층 주입
            kwargs["http_client"] = http_client
        if provider == "azure":
            # Azure OpenAI: base_url = https://<리소스>.openai.azure.com/ (?api-version=... 선택)
            # 모델 이름 자리에는 Azure의 '배포 이름'을 쓴다.
            endpoint, api_version = azure_endpoint(base_url or "")
            self.client: openai.OpenAI = openai.AzureOpenAI(
                azure_endpoint=endpoint, api_version=api_version, **kwargs
            )
            return
        if base_url:
            kwargs["base_url"] = base_url
        self.client = openai.OpenAI(**kwargs)

    def generate_images(self, *, model: str, prompt: str, size: str, count: int) -> RawImageResult:
        """이미지 만들기(v0.9). 그림은 가공 없이(b64·주소) 돌려준다. 받기·검사·저장은 서비스 몫."""
        n_each = 1 if one_image_per_call(model) else count
        calls = count if n_each == 1 else 1
        result = RawImageResult(model=model)
        try:
            for _ in range(calls):
                resp = self.client.images.generate(
                    model=model,
                    prompt=prompt,
                    size=native_size(model, size),
                    n=n_each,
                )
                result.images.extend(parse_images_response(resp))
                usage = getattr(resp, "usage", None)
                if usage is not None:
                    result.input_tokens += int(getattr(usage, "input_tokens", 0) or 0)
                    result.output_tokens += int(getattr(usage, "output_tokens", 0) or 0)
        except openai.OpenAIError as exc:
            raise map_image_error(exc) from exc
        return result

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
        sys_prompt = system + (json_instruction(json_schema) if json_schema else "")
        msgs: list[dict[str, Any]] = []
        if sys_prompt.strip():
            msgs.append({"role": "system", "content": sys_prompt})
        msgs.append({"role": "user", "content": openai_user_content(prompt, images or [])})
        params: dict[str, Any] = {"model": model, "messages": msgs}
        if temperature is not None:
            params["temperature"] = temperature
        if json_schema:
            params["response_format"] = {"type": "json_object"}
        if on_delta is not None and not json_schema:
            return self._complete_stream(params, on_delta)
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

    def _complete_stream(self, params: dict[str, Any], on_delta: OnText) -> LlmResult:
        """답을 조각으로 받으며 on_delta로 넘긴다. 사용량은 마지막 조각에 온다."""
        text = ""
        model = str(params["model"])
        in_tok = out_tok = 0
        try:
            try:
                stream = self.client.chat.completions.create(
                    **params, stream=True, stream_options={"include_usage": True}
                )
            except openai.BadRequestError:
                params.pop("temperature", None)
                stream = self.client.chat.completions.create(
                    **params, stream=True, stream_options={"include_usage": True}
                )
            for chunk in stream:
                model = chunk.model or model
                if chunk.choices:
                    piece = chunk.choices[0].delta.content or ""
                    if piece:
                        text += piece
                        on_delta(piece)
                if chunk.usage:
                    in_tok = chunk.usage.prompt_tokens
                    out_tok = chunk.usage.completion_tokens
        except openai.OpenAIError as exc:
            raise _map_error(exc) from exc
        return LlmResult(text=text, model=model, input_tokens=in_tok, output_tokens=out_tok)

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
            extra: dict[str, Any] = {}
            if model.startswith("text-embedding-3"):
                # 저장 칸이 1536차원이라 large도 1536으로 줄여 받는다(OpenAI 기능)
                extra["dimensions"] = EMBEDDING_DIM
            resp = self.client.embeddings.create(model=model, input=texts, **extra)
        except openai.OpenAIError as exc:
            raise _map_error(exc) from exc
        return [list(d.embedding) for d in resp.data]
