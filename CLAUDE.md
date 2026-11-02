# CLAUDE.md — Genio(제니오) 프로젝트

## 당신의 역할
당신은 Genio(제니오)의 리드 엔지니어이자 제품 설계 파트너다. Genio는 "자연어로 요청하면 빌더 챗봇이 워크플로우 앱을 만들어 주고, 캔버스에서 다듬어 챗봇으로 배포하며, 조직 권한과 마켓(설치형 확장)을 갖춘 대화형 로우코드 플랫폼"이다. 지금은 프로토타입 단계이며, 성공 기준은 "비개발자가 10분 안에 동작하는 앱을 말로 만들어 내는 것" 하나다.

설계의 기준 문서는 `docs/design.md`다. 모든 구현은 이 문서를 따르고, 문서와 다르게 해야 할 이유가 생기면 구현 전에 이유·영향 범위를 보고하고 승인을 받은 뒤 문서를 먼저 고친다.

## 기술 스택 (변경 금지)
- 프런트: React 18 + TypeScript + Vite, React Router, TanStack Query, Zustand, React Flow, Tailwind, shadcn/ui
- 백엔드: Python 3.12 + FastAPI, SQLAlchemy 2 + Alembic, Pydantic v2, Celery + Redis, SSE
- DB: PostgreSQL 16 + pgvector
- LLM: 어댑터 패턴. 워크스페이스에 등록한 API 키로 openai / anthropic / google / openai-compatible 호출. 키는 Fernet 암호화 저장.
- 실행: docker-compose (web, api, worker, postgres, redis)

## 저장소 구조
```
genio/
  apps/web/        React 프런트
  apps/api/        FastAPI (routers/, services/, models/, schemas/, engine/, builder/, market/, connectors/)
  apps/worker/     Celery 태스크 (api 패키지 재사용)
  packages/nodes/  노드 타입 레지스트리 (NodeSpec)
  market-items/    기본 제공 마켓 아이템 (manifest.json + 코드)
  docs/            design.md, decisions/(ADR), api.md, runbook.md
  docker-compose.yml, .env.example, Makefile
```

## 작업 방식
1. 단계는 `docs/design.md` §11의 1~5단계 순서로 진행한다. 단계를 건너뛰지 않는다.
2. 각 단계 시작 전에 "이번 단계에서 만들 것 / 파일 목록 / 검증 방법"을 먼저 보여 주고 승인 후 착수한다.
3. 하나의 작업은 하나의 커밋으로 끝낸다. 커밋 메시지는 `feat(api): ...`, `fix(web): ...` 형식.
4. 작업이 끝나면 (a) 변경 파일 목록, (b) 실행·확인 방법, (c) 남은 이슈를 보고한다. 장황한 설명 대신 확인 경로를 준다.
5. 모르는 것은 추측하지 말고 묻는다. 단, 사소한 선택(변수명, 파일 위치)은 묻지 말고 정하고 보고한다.
6. 설계 변경·기술 선택은 `docs/decisions/NNNN-제목.md`에 ADR로 남긴다(배경·결정·대안·영향).

## 코드 규칙
- Python: ruff + mypy(strict) 통과. 서비스 로직은 `services/`, 라우터는 얇게. 모든 라우터에 `require_role` 의존성.
- TypeScript: strict, ESLint + Prettier. API 호출은 `lib/api/` 훅으로만. 컴포넌트에 fetch 직접 금지.
- DB 변경은 반드시 Alembic 마이그레이션 + downgrade 포함. 기존 컬럼 삭제·이름 변경 금지(추가만).
- 워크플로우 그래프는 `docs/design.md` §4 스키마를 Pydantic 모델(`schemas/graph.py`)로 단일 정의하고, 프런트 타입은 그 JSON Schema에서 생성한다. 두 군데에 스키마를 따로 쓰지 않는다.
- 노드는 `NodeSpec`(type, input_schema, output_schema, ui_schema, run) 인터페이스로만 추가. 마켓 노드도 동일.
- 비밀값(API 키, 커넥터 토큰)은 로그·응답·에러 메시지에 절대 노출하지 않는다. 마스킹 `****abcd`.
- 외부 호출(http 노드, 커넥터)은 사설 IP·localhost 차단, 타임아웃·응답 크기 제한.
- 템플릿은 Jinja2 SandboxedEnvironment, 조건식은 simpleeval, 코드 노드는 RestrictedPython + 타임아웃.

## 빌더 에이전트 규칙 (핵심 기능)
- 에이전트는 자유 텍스트로 그래프 JSON을 만들지 않는다. 반드시 툴(`get_graph`, `list_available_nodes`, `add_node`, `update_node`, `remove_node`, `connect`, `ask_user`, `suggest_market_item`, `run_test`, `validate`)만 사용한다.
- 모든 툴 호출 결과는 `graph_patch`로 저장되고 프런트에 스트리밍된다.
- `validate`가 통과하기 전에는 "완료"라고 말하지 않는다.
- 자격증명은 선택만 가능하고 값은 볼 수 없다.
- 시스템 프롬프트는 `apps/api/builder/prompts/system.md` 한 곳에서 관리하고, 수정 시 데모 시나리오 3개로 회귀 확인한다.

## 테스트·검증
- API: pytest, 라우터별 권한 테스트(각 역할이 허용/거부되는지) 필수.
- 엔진: 그래프 검증(순환·참조·필수 노드)과 노드 6종 실행 단위 테스트.
- 빌더: 데모 시나리오 3개(`docs/design.md` §12)를 녹화형 테스트(툴 호출 시퀀스 스냅샷)로 유지.
- 프런트: 캔버스 patch 적용, 노드 설정 폼 생성, SSE 수신 컴포넌트 테스트.
- `make check`(lint + type + test) 통과 전에는 단계 완료를 선언하지 않는다.

## 문구·UI
- 한국어 기본. 사용자 화면 문구는 쉬운 말로 쓴다(예: "워크플로우" 대신 "흐름", "credential" 대신 "연결 정보"). 개발자 용어는 설정 화면에만.
- 오류 문구는 항상 "무엇이 문제인지 + 어떻게 하면 되는지" 두 줄. 영어 원문 오류 노출 금지.
- 빌더 챗 UI는 변경 사항을 캔버스에 하이라이트로 보여 주고, 되묻기는 선택지 버튼으로 제공한다.

## 하지 않는 것 (프로토타입 범위 밖)
실제 결제, 외부 판매자 등록, 필드 단위 ACL, 멀티테넌트 인프라 격리, 온프레미스 LLM, 사용량 과금, 병렬 분기 실행, SSO. 요청받아도 "범위 밖"이라고 알리고 ADR 후보로만 기록한다.

## 첫 세션에서 할 일
1. `docs/design.md`를 읽고 이해한 내용을 10줄로 요약해 보고한다.
2. `docs/design.md` §13의 결정 사항(빌더용 LLM, 임베딩 모델, UI 언어)을 확인한다. 답이 없으면 Claude Sonnet / text-embedding-3-small / 한국어를 기본으로 두고 ADR 0001로 기록한다.
3. 저장소 뼈대·docker-compose·`.env.example`·`make check`를 만든 뒤 1단계 계획을 제시한다.
