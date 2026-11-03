# API 계약 (prefix `/api/v1`)

설계서 §7을 구체화한 계약이다. 백엔드와 프런트는 이 문서를 기준으로 맞춘다.

## 공통
- 인증: `Authorization: Bearer <access_token>`. SSE처럼 헤더를 못 붙이면 `?access_token=` 쿼리도 받는다.
- ID는 모두 UUID 문자열. 시간은 ISO 8601(UTC).
- 오류 응답 형식(모든 4xx/5xx):
  ```json
  {"detail": {"message": "무엇이 문제인지", "hint": "어떻게 하면 되는지", "errors": [{"node_id": "n2", "field": "prompt", "message": "..."}]}}
  ```
  `errors`는 그래프 검증 실패(422)일 때만 있다.
- 역할: `owner | admin | builder | operator | member`. 권한표는 설계서 §3-1.
- SSE 형식: `event: <이름>\ndata: <JSON>\n\n`. 프런트는 fetch 스트림으로 읽는다(`lib/sse.ts`).

## 상태 확인
| 메서드 | 경로 | 권한 | 응답 |
|---|---|---|---|
| GET | `/health` (prefix 없음) | 없음 | `{status, env}` |

## 인증·조직
| 메서드 | 경로 | 권한 | 요청 | 응답 |
|---|---|---|---|---|
| POST | `/auth/signup` | 없음 | `{email, password(8자+), name, workspace_name?}` | `Tokens` (새 조직·워크스페이스의 owner가 됨) |
| POST | `/auth/login` | 없음 | `{email, password}` (이메일 형식 검사 없음) | `Tokens` |
| POST | `/auth/refresh` | 없음 | `{refresh_token}` | `Tokens` |
| GET | `/auth/invitations/{token}` | 없음 | | `{email, role, workspace_name, expired, accepted}` |
| POST | `/auth/invitations/{token}/accept` | 없음 | `{name, password}` | `Tokens` (계정이 있으면 비밀번호 확인 후 멤버 추가) |
| GET | `/me` | 로그인 | | `{id, email, name, workspaces: [{id, name, slug, role}]}` |
| GET | `/workspaces/{ws}/members` | 모든 역할 | | `[{id, user_id, email, name, role}]` (id = membership id) |
| POST | `/workspaces/{ws}/invitations` | owner, admin | `{email, role}` | `{id, email, role, token, expires_at, accept_url}` |
| GET | `/workspaces/{ws}/invitations` | owner, admin | | `[Invitation]` |
| PATCH | `/workspaces/{ws}/members/{id}` | owner, admin | `{role}` | `Member` (마지막 owner는 못 바꿈) |

`Tokens = {access_token, refresh_token, token_type: "bearer"}`

## 설정
| 메서드 | 경로 | 권한 | 요청 | 응답 |
|---|---|---|---|---|
| GET | `/workspaces/{ws}/llm-providers` | owner, admin, builder | | `[LlmProvider]` |
| POST | `/workspaces/{ws}/llm-providers` | owner, admin | `{provider: openai\|anthropic\|google\|openai-compatible, label, api_key, base_url?, default_model, is_default}` | `LlmProvider` |
| DELETE | `/workspaces/{ws}/llm-providers/{id}` | owner, admin | | 204 |
| GET | `/workspaces/{ws}/connectors/definitions` | 모든 역할 | | `[{id, key, name, version, source, manifest}]` (이 워크스페이스에 설치된 것만) |
| GET | `/workspaces/{ws}/connectors/credentials` | owner, admin, builder | | `[ConnectorCredential]` |
| POST | `/workspaces/{ws}/connectors/credentials` | owner, admin | `{connector_key, name, secrets: {bot_token: "..."}}` | `ConnectorCredential` |
| DELETE | `/workspaces/{ws}/connectors/credentials/{id}` | owner, admin | | 204 |

`LlmProvider = {id, provider, label, base_url, default_model, is_default, api_key_masked: "****abcd"}`
`ConnectorCredential = {id, definition_id, connector_key, connector_name, name, created_at, secrets_masked: {bot_token: "****abcd"}}` (값은 절대 안 내려감)

## 노드 카탈로그
| 메서드 | 경로 | 권한 | 응답 |
|---|---|---|---|
| GET | `/workspaces/{ws}/nodes` | 모든 역할 | `[NodeType]` (기본 + 이 워크스페이스에 설치된 마켓 노드) |
| GET | `/schemas/graph` | 없음 | 그래프 JSON Schema (프런트 타입 생성용) |

`NodeType = {type, label, category, description, input_schema, output_schema, ui_schema, source: "builtin"|"market"}`
`ui_schema`의 `ui:widget` 값: `textarea`, `json`, `code`(Monaco), `kb`(지식베이스 선택), `connector`, `credential`, `connectorAction`.

