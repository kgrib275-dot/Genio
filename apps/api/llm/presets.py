"""AI 공급자 목록(v0.6, ADR 0010).

기본 5종(openai·anthropic·google·azure·openai-compatible)은 전용 어댑터·설정을 쓴다.
나머지는 OpenAI 호환 API를 내놓는 공급자를 미리 설정해 둔 것(preset)이다. 사용자는 키만 넣으면 되고,
주소(base_url)는 미리 채워진다(필요하면 바꿀 수 있다). 모두 OpenAIAdapter로 부른다.

주소·모델 이름은 2026-11 기준 공개 값(대표 모델)이다. 모델은 자주 바뀌므로 화면의 '연결 테스트'로
키에 맞는 실제 모델 목록을 공급자에서 불러와 고를 수 있다(llm/probe.py).
단가는 engine/pricing.py에 아는 것만 적고, 모르는 모델은 0(비용 미집계)으로 둔다.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class PresetModel:
    model: str
    label: str
    vision: bool = False
    json: bool = True
    # 도구 호출(에이전트·빌더)을 지원하는지. 자동 전환 때 도구가 필요한 호출은 지원하는 모델로만 넘어간다
    tools: bool = True


@dataclass(frozen=True)
class Preset:
    key: str
    name: str
    group: str  # 화면 묶음: 기본 | 해외 | 국내 | 오픈 모델 호스팅 | 직접 입력
    base_url: str | None
    models: tuple[PresetModel, ...] = field(default_factory=tuple)
    note: str = ""
    # 전용 어댑터를 쓰는 기본 공급자인지(아니면 OpenAI 호환 preset)
    native: bool = False
    # 주소를 꼭 사용자에게 받아야 하는지(Azure·직접 입력)
    needs_base_url: bool = False
    embedding: bool = False
    # v0.9: 지식 검색 '재정렬 전용' 모델 공급자(대화·임베딩에는 쓰지 않는다)
    rerank: bool = False

    @property
    def default_model(self) -> str:
        return self.models[0].model if self.models else ""

    def describe(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "name": self.name,
            "group": self.group,
            "base_url": self.base_url,
            "default_model": self.default_model,
            "models": [
                {"model": m.model, "label": m.label, "vision": m.vision, "json": m.json}
                for m in self.models
            ],
            "note": self.note,
            "native": self.native,
            "needs_base_url": self.needs_base_url,
            "embedding": self.embedding,
            "image": self.key in IMAGE_PROVIDERS,
            "image_models": list(IMAGE_PROVIDERS.get(self.key, ())),
            "rerank": self.rerank,
            "vision": any(m.vision for m in self.models),
        }


M = PresetModel

_LIST: tuple[Preset, ...] = (
    # ---- 기본(전용 어댑터) ----
    Preset(
        "openai",
        "OpenAI (GPT)",
        "기본",
        None,
        (
            M("gpt-5.4-mini", "GPT-5.4 mini (기본 추천·빠르고 저렴)", vision=True),
            M("gpt-5.5", "GPT-5.5 (최상위)", vision=True),
            M("gpt-5.4", "GPT-5.4", vision=True),
            M("gpt-5", "GPT-5", vision=True),
            M("gpt-5-mini", "GPT-5 mini", vision=True),
            M("gpt-5-nano", "GPT-5 nano (가장 저렴)", vision=True),
            M("o4-mini", "o4-mini (추론)", vision=True),
            M("o3", "o3 (추론)", vision=True),
            M("gpt-4.1", "GPT-4.1", vision=True),
            M("gpt-4.1-mini", "GPT-4.1 mini", vision=True),
            M("gpt-4o", "GPT-4o", vision=True),
            M("gpt-4o-mini", "GPT-4o mini", vision=True),
        ),
        native=True,
        embedding=True,
    ),
    Preset(
        "anthropic",
        "Anthropic (Claude)",
        "기본",
        None,
        (
            M("claude-sonnet-5-5", "Claude Sonnet 5.5 (기본 추천)", vision=True),
            M("claude-haiku-5-5", "Claude Haiku 5.5 (빠르고 저렴)", vision=True),
            M("claude-opus-5-5", "Claude Opus 5.5", vision=True),
            M("claude-fable-5-1", "Claude Fable 5.1 (가장 똑똑함)", vision=True),
        ),
        native=True,
    ),
    Preset(
        "google",
        "Google (Gemini)",
        "기본",
        None,
        (
            M("gemini-2.5-flash", "Gemini 2.5 Flash (기본 추천·빠르고 저렴)", vision=True),
            M("gemini-3.1-pro-preview", "Gemini 3.1 Pro (미리 보기)", vision=True),
            M("gemini-3-flash-preview", "Gemini 3 Flash (미리 보기)", vision=True),
            M("gemini-3.1-flash-lite", "Gemini 3.1 Flash-Lite", vision=True),
            M("gemini-2.5-pro", "Gemini 2.5 Pro", vision=True),
            M("gemini-2.5-flash-lite", "Gemini 2.5 Flash-Lite", vision=True),
            M("gemini-2.0-flash", "Gemini 2.0 Flash", vision=True),
        ),
        native=True,
    ),
    Preset(
        "azure",
        "Azure OpenAI",
        "기본",
        None,
        (M("gpt-4o-mini", "배포 이름을 넣으세요", vision=True),),
        note="모델 칸에는 Azure에서 만든 '배포 이름'을 넣어요.",
        native=True,
        needs_base_url=True,
        embedding=True,
    ),
    Preset(
        "openai-compatible",
        "OpenAI 호환 (직접 입력)",
        "직접 입력",
        None,
        (),
        note="vLLM·Ollama·LM Studio 같은 사내 서버나 목록에 없는 공급자의 주소를 직접 넣어요.",
        native=True,
        needs_base_url=True,
        embedding=True,
    ),
    # ---- 해외 공급자(OpenAI 호환) ----
    Preset(
        "deepseek",
        "DeepSeek",
        "해외",
        "https://api.deepseek.com/v1",
        (M("deepseek-chat", "DeepSeek Chat"), M("deepseek-reasoner", "DeepSeek Reasoner")),
    ),
    Preset(
        "mistral",
        "Mistral AI",
        "해외",
        "https://api.mistral.ai/v1",
        (
            M("mistral-large-latest", "Mistral Large"),
            M("mistral-small-latest", "Mistral Small"),
            M("pixtral-large-latest", "Pixtral Large (이미지)", vision=True),
        ),
    ),
    Preset(
        "xai",
        "xAI (Grok)",
        "해외",
        "https://api.x.ai/v1",
        (M("grok-3", "Grok 3"), M("grok-3-mini", "Grok 3 mini")),
    ),
    Preset(
        "perplexity",
        "Perplexity (검색형)",
        "해외",
        "https://api.perplexity.ai",
        (
            M("sonar", "Sonar", json=False, tools=False),
            M("sonar-pro", "Sonar Pro", json=False, tools=False),
        ),
        note="웹 검색을 곁들여 답해요. 출력 형식(JSON)은 지원이 제한적이에요.",
    ),
    Preset(
        "cohere",
        "Cohere (Command)",
        "해외",
        "https://api.cohere.ai/compatibility/v1",
        (M("command-a-03-2025", "Command A"), M("command-r-plus", "Command R+")),
    ),
    Preset(
        "openrouter",
        "OpenRouter (여러 모델 중계)",
        "해외",
        "https://openrouter.ai/api/v1",
        (
            M("openrouter/auto", "자동 선택"),
            M("openai/gpt-4o-mini", "GPT-4o mini (중계)", vision=True),
            M("anthropic/claude-sonnet-5-5", "Claude Sonnet 5.5 (중계)", vision=True),
        ),
        note="키 하나로 여러 회사 모델을 '회사/모델' 이름으로 불러요.",
    ),
    Preset(
        "moonshot",
        "Moonshot (Kimi)",
        "해외",
        "https://api.moonshot.ai/v1",
        (M("kimi-latest", "Kimi"), M("moonshot-v1-32k", "Moonshot v1 32k")),
    ),
    Preset(
        "qwen",
        "Alibaba Qwen (DashScope)",
        "해외",
        "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        (
            M("qwen-plus", "Qwen Plus"),
            M("qwen-max", "Qwen Max"),
            M("qwen-vl-max", "Qwen VL Max (이미지)", vision=True),
        ),
    ),
    Preset(
        "zhipu",
        "Zhipu (GLM)",
        "해외",
        "https://open.bigmodel.cn/api/paas/v4",
        (
            M("glm-4-plus", "GLM-4 Plus"),
            M("glm-4-flash", "GLM-4 Flash"),
            M("glm-4v-plus", "GLM-4V Plus (이미지)", vision=True),
        ),
    ),
    # ---- 국내 ----
    Preset(
        "upstage",
        "Upstage (Solar)",
        "국내",
        "https://api.upstage.ai/v1",
        (M("solar-pro", "Solar Pro"), M("solar-mini", "Solar Mini")),
        note="한국어에 강한 국내 모델이에요.",
    ),
    Preset(
        "hyperclova",
        "네이버 HyperCLOVA X (CLOVA Studio)",
        "국내",
        "https://clovastudio.stream.ntruss.com/v1/openai",
        (M("HCX-005", "HCX-005", vision=True), M("HCX-DASH-002", "HCX-DASH-002 (가벼움)")),
        note="CLOVA Studio의 OpenAI 호환 API 주소예요. 키는 CLOVA Studio에서 발급한 API 키를 넣어요.",
    ),
    # ---- 재정렬 전용(v0.9): 검색 결과를 질문과의 관련도로 다시 줄 세우는 모델 ----
    Preset(
        "cohere-rerank",
        "Cohere Rerank",
        "재정렬 전용",
        "https://api.cohere.com",
        (
            M("rerank-v3.5", "Rerank 3.5 (다국어, 추천)"),
            M("rerank-multilingual-v3.0", "Rerank 다국어 3.0"),
        ),
        note="지식 검색 결과를 다시 줄 세우는 전용 모델이에요. 대화에는 쓰지 않아요.",
        native=True,
        rerank=True,
    ),
    Preset(
        "jina-rerank",
        "Jina Reranker",
        "재정렬 전용",
        "https://api.jina.ai",
        (M("jina-reranker-v2-base-multilingual", "Jina Reranker v2 (다국어)"),),
        note="지식 검색 결과를 다시 줄 세우는 전용 모델이에요. 대화에는 쓰지 않아요.",
        native=True,
        rerank=True,
    ),
    Preset(
        "voyage-rerank",
        "Voyage Rerank",
        "재정렬 전용",
        "https://api.voyageai.com",
        (M("rerank-2.5", "Rerank 2.5"), M("rerank-2", "Rerank 2")),
        note="지식 검색 결과를 다시 줄 세우는 전용 모델이에요. 대화에는 쓰지 않아요.",
        native=True,
        rerank=True,
    ),
    Preset(
        "rerank-compatible",
        "재정렬 호환 서버 (직접 입력)",
        "재정렬 전용",
        None,
        (),
        note="Cohere 형식의 /rerank 주소를 내놓는 서버(vLLM·TEI·사내 서버)의 주소와 모델 이름을 직접 넣어요.",
        native=True,
        needs_base_url=True,
        rerank=True,
    ),
    # ---- 오픈 모델 호스팅 ----
    Preset(
        "groq",
        "Groq (아주 빠름)",
        "오픈 모델 호스팅",
        "https://api.groq.com/openai/v1",
        (
            M("llama-3.3-70b-versatile", "Llama 3.3 70B"),
            M("llama-3.1-8b-instant", "Llama 3.1 8B (가벼움)"),
        ),
    ),
    Preset(
        "together",
        "Together AI",
        "오픈 모델 호스팅",
        "https://api.together.xyz/v1",
        (
            M("meta-llama/Llama-3.3-70B-Instruct-Turbo", "Llama 3.3 70B Turbo"),
            M("Qwen/Qwen2.5-72B-Instruct-Turbo", "Qwen 2.5 72B Turbo"),
        ),
    ),
    Preset(
        "fireworks",
        "Fireworks AI",
        "오픈 모델 호스팅",
        "https://api.fireworks.ai/inference/v1",
        (M("accounts/fireworks/models/llama-v3p3-70b-instruct", "Llama 3.3 70B"),),
    ),
    Preset(
        "nvidia",
        "NVIDIA NIM",
        "오픈 모델 호스팅",
        "https://integrate.api.nvidia.com/v1",
        (M("meta/llama-3.3-70b-instruct", "Llama 3.3 70B"),),
    ),
    Preset(
        "cerebras",
        "Cerebras",
        "오픈 모델 호스팅",
        "https://api.cerebras.ai/v1",
        (M("llama-3.3-70b", "Llama 3.3 70B"),),
    ),
    Preset(
        "sambanova",
        "SambaNova",
        "오픈 모델 호스팅",
        "https://api.sambanova.ai/v1",
        (M("Meta-Llama-3.3-70B-Instruct", "Llama 3.3 70B"),),
    ),
    Preset(
        "siliconflow",
        "SiliconFlow",
        "오픈 모델 호스팅",
        "https://api.siliconflow.com/v1",
        (M("Qwen/Qwen2.5-72B-Instruct", "Qwen 2.5 72B"),),
    ),
)

PRESETS: dict[str, Preset] = {p.key: p for p in _LIST}
NATIVE_KEYS = tuple(p.key for p in _LIST if p.native)
COMPAT_KEYS = tuple(p.key for p in _LIST if not p.native)
GROUP_ORDER = ("기본", "국내", "해외", "오픈 모델 호스팅", "재정렬 전용", "직접 입력")
RERANK_KEYS = tuple(p.key for p in _LIST if p.rerank)


def is_rerank(provider: str) -> bool:
    """재정렬 전용 공급자(대화·임베딩 연결로는 고를 수 없다)인지."""
    return provider in RERANK_KEYS


# 이미지 만들기(v0.9)를 지원하는 공급자와 대표 이미지 모델(앞이 기본). 모델 이름은 자주 바뀌므로
# 단계 설정에서 직접 적을 수 있다. 빈 목록 = 지원하지만 모델 이름(배포 이름 등)을 직접 적어야 한다.
IMAGE_PROVIDERS: dict[str, tuple[str, ...]] = {
    "openai": ("gpt-image-1", "dall-e-3"),
    "azure": (),
    "openai-compatible": (),
    "xai": ("grok-2-image",),
    "together": ("black-forest-labs/FLUX.1-schnell",),
}


def image_capable(provider: str) -> bool:
    return provider in IMAGE_PROVIDERS


def default_image_model(provider: str) -> str:
    """대표 이미지 모델(없으면 빈 글 — 사용자가 직접 적어야 한다)."""
    models = IMAGE_PROVIDERS.get(provider, ())
    return models[0] if models else ""


def provider_list() -> list[dict[str, Any]]:
    order = {g: i for i, g in enumerate(GROUP_ORDER)}
    return [p.describe() for p in sorted(_LIST, key=lambda p: order.get(p.group, 99))]


def preset_base_url(key: str) -> str | None:
    p = PRESETS.get(key)
    return p.base_url if p and not p.native else None


def _model(provider: str, model: str) -> PresetModel | None:
    p = PRESETS.get(provider)
    if p is None:
        return None
    return next((m for m in p.models if m.model == model), None)


def model_supports_json(provider: str, model: str) -> bool:
    """출력 형식(JSON)을 지원하는지. 목록에 없는 모델은 지원한다고 본다."""
    m = _model(provider, model)
    return True if m is None else m.json


def provider_supports_tools(provider: str, model: str) -> bool:
    """도구 호출(에이전트·빌더)이 되는지. Google 어댑터는 아직 도구 대화를 지원하지 않는다."""
    if provider == "google" or is_rerank(provider):
        return False
    m = _model(provider, model)
    return True if m is None else m.tools


def model_supports_vision(provider: str, model: str) -> bool | None:
    """목록에 있는 모델이면 이미지 지원 여부, 모르면 None."""
    p = PRESETS.get(provider)
    if p is None:
        return None
    for m in p.models:
        if m.model == model:
            return m.vision
    return None
