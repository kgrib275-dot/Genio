# ADR 0003. LLM 어댑터 구현 방식과 최신 API 제약 대응

- 상태: 채택
- 날짜: 2026-11-03

## 배경
설계서 §1은 LLM을 어댑터 패턴으로 붙이라고 한다. 노드 `llm`의 그래프 스키마(§4)에는 `temperature`가 있다.
구현 시점의 Anthropic API와 공식 SDK(anthropic 2.x)는 다음 제약이 있다.
- 최신 API 버전은 `temperature`·`top_p`·`top_k`를 보내면 400을 돌려준다. SDK 2.x는 이 인자를 아예 받지 않는다.
- Claude Sonnet 5.5 등 최신 모델은 강제 툴 호출(`tool_choice: any/tool`)을 400으로 거부한다.
- Claude 5 세대는 안전 분류기가 요청을 거절할 수 있고(`stop_reason: refusal`), 공식 API는 거절 시 다른 모델로 넘기는 `fallbacks`를 지원한다.

## 결정
1. **공통 인터페이스**: `complete`(노드용 1회 응답), `chat`(빌더 툴 호출 대화), `embed`(지식베이스) 세 메서드. 공급자별 구현은 `apps/api/llm/`에 둔다.
   - anthropic: 공식 SDK. `chat`은 스트리밍(`messages.stream`)으로 글자 단위 전송.
   - openai, openai-compatible: 공식 SDK. `chat`은 비스트리밍(한 번에 전송).
   - google: REST(generateContent)로 `complete`만. 빌더·임베딩은 안내 문구와 함께 거부.
2. **temperature**: 그래프에는 그대로 두고(설계서 스키마 유지), Anthropic 어댑터만 보내지 않는다. OpenAI는 보내되 모델이 거부하면 빼고 한 번 더 보낸다.
3. **툴 선택**: 빌더는 `tool_choice`를 지정하지 않는다(auto). 툴을 쓰게 하는 것은 시스템 프롬프트가 맡는다.
4. **거절 대비**: 공식 엔드포인트(base_url 없음)로 Claude 5 세대를 부를 때 `betas=["server-side-fallback-2026-07-01"]`, `fallbacks="default"`를 켠다. 그래도 거절되면 한국어 오류로 바꾼다.
5. **effort**: 노드(분류·요약 등 단순 작업)는 `low`, 빌더는 `medium`. Claude 5 세대에만 보낸다.
6. **빌더 대화 맥락**: 한 차례 안에서는 공급자 원본 블록(생각 블록 포함)을 바꾸지 않고 되돌려 보낸다. 이전 차례는 텍스트 요약(한 일·질문·제안·테스트 결과)으로만 넘긴다. 지난 툴 블록을 다시 보내지 않아 기록 편집 검사와 충돌하지 않고, 공급자를 바꿔도 대화가 이어진다.
7. **툴 입력 스트리밍**: 스트리밍 요청의 툴에 `eager_input_streaming: true`를 켜고, 실행 전 JSON Schema로 입력을 다시 검증한다. 잘린 입력(max_tokens)은 실행하지 않고 오류 결과로 돌려준다.
8. **오류 문구**: 공급자 원문 오류·키는 절대 내보내지 않고 "무엇이 문제 + 어떻게" 두 줄로 바꾼다.

## 대안
- 공급자 SDK 대신 LiteLLM 같은 통합 라이브러리: 의존성이 크고, 최신 파라미터(fallbacks 등) 반영이 늦을 수 있다.
- 빌더 맥락에 지난 툴 블록까지 모두 다시 보내기: 토큰이 늘고, 공급자 전환·기록 편집 시 오류 위험이 커진다.

## 영향
- 노드 설정의 "창의성(temperature)"은 Anthropic 모델에서 효과가 없다. 화면 안내 문구는 추후 보완(남은 이슈).
- 실제 키로의 호출은 이 PC에 키가 없어 확인하지 못했다. 요청 형식·스트림 해석은 SDK 전송 계층 모의 테스트(`tests/test_llm_adapters.py`)로 확인했다.
