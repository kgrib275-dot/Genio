# 대화형 로우코드 챗봇 플랫폼 — 프로토타입 설계서 (v0.1)

## 0. 목표와 범위
- 목표: 비개발자가 자연어로 요청하면 빌더 챗봇이 워크플로우 앱을 만들어 주고, 사용자는 캔버스에서 확인·수정 후 챗봇으로 배포한다. 조직 단위 권한 관리와 마켓(설치형 확장)을 포함한다.
- 프로토타입 성공 기준: 비개발자가 "고객 문의 메일을 분류해서 슬랙으로 보내 줘" 수준의 요청을 10분 안에 동작하는 앱으로 만든다.
- 범위 제외: 실제 결제, 외부 판매자 등록, 필드 단위 ACL, 멀티테넌트 인프라 격리, 온프레미스 LLM, 사용량 과금.

## 1. 기술 스택
- 프런트: React 18 + TypeScript + Vite, React Router, TanStack Query, Zustand(캔버스 상태), React Flow(캔버스), Tailwind, shadcn/ui, Monaco(코드 노드 편집)
- 백엔드: Python 3.12 + FastAPI, SQLAlchemy 2 + Alembic, Pydantic v2, httpx, Celery + Redis(워크플로우 실행 큐), SSE(실행 로그·챗 스트리밍)
- DB: PostgreSQL 16 + pgvector(지식베이스 임베딩)
- LLM: 어댑터 패턴. 워크스페이스 설정에서 provider(openai / anthropic / google / openai-compatible)와 API 키를 등록. 키는 서버 암호화 저장(Fernet, 키는 환경변수).
- 인증: 이메일+비밀번호(bcrypt) + JWT(access 15분, refresh 7일). 프로토타입이라 SSO 없음(인터페이스만 남김).
- 배포: docker-compose(api, worker, web, postgres, redis). 환경변수는 `.env.example`로 관리.

## 2. 시스템 구성
```
[Web(React)] ──REST/SSE──> [API(FastAPI)] ──> [PostgreSQL + pgvector]
                                 │                     ▲
                                 ├──> [Redis] <──> [Worker(Celery)] ── 워크플로우 실행·임베딩·마켓 설치
                                 └──> [LLM Adapter] ──> OpenAI / Anthropic / Google / 호환 API
[배포된 챗봇 위젯] ──> /public/apps/{slug}/chat (API 키 없이 공개 토큰)
```
- API는 상태 없음. 실행은 전부 Worker. 실행 상태는 DB(run, run_step)에 기록하고 SSE로 전달.
- 코드 실행 노드는 Worker 안의 제한 실행(RestrictedPython + 타임아웃 10초 + 네트워크 차단). 정식 버전에서 컨테이너 샌드박스로 교체 가능하도록 `CodeRunner` 인터페이스로 분리.

## 3. 도메인 모델 (PostgreSQL)

### 3-1. 조직·권한
- `organizations` (id, name, slug, created_at)
- `workspaces` (id, org_id, name, slug, settings jsonb) — 프로토타입은 조직당 1개로 시작하되 테이블은 분리
- `users` (id, email, password_hash, name, created_at)
- `memberships` (id, user_id, workspace_id, role) — role ∈ {owner, admin, builder, operator, member}
- `invitations` (id, workspace_id, email, role, token, expires_at, accepted_at)

역할 권한표:
| 기능 | owner | admin | builder | operator | member |
|---|---|---|---|---|---|
| 멤버 초대·역할 변경 | ○ | ○ | | | |
| LLM 키·커넥터 자격증명 관리 | ○ | ○ | | | |
| 마켓 설치·제거 | ○ | ○ | | | |
| 앱 생성·편집·삭제 | ○ | ○ | ○ | | |
| 앱 배포·배포 대상 지정 | ○ | ○ | ○ | | |
| 실행 로그·비용 조회 | ○ | ○ | ○ | ○ | |
| 배포된 앱 사용 | ○ | ○ | ○ | ○ | ○(배포 대상일 때) |