## 앱·워크플로우
| 메서드 | 경로 | 권한 | 요청 | 응답 |
|---|---|---|---|---|
| GET | `/workspaces/{ws}/apps` | 모든 역할 (member는 published만) | | `[App]` |
| POST | `/workspaces/{ws}/apps` | owner, admin, builder | `{name, type: chat\|workflow\|form, description?, icon?, template_key?}` | `AppDetail` |
| GET | `/apps/{id}` | owner, admin, builder, operator | | `AppDetail` |
| PATCH | `/apps/{id}` | owner, admin, builder | `{name?, description?, icon?, type?}` | `AppDetail` |
| DELETE | `/apps/{id}` | owner, admin, builder | | 204 |
| PUT | `/apps/{id}/draft` | owner, admin, builder | `{graph}` | `AppDetail` (형식만 검사, 내용 검증은 안 함) |
| GET | `/apps/{id}/versions` | owner, admin, builder, operator | | `[{id, version, note, created_at, created_by}]` |
| GET | `/apps/{id}/versions/{version}` | owner, admin, builder, operator | | `{id, version, note, created_at, graph}` |
| POST | `/apps/{id}/versions` | owner, admin, builder | `{graph?, note?}` (graph 없으면 작업본) | 201 `Version` / 422 검증 실패(`errors`) |
| POST | `/apps/{id}/validate` | owner, admin, builder | `{graph?}` | `{valid, errors: [{node_id, field, message}]}` |
| POST | `/apps/{id}/runs` | owner, admin, builder | `{input: {...}, version?: number}` (version 없으면 작업본 실행) | 201 `Run` |
| GET | `/apps/{id}/runs` | owner, admin, builder, operator | | `[Run]` 최근 50개 |
| GET | `/runs/{id}` | owner, admin, builder, operator | | `RunDetail` |
| GET | `/runs/{id}/events` | owner, admin, builder, operator | | SSE |
| POST | `/runs/{id}/approve` | 승인 노드의 approver_roles (비면 owner, admin, builder, operator) | `{approved: bool, comment?}` | `RunDetail` |

```
App = {id, workspace_id, name, slug, type, description, icon, status: draft|published, created_by, updated_at, latest_version: number|null}
AppDetail = App + {draft_graph: Graph}
Run = {id, app_id, version_id, trigger, status: queued|running|succeeded|failed|waiting_approval, input, output, error, started_at, finished_at, created_at, token_usage, cost}
RunDetail = Run + {steps: [RunStep], approval: {node_id, message, approver_roles, decided_by?, approved?, comment?} | null, graph: Graph}
RunStep = {id, node_id, status: running|succeeded|failed|skipped|waiting_approval, input, output, logs, started_at, finished_at}  (실행 순서대로 정렬)
Run.output = {text: string, outputs: {node_id: {...}}}
Run.token_usage = {input_tokens, output_tokens}
```

SSE `/runs/{id}/events` 이벤트:
- `run`: `Run` (상태가 바뀔 때마다)
- `step`: `RunStep` (새로 생기거나 바뀔 때마다)
- `end`: `Run` (succeeded/failed/waiting_approval에 도달하면 보내고 스트림 종료)

## 빌더
| 메서드 | 경로 | 권한 | 요청 | 응답 |
|---|---|---|---|---|
| GET | `/apps/{id}/builder/sessions` | owner, admin, builder | | `[{id, app_id, user_id, created_at}]` 최신순 |
| POST | `/apps/{id}/builder/sessions` | owner, admin, builder | | `{id, app_id, user_id, created_at}` |
| GET | `/builder/sessions/{id}/messages` | owner, admin, builder | | `[BuilderMessage]` |
| POST | `/builder/sessions/{id}/messages` | owner, admin, builder | `{content, event?: {type: "installed", item_key}}` | SSE |

`BuilderMessage = {id, role: user|assistant, content, graph_patch: TurnRecord|null, created_at}`
`TurnRecord = {ops: [PatchOp], tool_calls: [{id, name, input, ok, summary}], ask_user?: {question, options}, market_suggestion?: {item, reason}, test_result?: {run_id, status, output, error}}`
`PatchOp` = `{op: "add_node", node}` | `{op: "update_node", id, data}` | `{op: "remove_node", id}` | `{op: "add_edge", edge}` | `{op: "remove_edge", id}`

SSE `/builder/sessions/{id}/messages` 이벤트(순서대로 여러 번):
- `user_message`: `BuilderMessage` (저장된 사용자 메시지)
- `text`: `{delta}` 어시스턴트 문장 조각
- `tool_call`: `{id, name, input}`
- `tool_result`: `{id, name, ok, summary}`
- `graph_patch`: `{ops: [PatchOp], graph: Graph}` (graph = 적용 후 작업본 전체)
- `ask_user`: `{question, options: [string]}` → 프런트는 선택지 버튼으로 표시
- `market_suggestion`: `{item: MarketItem, reason}` → 설치 카드 표시. 설치하면 `event: {type: "installed", item_key}`로 다시 메시지를 보낸다
- `test_result`: `{run_id, status, output, error}`
- `error`: `{message, hint}`
- `done`: `BuilderMessage` (저장된 어시스턴트 메시지)

