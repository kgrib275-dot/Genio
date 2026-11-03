"""Google(Gemini) 어댑터. REST(generateContent)를 httpx로 호출한다. 키는 헤더로만 보낸다."""

from typing import Any

import httpx

from api.llm.base import (
    ChatTurn,
    LlmError,
    Message,
    OnText,
    ToolDef,
    json_instruction,
    parse_json_object,
)
from nodes import LlmResult

DEFAULT_BASE = "https://generativelanguage.googleapis.com/v1beta"


class GoogleAdapter:
    provider = "google"

    def __init__(self, api_key: str, base_url: str | None = None) -> None:
        self.api_key = api_key
        self.base = (base_url or DEFAULT_BASE).rstrip("/")

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            resp = httpx.post(
                f"{self.base}/{path}",
                json=body,
                headers={"x-goog-api-key": self.api_key},
                timeout=120.0,
            )
        except httpx.HTTPError as exc:
            raise LlmError(
                "AI 서버에 연결하지 못했어요.",
                "네트워크를 확인하고 다시 시도하세요.",
                retryable=True,
            ) from exc
        if resp.status_code in (401, 403):
            raise LlmError(
                "AI 연결 키가 올바르지 않아요.",
                "워크스페이스 설정에서 Google 키를 다시 등록하세요.",
            )
        if resp.status_code == 404:
            raise LlmError(
                "모델을 찾을 수 없어요.", "모델 이름을 확인하세요(예: gemini-2.0-flash)."
            )
        if resp.status_code == 429:
            raise LlmError("AI 요청이 너무 많아요.", "잠시 후 다시 시도하세요.", retryable=True)
        if resp.status_code >= 400:
            raise LlmError("AI가 요청을 처리하지 못했어요.", "모델 이름과 노드 설정을 확인하세요.")
        data = resp.json()
        return data if isinstance(data, dict) else {}

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
        body: dict[str, Any] = {"contents": [{"role": "user", "parts": [{"text": prompt}]}]}
        if sys_prompt.strip():
            body["systemInstruction"] = {"parts": [{"text": sys_prompt}]}
        gen: dict[str, Any] = {}
        if temperature is not None:
            gen["temperature"] = temperature
        if json_schema:
            gen["responseMimeType"] = "application/json"
        if gen:
            body["generationConfig"] = gen
        data = self._post(f"models/{model}:generateContent", body)
        parts = (data.get("candidates") or [{}])[0].get("content", {}).get("parts", [])
        text = "".join(p.get("text", "") for p in parts)
        usage = data.get("usageMetadata", {})
        return LlmResult(
            text=text,
            data=parse_json_object(text) if json_schema else None,
            model=model,
            input_tokens=int(usage.get("promptTokenCount", 0)),
            output_tokens=int(usage.get("candidatesTokenCount", 0)),
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
        raise LlmError(
            "빌더 챗은 아직 Google 연결을 지원하지 않아요.",
            "워크스페이스 설정에서 Anthropic 또는 OpenAI 연결을 기본으로 지정하세요.",
        )

    def embed(self, *, model: str, texts: list[str]) -> list[list[float]]:
        raise LlmError(
            "Google 연결로는 아직 문서 임베딩을 만들 수 없어요.",
            "워크스페이스 설정에 OpenAI 연결을 추가하세요.",
        )