### 3-2. 앱·워크플로우
- `apps` (id, workspace_id, name, slug, type ∈ {chat, workflow, form}, description, icon, status ∈ {draft, published}, created_by, updated_at)
- `workflow_versions` (id, app_id, version, graph jsonb, created_by, created_at, note) — graph는 §4 스키마. 앱당 여러 버전, 배포는 특정 버전을 가리킴
- `deployments` (id, app_id, version_id, channel ∈ {web_widget, share_link, api}, public_token, access ∈ {workspace, roles, public}, allowed_roles text[], created_at)
- `runs` (id, app_id, version_id, trigger ∈ {test, chat, api, schedule}, status ∈ {queued, running, succeeded, failed, waiting_approval}, input jsonb, output jsonb, error text, started_at, finished_at, token_usage jsonb, cost numeric)
- `run_steps` (id, run_id, node_id, status, input jsonb, output jsonb, logs text, started_at, finished_at)
- (ADR 0002 추가) `apps.draft_graph jsonb` 편집 중 작업본, `runs.graph_snapshot jsonb`·`runs.approval jsonb`·`runs.context jsonb` 추가, `runs.version_id` nullable(작업본 테스트 실행)
- `conversations` (id, app_id, deployment_id, user_id nullable, external_session_id, created_at)
- `messages` (id, conversation_id, role ∈ {user, assistant, system}, content text, run_id, created_at)

### 3-3. 지식베이스
- `knowledge_bases` (id, workspace_id, name, embedding_model, chunk_size, created_at)
- `documents` (id, kb_id, filename, mime, size, status ∈ {uploaded, processing, ready, failed}, created_at)
- `chunks` (id, document_id, kb_id, content text, embedding vector(1536), metadata jsonb) — ivfflat 인덱스

### 3-4. 커넥터
- `connector_definitions` (id, key, name, version, source ∈ {builtin, market}, manifest jsonb) — 커넥터의 스펙(인증 방식, 제공 액션 목록, 각 액션의 입출력 스키마)
- `connector_credentials` (id, workspace_id, definition_id, name, secret_encrypted bytea, created_by) — 워크스페이스 귀속. 빌더는 목록만 보고 선택, 값은 못 봄

### 3-5. 빌더 챗
- `builder_sessions` (id, app_id, user_id, created_at)
- `builder_messages` (id, session_id, role, content text, graph_patch jsonb nullable, created_at) — 어시스턴트 메시지는 설명 텍스트 + 그래프 변경(patch)을 함께 가짐

### 3-6. 마켓
- `market_items` (id, key, type ∈ {template, node, connector, prompt_pack}, name, summary, description_md, version, publisher, price integer, manifest jsonb, bundle_url, tags text[], installs integer, created_at)
- `installations` (id, workspace_id, item_id, version, installed_by, installed_at, status ∈ {installed, disabled})
- `purchases` (id, workspace_id, item_id, amount, status ∈ {mock_paid}, created_at) — 프로토타입은 결제 없이 mock_paid

### 3-7. 공통
- `audit_logs` (id, workspace_id, user_id, action, target_type, target_id, meta jsonb, created_at)
- `llm_providers` (id, workspace_id, provider, label, api_key_encrypted, base_url, default_model, is_default)

## 4. 워크플로우 그래프 스키마 (jsonb)
```json
{
  "version": 1,
  "nodes": [
    {"id": "n1", "type": "input", "position": {"x":0,"y":0},
     "data": {"label": "사용자 입력", "fields": [{"key":"message","type":"text","required":true}]}},
    {"id": "n2", "type": "llm", "position": {"x":300,"y":0},
     "data": {"label": "분류", "provider": "default", "model": "gpt-4o-mini", "temperature": 0.2,
              "system": "문의를 billing/tech/other 중 하나로 분류", "prompt": "{{n1.message}}",
              "output_schema": {"type":"object","properties":{"category":{"type":"string"}}}}},
    {"id": "n3", "type": "condition", "position": {"x":600,"y":0},
     "data": {"cases": [{"id":"c1","when":"{{n2.category}} == 'billing'"},{"id":"c2","when":"{{n2.category}} == 'tech'"}], "else": "c_else"}},
    {"id": "n4", "type": "connector", "position": {"x":900,"y":-100},
     "data": {"connector": "slack", "credential_id": "…", "action": "post_message",
              "params": {"channel": "#billing", "text": "{{n1.message}}"}}},
    {"id": "n9", "type": "output", "position": {"x":1200,"y":0}, "data": {"template": "분류: {{n2.category}}"}}
  ],
  "edges": [
    {"id":"e1","source":"n1","target":"n2"},
    {"id":"e2","source":"n2","target":"n3"},
    {"id":"e3","source":"n3","sourceHandle":"c1","target":"n4"},
    {"id":"e4","source":"n4","target":"n9"}
  ],
  "variables": {}
}
```
- 템플릿 표현식: `{{nodeId.field}}` (Jinja2 sandbox). 조건식은 안전한 소형 평가기(simpleeval).
- 노드 타입(1차): `input`, `llm`, `condition`, `http`, `knowledge_search`, `code`, `connector`, `approval`(사람 승인 대기), `output`. 각 타입은 `NodeSpec`(입력 스키마, 출력 스키마, UI 폼 정의, 실행 함수)으로 등록. 마켓 노드도 같은 인터페이스로 등록.
- 유효성 검사: 그래프 저장 시 순환 없음, input 1개·output ≥1개, 모든 참조 변수 존재, 커넥터 credential 존재 여부 검사. 오류는 노드별로 반환해 캔버스에 표시.