## 지식베이스
| 메서드 | 경로 | 권한 | 요청 | 응답 |
|---|---|---|---|---|
| GET | `/workspaces/{ws}/knowledge-bases` | owner, admin, builder, operator | | `[KnowledgeBase]` |
| POST | `/workspaces/{ws}/knowledge-bases` | owner, admin, builder | `{name, chunk_size?}` | `KnowledgeBase` |
| DELETE | `/knowledge-bases/{id}` | owner, admin, builder | | 204 |
| POST | `/knowledge-bases/{id}/documents` | owner, admin, builder | multipart `file` (pdf, txt, md) | `Document` |
| GET | `/knowledge-bases/{id}/documents` | owner, admin, builder, operator | | `[Document]` |
| DELETE | `/documents/{id}` | owner, admin, builder | | 204 |
| POST | `/knowledge-bases/{id}/search` | owner, admin, builder | `{query, top_k?}` | `[{chunk_id, document_id, filename, content, score}]` |

`KnowledgeBase = {id, name, embedding_model, chunk_size, created_at, document_count}`
`Document = {id, kb_id, filename, mime, size, status: uploaded|processing|ready|failed, error, created_at, chunk_count}`

## 배포·공개
| 메서드 | 경로 | 권한 | 요청 | 응답 |
|---|---|---|---|---|
| POST | `/apps/{id}/deployments` | owner, admin, builder | `{channel: web_widget\|share_link\|api, access: workspace\|roles\|public, allowed_roles?: [Role], version?: number}` | `Deployment` (version 없으면 최신 버전, 버전이 없으면 422) |
| GET | `/apps/{id}/deployments` | owner, admin, builder, operator | | `[Deployment]` |
| DELETE | `/deployments/{id}` | owner, admin, builder | | 204 |
| GET | `/public/apps/{token}` | 접근 규칙 | | `PublicApp` |
| POST | `/public/apps/{token}/chat` | 접근 규칙 + IP당 분당 30회 | `{message, session_id?, input?}` | SSE |
| GET | `/public/apps/{token}/widget.js` | 없음 | | JavaScript |

`Deployment = {id, app_id, version_id, version, channel, public_token, access, allowed_roles, created_at, share_url, widget_snippet, api_url}`
`PublicApp = {name, description, icon, type, access, requires_login, can_use, input_fields: [{key, label, type, required}]}`

접근 규칙: `public`은 누구나. `workspace`는 로그인한 워크스페이스 멤버. `roles`는 `allowed_roles`에 든 역할의 멤버. 로그인 토큰은 `Authorization` 헤더로 보낸다.

공개 챗 SSE 이벤트:
- `session`: `{session_id}`
- `status`: `{message}` (예: "답을 만들고 있어요")
- `answer`: `{text}`
- `error`: `{message, hint}`
- `done`: `{session_id, run_id, status}`

## 마켓
| 메서드 | 경로 | 권한 | 요청 | 응답 |
|---|---|---|---|---|
| GET | `/market/items?type=&q=&workspace_id=` | 로그인 | | `[MarketItem]` (workspace_id를 주면 `installed` 채움) |
| GET | `/market/items/{key}?workspace_id=` | 로그인 | | `MarketItemDetail` |
| POST | `/workspaces/{ws}/market/install` | owner, admin | `{item_key}` | `Installation` |
| GET | `/workspaces/{ws}/market/installations` | 모든 역할 | | `[Installation]` |
| DELETE | `/workspaces/{ws}/market/installations/{id}` | owner, admin | | 204 |
| GET | `/workspaces/{ws}/templates` | 모든 역할 | | `[{key, name, summary, graph}]` 설치된 템플릿 |
| GET | `/workspaces/{ws}/prompt-packs` | 모든 역할 | | `[{key, name, prompts: [{key, title, system, prompt}]}]` |

`MarketItem = {key, type: template|node|connector|prompt_pack, name, summary, version, publisher, price, tags, installs, installed: bool|null}`
`MarketItemDetail = MarketItem + {description_md, manifest}`
`Installation = {id, item_key, item_name, type, version, status, installed_at}`

## 운영
| 메서드 | 경로 | 권한 | 응답 |
|---|---|---|---|
| GET | `/workspaces/{ws}/runs?app=&status=&from=&to=` | owner, admin, builder, operator | `[Run + {app_name}]` 최근 200개 |
| GET | `/workspaces/{ws}/usage?from=&to=` | owner, admin, builder, operator | `{total_runs, total_input_tokens, total_output_tokens, total_cost, by_app: [{app_id, app_name, runs, input_tokens, output_tokens, cost}]}` |
| GET | `/workspaces/{ws}/audit-logs` | owner, admin | `[{id, user_id, user_email, action, target_type, target_id, meta, created_at}]` 최근 200개 |
