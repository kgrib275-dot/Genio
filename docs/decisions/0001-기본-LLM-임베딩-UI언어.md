# ADR 0001. 빌더 LLM, 임베딩 모델, UI 언어 기본값

- 상태: 채택
- 날짜: 2026-11-03

## 배경
CLAUDE.md "첫 세션에서 할 일" 2번은 `docs/design.md` §13의 결정 사항을 확인하고, 답이 없으면 기본값을 ADR 0001로 남기라고 한다.
첫 세션에는 `docs/design.md`가 없었다. 이후 받은 설계서 §13은 권장안(Claude Sonnet 또는 GPT-4o급, text-embedding-3-small, 한국어 기본)만 적고 확정하지 않았다. 그래서 아래 기본값을 그대로 채택한다.

## 결정
| 항목 | 기본값 | 설정 키 |
|---|---|---|
| 빌더용 LLM | Anthropic Claude Sonnet (`claude-sonnet-5-5`) | `GENIO_BUILDER_LLM_PROVIDER`, `GENIO_BUILDER_LLM_MODEL` |
| 임베딩 모델 | OpenAI `text-embedding-3-small` (1536차원) | `GENIO_EMBEDDING_PROVIDER`, `GENIO_EMBEDDING_MODEL`, `GENIO_EMBEDDING_DIM` |
| UI 언어 | 한국어 | `GENIO_DEFAULT_LOCALE=ko` |

- 모델 이름은 코드에 박지 않고 환경 변수와 워크스페이스 설정으로만 바꾼다.
- 키는 워크스페이스에 등록하고 Fernet으로 암호화해 저장한다. `.env`에는 키를 두지 않는다.
- pgvector 컬럼 차원은 `GENIO_EMBEDDING_DIM`과 맞춘다. 차원을 바꾸려면 새 컬럼 추가 마이그레이션이 필요하다.

## 대안
- 빌더 LLM을 Opus 계열로: 품질은 높지만 응답 시간과 비용이 커서 "10분 안에 앱 만들기" 목표에 불리할 수 있다. 데모 시나리오 회귀 결과를 보고 다시 판단한다.
- 임베딩을 `text-embedding-3-large`로: 차원(3072)이 커서 저장·검색 비용이 늘어난다.

## 영향
- 빌더 툴 호출은 Anthropic 어댑터를 우선 구현한다. 다른 공급자 어댑터는 같은 인터페이스로 뒤에 붙인다.
- Anthropic 최신 모델은 강제 `tool_choice`(any/tool)를 거부하므로 빌더 루프는 `tool_choice: auto`와 프롬프트 지시로 툴 사용을 유도한다.
- 기본값을 바꾸면 새 ADR로 대체한다. Anthropic API 제약 대응은 ADR 0003.