## 5. 실행 엔진 (Worker)
- 위상 정렬 후 순차 실행. condition은 선택된 분기만 실행. 병렬 분기는 1차에서 미지원(설계상 edges로 표현 가능하게 유지).
- 각 노드 실행 → `run_steps` 기록 → Redis pub/sub → API가 SSE로 클라이언트 전송.
- `approval` 노드: run을 `waiting_approval`로 두고 승인 링크 생성. 승인 시 재개.
- 재시도: http·connector 노드는 지수 백오프 2회. LLM 노드는 output_schema가 있으면 JSON 파싱 실패 시 1회 재요청.
- 비용: LLM 응답의 토큰 수 × 모델 단가표(설정 파일)로 run.cost 계산.
- 타임아웃: 노드 60초, run 10분.

## 6. 빌더 에이전트 (핵심)
### 6-1. 동작 원리
- LLM에 "도구 사용" 방식으로 그래프를 조작하게 한다. 자유 텍스트로 JSON을 뱉게 하지 않고, 아래 툴만 호출하게 해서 항상 유효한 그래프를 유지한다.
  - `get_graph()` 현재 그래프 조회
  - `list_available_nodes()` 설치된 노드 타입·커넥터·지식베이스 목록(마켓 설치분 포함)
  - `add_node(type, data, after?)`, `update_node(id, data)`, `remove_node(id)`, `connect(source, target, handle?)`
  - `ask_user(question, options?)` 빠진 정보 되묻기
  - `suggest_market_item(type, reason)` 필요한 커넥터·노드가 없을 때 마켓 제안
  - `run_test(input)` 테스트 실행 후 결과 요약 반환
  - `validate()` 그래프 검증 결과
- 시스템 프롬프트: 역할(로우코드 빌더), 노드 카탈로그 요약, 규칙(한 번에 하나의 목표, 변경 전 설명, 자격증명은 선택만 가능, 검증 통과 전 완료 선언 금지).
- 대화 턴마다 호출된 툴의 결과로 `graph_patch`를 만들어 `builder_messages`에 저장하고, 프런트는 patch를 캔버스에 애니메이션으로 반영.
- 컨텍스트: 최근 20턴 + 현재 그래프 요약(노드 id·type·label만) + 앱 설명.

### 6-2. 대화 흐름 예시
1. 사용자: "문의 메일을 분류해서 담당자 슬랙으로 보내 줘"
2. 빌더: `list_available_nodes` → 슬랙 커넥터 없음 → `suggest_market_item("connector","slack")` + "슬랙 커넥터를 설치할까요?"
3. 사용자: "응" → 프런트가 설치 API 호출 → 빌더에 "installed" 이벤트 전달
4. 빌더: `add_node(input)`, `add_node(llm, 분류)`, `add_node(condition)`, `add_node(connector slack)` ×2, `connect` … → "분류 기준을 billing/tech/other로 잡았어요. 채널은 어디로 보낼까요?" (`ask_user`)
5. 사용자: "빌링은 #billing, 기술은 #tech"
6. 빌더: `update_node` → `validate` → `run_test({"message":"결제가 두 번 됐어요"})` → "테스트 결과 billing으로 분류돼 #billing에 전송됐어요. 배포할까요?"

### 6-3. 수정 대화
- "두 번째 노드 온도 낮춰 줘", "조건 하나 더 추가해 줘" 같은 요청은 `get_graph` 후 해당 노드를 찾아 `update_node`. 노드 라벨·순서로 지칭 가능하게 그래프 요약에 순번 포함.

## 7. API 설계 (FastAPI, prefix /api/v1)
### 인증·조직
- `POST /auth/signup`, `POST /auth/login`, `POST /auth/refresh`
- `GET /me`, `GET /workspaces/{ws}/members`, `POST /workspaces/{ws}/invitations`, `PATCH /workspaces/{ws}/members/{id}`
### 설정
- `GET/POST/DELETE /workspaces/{ws}/llm-providers`
- `GET/POST/DELETE /workspaces/{ws}/connectors/credentials`
- `GET /workspaces/{ws}/connectors/definitions`
### 앱·워크플로우
- `GET/POST /workspaces/{ws}/apps`, `GET/PATCH/DELETE /apps/{id}`
- `GET /apps/{id}/versions`, `POST /apps/{id}/versions` (graph 저장 → 검증 → 새 버전)
- `POST /apps/{id}/validate`
- `POST /apps/{id}/runs` (테스트 실행) → `GET /runs/{id}`, `GET /runs/{id}/events` (SSE)
- `POST /runs/{id}/approve`
### 빌더
- `POST /apps/{id}/builder/sessions`, `GET /builder/sessions/{id}/messages`
- `POST /builder/sessions/{id}/messages` (SSE 스트리밍: 텍스트 토큰 + tool_call 이벤트 + graph_patch)
### 지식베이스
- `GET/POST /workspaces/{ws}/knowledge-bases`, `POST /knowledge-bases/{id}/documents` (multipart), `GET /knowledge-bases/{id}/documents`, `POST /knowledge-bases/{id}/search` (디버그용)
### 배포·공개
- `POST /apps/{id}/deployments`, `GET /apps/{id}/deployments`, `DELETE /deployments/{id}`
- `POST /public/apps/{token}/chat` (SSE), `GET /public/apps/{token}/widget.js`
### 마켓
- `GET /market/items?type=&q=`, `GET /market/items/{key}`
- `POST /workspaces/{ws}/market/install` {item_key} (mock 결제 → 설치 → 노드/커넥터 등록)
- `DELETE /workspaces/{ws}/market/installations/{id}`
### 운영
- `GET /workspaces/{ws}/runs?app=&status=&from=&to=`, `GET /workspaces/{ws}/usage` (앱별 토큰·비용)
- `GET /workspaces/{ws}/audit-logs`

모든 엔드포인트는 `require_role(ws, [...])` 의존성으로 §3-1 표를 강제. 공개 엔드포인트는 public_token + 속도 제한(IP 분당 30회).

## 8. 마켓 아이템 패키지 규격
```
item/
  manifest.json
  README.md
  node.py          (type=node일 때: NodeSpec 구현)
  connector.py     (type=connector일 때: 액션 구현)
  template.json    (type=template일 때: §4 그래프 + 필요한 KB/커넥터 placeholder)
  prompts.json     (type=prompt_pack)
```
manifest.json:
```json
{"key":"slack","type":"connector","name":"Slack","version":"1.0.0","publisher":"platform",
 "price":0,"requires":{"credentials":[{"key":"bot_token","label":"Bot Token","secret":true}]},
 "actions":[{"key":"post_message","label":"메시지 보내기",
   "input_schema":{"type":"object","properties":{"channel":{"type":"string"},"text":{"type":"string"}},"required":["channel","text"]},
   "output_schema":{"type":"object","properties":{"ts":{"type":"string"}}}}],
 "permissions":["network:slack.com"]}
```
- 설치 = 번들 검증(허용 import 화이트리스트, 네트워크 도메인 선언) → `connector_definitions`/노드 레지스트리 등록 → 빌더 카탈로그 갱신.
- 프로토타입 기본 제공: 커넥터 3개(Slack, Email(SMTP), Google Sheets), 템플릿 5개(문의 분류, FAQ 챗봇(KB), 문서 요약, 일일 보고 생성, 승인 요청 워크플로우), 프롬프트 팩 2개.

## 9. 프런트엔드 구조
```
src/
  app/ (라우터, 레이아웃, 인증 가드)
  pages/
    auth/ (login, signup, invite-accept)
    dashboard/ (앱 목록, 최근 실행)
    apps/[id]/
      builder/   ← 핵심 화면: 좌 빌더 챗(40%) · 우 캔버스(60%) · 하단 실행 로그 패널
      settings/  (배포, 접근 권한, 버전)
      runs/      (실행 이력·스텝 상세)
    knowledge/ (KB 목록·문서 업로드)
    connectors/ (자격증명 관리)
    market/ (목록·상세·설치됨)
    workspace/ (멤버·역할·LLM 키·감사 로그·사용량)
  components/canvas/ (React Flow 노드 컴포넌트 타입별, 노드 설정 사이드 패널(JSON Schema → 폼 자동 생성))
  components/builder-chat/ (메시지, 툴 호출 카드, ask_user 선택지 버튼, market 제안 카드)
  lib/api/ (TanStack Query 훅), lib/sse.ts, store/canvas.ts
public/widget.js (배포용 챗 위젯, iframe 기반)
```
- 캔버스와 빌더 챗은 같은 `graph` 상태(Zustand)를 공유. 빌더 patch 적용 시 변경 노드 하이라이트 2초.
- 노드 설정 패널은 NodeSpec의 `ui_schema`로 자동 생성(react-jsonschema-form).
- 미저장 변경은 로컬에 유지, "버전 저장" 시 서버 검증 → 오류 노드 빨간 테두리.

## 10. 보안 기본
- API 키·커넥터 비밀값은 Fernet 암호화, 로그·응답에 절대 미노출(마스킹 `****abcd`).
- 템플릿 엔진은 sandbox(Jinja2 SandboxedEnvironment), 코드 노드는 RestrictedPython + 타임아웃 + import 제한.
- http 노드는 사설 IP·localhost 호출 차단(SSRF), 응답 1MB 제한.
- 공개 챗 엔드포인트 속도 제한, 프롬프트에 자격증명 주입 금지(커넥터는 credential_id로만 참조).
- 모든 변경 행위 `audit_logs` 기록.

## 11. 구현 단계
1단계 (2주) 기반: 인증·워크스페이스·역할, 앱 CRUD, 그래프 스키마·검증, 노드 6종(input/llm/condition/http/code/output), 실행 엔진·SSE 로그, 캔버스·노드 설정 패널, LLM 어댑터·키 등록.
2단계 (2주) 빌더 챗: 툴 기반 에이전트, graph_patch 스트리밍, ask_user·run_test, 수정 대화, 빌더 세션 저장.
3단계 (1.5주) 지식·커넥터: KB 업로드·청킹·임베딩·검색 노드, 커넥터 프레임워크·자격증명·Slack/Email/Sheets, approval 노드.
4단계 (1.5주) 배포·마켓·운영: 배포(위젯·링크·접근 권한), 공개 챗 API, 마켓 목록·설치·manifest 로딩·템플릿 5개, 실행 이력·사용량·감사 로그 화면.
5단계 (1주) 마감: 데모 시나리오 3개 end-to-end, 회귀 테스트, docker-compose 배포 문서, 데모 데이터 시드.

## 12. 데모 시나리오 (완료 기준)
1. 문의 분류 → 슬랙 전송 (커넥터 마켓 설치 포함)
2. 사내 규정 PDF 올리고 FAQ 챗봇 만들어 공유 링크로 배포, member 역할 계정으로 질문
3. "주간 보고 초안 만들어 줘" → 구글시트 읽기 → LLM 요약 → 승인 노드 → 승인 후 이메일 발송

## 13. 결정 필요 사항
> 결정: ADR 0001(Claude Sonnet / text-embedding-3-small / 한국어). 구현 제약은 ADR 0003, 포트·공유는 ADR 0004.

- LLM 기본 provider(빌더 에이전트용은 툴 호출 품질이 중요하므로 Claude Sonnet 또는 GPT-4o급 권장)
- 임베딩 모델(OpenAI text-embedding-3-small 기본, 한국어 품질 확인)
- 프로토타입 UI 언어(한국어 기본, i18n 키만 준비)
