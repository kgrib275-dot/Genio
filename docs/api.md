# API 계약 (prefix `/api/v1`)

설계서 §7을 구체화한 계약이다. 백엔드와 프런트는 이 문서를 기준으로 맞춘다.

## 공통
- 인증: `Authorization: Bearer <access_token>`. SSE처럼 헤더를 못 붙이는 스트림 경로(`…/stream`, `…/events`의 GET)에서만 `?access_token=` 쿼리도 받는다.
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
| POST | `/auth/invitations/{token}/accept` | 없음 | `{name, password?}` | `Tokens` (계정이 있으면 비밀번호 확인 후 멤버 추가 — 로그인과 같은 시도 제한, 2단계 인증 계정은 409. 초대받은 계정으로 로그인한 채 보내면 비밀번호 없이 수락) |
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
| GET | `/apps/{id}/runs` | owner, admin, builder, operator | | `[Run]` 최근 `?limit=`개(기본 50, 최대 1000) |
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
| GET | `/workspaces/{ws}/runs?app=&status=&from=&to=&limit=` | owner, admin, builder, operator | `[Run + {app_name}]` 최근 limit개(기본 200, 최대 1000) |
| GET | `/workspaces/{ws}/usage?from=&to=` | owner, admin, builder, operator | `{total_runs, total_input_tokens, total_output_tokens, total_cost, by_app: [{app_id, app_name, runs, input_tokens, output_tokens, cost}]}` |
| GET | `/workspaces/{ws}/audit-logs` | owner, admin | `[{id, user_id, user_email, action, target_type, target_id, meta, created_at}]` 최근 `?limit=`개(기본 200, 최대 1000) |

---

# v0.2 추가 (Dify 기능 반영, docs/dify-gap.md)

## 노드 추가(그래프 스키마는 그대로, `GET /workspaces/{ws}/nodes`에 자동 노출)
`question_classifier`, `parameter_extractor`, `template`, `variable_aggregator`, `list_operator`, `iteration`, `loop`, `document_extractor`, `variable_assigner`, `agent`.
- `question_classifier`: `data.classes=[{id, name, description}]`. 출구 핸들 = 각 class `id`(condition처럼 `sourceHandle`). 출력 `{class_id, class_name}`.
- 모든 노드 공통 선택 설정(노드 설정 패널 아래 "실패했을 때" 영역):
  - `data._retry = {max_retries: 0~5, interval_ms: 100~5000}`
  - `data._on_error = "stop" | "default" | "branch"`, `data._default = {...}`(default일 때 출력)
  - `branch`이면 출구 핸들 `"fail"`이 생긴다(실패 시 그쪽으로). 출력 `{error}`.
- 템플릿에서 쓸 수 있는 범위: `{{노드.값}}`, `{{input.x}}`, `{{env.x}}`(앱 환경 변수), `{{conv.x}}`(대화 변수, 챗 앱), `{{item}}`/`{{index}}`(iteration 안), `{{loop.index}}`/`{{loop.last}}`(loop 안).
- 입력 노드 `fields[].type`에 `file` 추가. 값은 파일 id(문자열).

## 파일
| POST | `/workspaces/{ws}/files` | owner, admin, builder | multipart `file` | `File` |
| POST | `/public/apps/{token}/files` | 접근 규칙 | multipart `file` | `File` |
`File = {id, filename, mime, size, created_at}` (최대 15MB)

## 앱 기능(App Toolkit)·환경 변수
`AppDetail`에 `features`, `env_vars` 추가.
```
features = {
  opening_statement: string, suggested_questions: [string],
  follow_up: {enabled: bool},
  citations: {enabled: bool},
  moderation: {enabled: bool, keywords: [string], preset_reply: string, check_output: bool},
  annotation_reply: {enabled: bool, score_threshold: number(0.5~1, 기본 0.85)},
  speech: {stt: bool, tts: bool},
  file_upload: {enabled: bool, max_files: number},
  memory: {window: number(0~20)}
}
env_vars = [{key, value, secret: bool}]   # 응답에서 secret 값은 "****abcd"
```
| PATCH | `/apps/{id}/features` | owner, admin, builder | `features`(부분) | `AppDetail` |
| PUT | `/apps/{id}/env-vars` | owner, admin, builder | `{env_vars: [...]}` (secret 값이 `****`로 시작하면 기존 값 유지) | `AppDetail` |
| GET | `/apps/{id}/export` | owner, admin, builder | | `{genio_version: "0.2", app: {name, type, description, icon, features}, graph, env_vars(비밀 제외)}` |
| POST | `/workspaces/{ws}/apps/import` | owner, admin, builder | 위 export 형식 | `AppDetail` |
| POST | `/apps/{id}/duplicate` | owner, admin, builder | | `AppDetail` |
| POST | `/apps/{id}/versions/{version}/restore` | owner, admin, builder | | `AppDetail`(작업본을 그 버전으로) |

## 공개 챗 확장
`PublicApp`에 `features: {opening_statement, suggested_questions, follow_up, citations, speech, file_upload}` 추가.
`POST /public/apps/{token}/chat` 요청에 `files?: [file_id]`. 이벤트 추가:
- `answer`: `{text, message_id}` (message_id로 피드백)
- `citations`: `[{index, filename, content, score}]`
- `suggestions`: `[string]` (이어서 물어볼 질문)
- `moderated`: `{text}` (검열에 걸려 미리 정한 답으로 대체)
- `annotated`: `{text, annotation_id}` (주석 답변으로 바로 답함)
| POST | `/public/apps/{token}/messages/{message_id}/feedback` | 접근 규칙 | `{rating: "like"|"dislike"|null, comment?}` | `{ok}` |

## 로그·주석·모니터링
| GET | `/apps/{id}/conversations?page=&size=&q=` | VIEW_RUNS | | `[{id, user_name, external_session_id, message_count, likes, dislikes, created_at, last_message_at, first_question}]` — size 기본 30·최대 100, q는 메시지 내용 검색 |
| GET | `/conversations/{id}/messages` | VIEW_RUNS | | `[{id, role, content, run_id, feedback, created_at, annotated, moderated}]` |
| GET | `/apps/{id}/annotations` | owner, admin, builder | | `[{id, question, answer, hit_count, created_at}]` |
| POST | `/apps/{id}/annotations` | owner, admin, builder | `{question, answer}` | `Annotation` |
| PATCH | `/annotations/{id}` | owner, admin, builder | `{question?, answer?}` | `Annotation` |
| DELETE | `/annotations/{id}` | owner, admin, builder | | 204 |
| GET | `/apps/{id}/stats?days=7` | VIEW_RUNS | | `{days: [{date, runs, conversations, messages, input_tokens, output_tokens, cost, avg_latency_ms, success_rate, likes, dislikes}], totals: {...같은 키}}` |

## 앱 API 키·서비스 API
| GET | `/apps/{id}/api-keys` | owner, admin, builder | | `[{id, name, prefix, created_at, last_used_at}]` |
| POST | `/apps/{id}/api-keys` | owner, admin, builder | `{name}` | `{id, name, prefix, created_at, key}` (key는 이때 한 번만) |
| DELETE | `/api-keys/{id}` | owner, admin, builder | | 204 |

서비스 API(헤더 `Authorization: Bearer gk-...`, 앱 키, IP·키당 분당 60회):
| POST | `/service/chat-messages` | `{query, inputs?, conversation_id?, user?}` | `{answer, conversation_id, message_id, metadata: {usage, citations}}` |
| POST | `/service/workflows/run` | `{inputs}` | `{run_id, status, outputs, error, elapsed_ms}` |
| GET | `/service/parameters` | | `{input_fields, features}` |

## 지식베이스 확장
`KnowledgeBase`에 `settings` 추가:
```
settings = {
  chunk_mode: "general" | "parent_child", separator: "\n\n", chunk_size, chunk_overlap, child_chunk_size,
  retrieval: {method: "vector"|"keyword"|"hybrid", top_k, score_threshold, vector_weight(0~1), rerank: bool}
}
```
`Document`에 `metadata: {키: 값}`, `source: "upload"|"url"`, `url` 추가.
| PATCH | `/knowledge-bases/{id}` | owner, admin, builder | `{name?, settings?}` | `KnowledgeBase` |
| POST | `/knowledge-bases/{id}/documents/url` | owner, admin, builder | `{url}` | `Document` |
| PATCH | `/documents/{id}` | owner, admin, builder | `{metadata}` | `Document` |
| POST | `/documents/{id}/reprocess` | owner, admin, builder | | `Document` (설정 바꾼 뒤 다시 조각내기) |
| GET | `/documents/{id}/chunks` | VIEW_RUNS | | `[{id, index, content, parent_content, enabled, char_count}]` |
| PATCH | `/chunks/{id}` | owner, admin, builder | `{content?, enabled?}` | `Chunk` |
| POST | `/knowledge-bases/{id}/search` | 기존 | `{query, top_k?, method?, score_threshold?, metadata_filter?: {키: 값}}` | `[{chunk_id, document_id, filename, content, score, metadata}]` |
`knowledge_search` 노드 data에도 `method`, `score_threshold`, `metadata_filter` 추가.

## 관리 콘솔(owner, admin 전용. 시스템 설정은 "인스턴스 관리자" = 가장 먼저 만든 워크스페이스의 owner)
| GET | `/workspaces/{ws}/admin/overview?days=14` | owner, admin | `{counts: {members, apps, published_apps, knowledge_bases, documents, api_keys}, days: [{date, runs, tokens, cost, active_users, conversations}], top_apps: [{app_id, app_name, runs, cost}]}` |
| PATCH | `/workspaces/{ws}` | owner, admin | `{name?, settings?: {default_models?: {chat?: provider_id, embedding?: provider_id}, public_rate_limit_per_minute?}}` | `{id, name, settings}` |
| GET | `/workspaces/{ws}` | 모든 역할 | | `{id, name, settings}` |
| DELETE | `/workspaces/{ws}/members/{id}` | owner, admin (owner 내보내기는 불가) | | 204 |
| POST | `/workspaces/{ws}/transfer-ownership` | owner | `{member_id}` | `{ok}` (나는 admin이 됨) |
| DELETE | `/workspaces/{ws}/invitations/{id}` | owner, admin | | 204 |
| GET | `/workspaces/{ws}/admin/api-keys` | owner, admin | | `[{id, app_id, app_name, name, prefix, created_at, last_used_at}]` |
| GET | `/admin/system` | 로그인 | | `{is_instance_admin, allow_signup}` |
| PATCH | `/admin/system` | 인스턴스 관리자 | `{allow_signup?}` | 같은 형식 |
`POST /auth/signup`은 `allow_signup=false`면 403. 로그인 화면용 `GET /auth/demo-accounts`는 없앴다(역할별 계정·비밀번호를 공개하지 않음, ADR 0007).

#### 계정 관리(관리 콘솔 > 멤버)
| 메서드 | 경로 | 권한 | 요청 | 응답 |
|---|---|---|---|---|
| POST | `/workspaces/{ws}/admin/accounts` | owner, admin (owner 역할 계정은 owner만) | `{email, name, role?, password?(8자 이상)}` | 201 `{member, temporary_password}` — password를 안 주면 12자 임시 비밀번호를 만들어 이번 한 번만 돌려준다. 이미 가입된 이메일은 409(초대하기 안내) |
| POST | `/workspaces/{ws}/members/{id}/reset-password` | owner, admin (owner·admin 계정은 owner만, 내 계정 불가) | | `{temporary_password}` — 다른 워크스페이스에도 속한 계정은 409 |

`GET /workspaces/{ws}/members`의 각 멤버에 `only_here`(이 워크스페이스에만 속한 계정, 비밀번호 재설정 가능 여부)가 붙는다. 비밀번호는 활동 기록·로그에 남기지 않는다.

---

# v0.3 추가: 개인 설정·프로젝트

## 개인 설정
`GET /me` 응답에 `preferences: {theme: "light"|"dark"|"system", font_size: "normal"|"large", default_workspace_id: string|null, enter_to_send: bool}` 추가.
| PATCH | `/me` | 로그인 | `{name?, preferences?: {theme?, font_size?, default_workspace_id?, enter_to_send?}}` | `/me`와 같은 형식 |
| POST | `/me/password` | 로그인 | `{current_password, new_password(8자+)}` | `{ok, access_token, refresh_token}` (지금 비밀번호가 틀리면 400. 이 기기를 뺀 모든 로그인을 끊고 새 토큰을 준다. 72바이트 넘는 비밀번호는 거절) |

## 프로젝트
워크스페이스 안에서 앱·지식베이스를 묶는 단위. `visibility="private"`이면 만든 사람·프로젝트 멤버·소유자·관리자만 보고, 다른 사람에게는 그 프로젝트의 앱·지식베이스·실행 기록이 404로 숨겨진다.
```
Project = {id, workspace_id, name, description, color: indigo|sky|emerald|amber|rose|violet|slate,
           visibility: workspace|private, created_by, created_by_name, created_at,
           app_count, knowledge_base_count, members: [{user_id, name, email}], can_manage: bool}
```
| GET | `/workspaces/{ws}/projects` | 모든 역할 | | `[Project]` (볼 수 있는 것만) |
| POST | `/workspaces/{ws}/projects` | owner, admin, builder | `{name, description?, color?, visibility?}` | 201 `Project` |
| PATCH | `/projects/{id}` | 만든 사람·owner·admin | `{name?, description?, color?, visibility?}` | `Project` |
| DELETE | `/projects/{id}` | 만든 사람·owner·admin | | 204 (앱·KB는 지우지 않고 '프로젝트 없음'으로) |
| PUT | `/projects/{id}/members` | 만든 사람·owner·admin | `{user_ids: [워크스페이스 멤버 user_id]}` | `Project` |
| GET | `/workspaces/{ws}/projects/overview?days=30` | owner, admin, builder, operator | | `{days, totals, projects: [{project, ...통계}], unassigned}` |

프로젝트 현황판 통계(프로젝트마다, '프로젝트 없음'은 `unassigned`): `apps, published_apps, knowledge_bases, documents, runs, succeeded, failed, waiting_approval, input_tokens, output_tokens, cost, conversations, last_activity_at, success_rate(성공/(성공+실패), 없으면 null), series[{date, runs}]`. 실행·대화·비용은 기간(1~90일) 기준, 앱·지식 수는 현재 값. 볼 수 없는 비공개 프로젝트는 목록과 합계 모두에서 빠진다.

기존 API 변경:
- `App`, `KnowledgeBase` 응답에 `project_id` 추가.
- `GET /workspaces/{ws}/apps?project=<id>|none`, `GET /workspaces/{ws}/knowledge-bases?project=<id>|none` 필터.
- `POST /workspaces/{ws}/apps`, `POST /workspaces/{ws}/knowledge-bases` 요청에 `project_id?`.
- `PATCH /apps/{id}`, `PATCH /knowledge-bases/{id}` 요청에 `project_id` (빈 문자열 `""`이면 '프로젝트 없음'으로 옮김).

---
# v0.4 (ADR 0008) — 자동 실행·데이터 표·캔버스·챗 경험

## 자동 실행(트리거)
`Trigger = {id, app_id, kind: "webhook"|"schedule", name, enabled, config, url?, next_run_at, last_run_at, last_run_id, last_status, created_at}`
- webhook `config = {mode: "async"|"sync", version?: number}` — `url`은 webhook만(전체 주소, 편집 권한자에게만).
- schedule `config = {cron: "0 9 * * 1-5", timezone: "Asia/Seoul", input: {}, version?: number}` — cron 5칸, 최소 1분.

| 메서드 | 경로 | 권한 | 요청 | 응답 |
|---|---|---|---|---|
| GET | `/apps/{id}/triggers` | owner, admin, builder, operator | | `[Trigger]` |
| POST | `/apps/{id}/triggers` | owner, admin, builder | `{kind, name?, enabled?, config}` | 201 `Trigger` (cron이 틀리면 422 두 줄 오류) |
| PATCH | `/triggers/{id}` | owner, admin, builder | `{name?, enabled?, config?}` | `Trigger` (next_run_at 다시 계산) |
| POST | `/triggers/{id}/rotate-token` | owner, admin, builder | | `Trigger` (webhook만, 옛 주소는 바로 막힘) |
| POST | `/triggers/{id}/run-now` | owner, admin, builder | | 201 `Run` (trigger=`schedule` 또는 `webhook`) |
| DELETE | `/triggers/{id}` | owner, admin, builder | | 204 |
| POST·GET | `/hooks/{token}` | 공개(토큰) | JSON 본문(+쿼리) = 입력 | async: 202 `{run_id, status}` · sync: 200 `{run_id, status, output}`(30초 넘으면 202) · 꺼짐/없음 404 · 저장한 버전 없음 409 |
| POST | `/runs/{id}/rerun` | owner, admin, builder | `{input?}` | 201 `Run` (같은 앱·버전, 입력 생략 시 원래 입력, trigger=`rerun`) |

- 실패하면 다른 앱 실행: 앱 기능 `features.on_failure = {app_id: string|null}`. 실패한 실행이 끝나면 그 앱을 `trigger="on_failure"`, 입력 `{failed_app_id, failed_app_name, run_id, error, input}`로 실행. `on_failure`로 시작된 실행이 실패하면 다시 부르지 않는다.
- Run.trigger 값: test, chat, api, schedule, webhook, rerun, on_failure, preview, subflow(run_app 블록이 부른 하위 실행).
- 실패 처리 앱은 test·preview·tool·subflow 실행이 실패할 때는 부르지 않는다(빌더 테스트가 알림을 쏟지 않도록). 실패 처리 앱에 저장한 버전이 없으면 작업본으로 실행한다.

## 데이터 표
`DataTable = {id, workspace_id, project_id, name, description, columns: [{key, label, type: text|number|boolean|date|json}], row_count, created_at, updated_at}`
`DataRow = {id, table_id, row_key, data: {}, created_at, updated_at}`

| 메서드 | 경로 | 권한 | 요청 | 응답 |
|---|---|---|---|---|
| GET | `/workspaces/{ws}/data-tables` | 모든 역할(볼 수 있는 프로젝트만) | | `[DataTable]` |
| POST | `/workspaces/{ws}/data-tables` | owner, admin, builder | `{name, description?, columns?, project_id?}` | 201 `DataTable` (같은 이름 409) |
| GET·PATCH·DELETE | `/data-tables/{id}` | 보기: 모든 역할 · 바꾸기: owner, admin, builder | `{name?, description?, columns?, project_id?}` | `DataTable` / 204 |
| GET | `/data-tables/{id}/rows?limit=50&offset=0&q=` | 모든 역할 | | `{total, rows: [DataRow]}` (q는 값 전체 글 검색) |
| POST | `/data-tables/{id}/rows` | owner, admin, builder, operator | `{row_key?, data}` | 201 `DataRow` (row_key 겹치면 409) |
| PATCH·DELETE | `/data-rows/{id}` | owner, admin, builder, operator | `{row_key?, data?}` | `DataRow` / 204 |
| POST | `/data-tables/{id}/import` | owner, admin, builder | multipart `file`(CSV, 첫 줄 머리글, 1MB·5000행 이하) | `{imported, columns}` |
| GET | `/data-tables/{id}/export.csv` | 모든 역할 | | `text/csv` (UTF-8 BOM) |

## 새 블록(`GET /workspaces/{ws}/nodes`에 자동 노출)
| type | 이름 | data | 출력 |
|---|---|---|---|
| `wait` | 기다리기 | `{seconds: 1~300}` | `{waited_seconds}` |
| `set_fields` | 값 정리 | `{fields: [{key, value(템플릿), type: text|number|boolean|json}], keep_input?: bool, source?: 템플릿}` | 만든 값들 |
| `date_time` | 날짜·시간 | `{operation: now|format|add|diff, value?, format?, amount?, unit?: minutes|hours|days|weeks|months, other?, timezone?}` | `{result, iso, timestamp}` |
| `run_app` | 다른 앱 실행 | `{app_id, input: {키: 템플릿}}` | 그 앱의 출력(`text` 등) |
| `data_table` | 데이터 표 | `{table_id, operation: insert|upsert|get|find|list|delete|count, row_key?, data?: {키: 템플릿}, filter?: {키: 템플릿}, limit?}` | `{row, rows, count, found}` |

## 그래프 형식 추가(schemas/graph.py)
- `GraphNode.disabled?: boolean` — 끈 블록은 건너뛰고(단계 상태 `skipped`) 입력을 그대로 다음으로. 분기 블록은 첫 번째 출구로.
- `Graph.notes?: [{id, text, position, width, height, color: yellow|blue|green|pink|gray}]` — 실행과 무관한 캔버스 메모.

## 챗 경험
- 공개 챗 SSE(`POST /public/apps/{token}/chat`)에 이벤트 추가: `delta {text, node_id}`(답 조각, 쌓아서 보여 줌), `delta_reset {}`(다른 AI 블록이 시작돼 지금까지 조각을 지움). 마지막 `answer`가 최종 글이다. 출력 검열을 켠 앱은 delta를 보내지 않는다.
- `GET /public/apps/{token}/sessions/{session_id}/messages` — 이 세션(브라우저가 가진 무작위 id)의 메시지 `[{id, role, content, created_at, feedback, citations?}]`. 다른 앱의 세션이면 404.
- `GET /public/apps/{token}`에 `appearance` 추가.
- 배포 모양: `PATCH /deployments/{id}` `{appearance: {primary_color: "#4f46e5", position: "right"|"left", launcher_text, greeting, open_on_load, width, height, title}}` (owner, admin, builder). widget.js가 이 값을 쓴다.
- 대화로 시험하기: `POST /apps/{id}/preview/chat` (owner, admin, builder) — 공개 챗과 같은 SSE 이벤트, 작업본 그래프로 실행, trigger=`preview`. 로그·모니터링 집계에서 뺀다.

---
# v0.5 (ADR 0009) — 기능 정의서 P0 반영

## 사람 개입·작업함
| 메서드 | 경로 | 권한 | 요청 | 응답 |
|---|---|---|---|---|
| GET | `/workspaces/{ws}/tasks?status=open\|done\|cancelled\|all&mine=bool&limit≤1000` | 모든 역할(볼 수 있는 프로젝트만) | | `[Task + can_act]` |
| GET | `/workspaces/{ws}/tasks/count` | 모든 역할 | | `{open}` (내가 처리할 수 있는 것) |
| GET | `/workspaces/{ws}/tasks/{id}` | 모든 역할 | | `Task + can_act` |
| POST | `/workspaces/{ws}/tasks/{id}/complete` | owner·admin 항상, 승인은 approver_roles(없으면 builder·operator), 나머지는 담당 사용자·역할 | `{approved?, values?, comment?}` | `Task` (실행이 이어짐) |
| POST | `/workspaces/{ws}/tasks/{id}/cancel` | owner, admin, builder | | `Task` (기다리던 실행은 실패) |
| GET·POST | `/public/tasks/{token}` | 공개(토큰 = 권한, IP당 분당 60) | POST는 complete와 같음 | 내부 id 없는 Task, 이미 처리했으면 409 |
| POST | `/runs/{id}/approve` | 그대로 | | 작업도 함께 닫음. 질문·배정이면 409 |
| POST | `/runs/{id}/rerun` | owner, admin, builder | `{input?, from_node?}` | 새 Run. from_node면 그 앞 단계 출력을 context로 복사, 없거나 도달 못한 단계면 422 |

## 챗 ↔ 흐름·상담원 전환
- 공개 챗 SSE 이벤트 추가: `pending {run_id, message}`(사람 확인 대기), `handoff {message, message_id?}`.
- 사람을 기다리던 챗 실행이 나중에 끝나면 결과를 대화에 assistant 메시지로 붙인다(화면은 대기 중 8초마다 다시 읽음).

| 메서드 | 경로 | 권한 | 요청 | 응답 |
|---|---|---|---|---|
| GET | `/public/apps/{token}/sessions/{sid}/state` | 배포 접근 | | `{status: bot\|handoff\|closed, waiting, last_message_at}` |
| POST | `/public/apps/{token}/sessions/{sid}/handoff` | 배포 접근, 속도 제한 | | `{status:"handoff", message}`, 상담원 연결이 꺼져 있으면 409 |
| GET | `/apps/{id}/conversations?status=handoff` | VIEW_RUNS | | 각 항목에 `status` |
| POST | `/conversations/{id}/reply` | VIEW_RUNS | `{content}` | 201 Message(role `agent`), handoff가 아니면 409 |
| POST | `/conversations/{id}/close` | VIEW_RUNS | | `{id, status:"closed"}` |
| POST·PATCH | `/apps/{id}/deployments`, `/deployments/{id}` | 배포 역할 | `allowed_users`(워크스페이스 멤버만), PATCH는 `access`·`allowed_roles`도 | access=roles면 역할 OR 사용자 |

## 흐름 앱 공유(입력 폼 → 결과)
| 메서드 | 경로 | 권한 | 요청 | 응답 |
|---|---|---|---|---|
| POST | `/public/apps/{token}/runs` | 배포 접근, 속도 제한 | `{input, files?}` (입력 20KB 이하) | 202 `{run_id, status}` (trigger `form`) |
| GET | `/public/apps/{token}/runs/{run_id}` | 배포 접근 | | `{run_id, status, text?, error?{message,hint,detail}}` — 그 링크 앱의 form 실행만, 단계 값은 주지 않음 |

## 연결·외부에서 받기·HTTP
| 메서드 | 경로 | 권한 | 요청 | 응답 |
|---|---|---|---|---|
| POST | `/workspaces/{ws}/connectors/credentials/{id}/test` | owner, admin, builder | | `{ok, checked, message}` (비밀값 제거) |
| GET·PUT | `/workspaces/{ws}/connectors/private-hosts` | owner, admin | `{hosts}` (최대 20, localhost·메타데이터 주소 거부) | `{hosts}` |
| POST | `/triggers/{id}/secret` | owner, admin, builder | | Trigger + `secret`(한 번만) |
| GET | `/triggers/{id}/payloads` | owner, admin, builder | | 최근 받은 값 5개(인증·쿠키·서명 헤더 제외, 본문 4KB) |
| POST | `/workspaces/{ws}/http/preview` | owner, admin, builder | `{method, url, headers, body, auth}` | `{status, headers, body, truncated, elapsed_ms}` |
- 외부에서 받기 서명: config `require_signature`. 헤더 `X-Genio-Timestamp`(±300초), `X-Genio-Signature: sha256=hex(HMAC(secret, "{ts}.{원문}"))`. 틀리면 401(받은 값 기록에는 남음).
- HTTP 단계 data: `auth {type: none|bearer|basic|header, credential_id, header_name}`(연결 정보 'HTTP 인증 정보'만), `pagination {type: none|next_url|page, items_path, path, param, max_pages≤10}`. 코드 단계 `language: python|javascript`. 모든 단계 `_timeout`(초, 1~600).
- DB 커넥터(PostgreSQL·MySQL): 읽기 SELECT 1개(읽기 전용, 15초, 500행), 쓰기 INSERT/UPDATE/DELETE 1개, 값은 바인딩. 내부 주소는 허용 목록에 있을 때만.

## AI·비용·한도·보안
| 메서드 | 경로 | 권한 | 응답 |
|---|---|---|---|
| GET | `/llm/catalog`, `/llm/embedding-models` | 로그인 | 모델 목록(컨텍스트·단가·도구·비전·임베딩) |
| GET | `/workspaces/{ws}/usage?group=user` | owner, admin, builder, operator | `{total_*, by_user[]}` |
| GET | `/workspaces/{ws}/usage/estimate?model=&days=30` | 같음 | `{current_cost, estimated_cost, difference, …}`, 모르는 모델 422 |
| GET·PATCH | `/workspaces/{ws}/limits` | owner, admin | 월 예산·알림 기준·실패 알림·알림 메일·메일 연결·보관 일수 + `month_cost` |
| GET | `/service/runs`, `/service/runs/{id}` | API 키 `logs` 범위 | 최근 실행 / 실행 하나 |
- AI 연결 `azure`(base_url 필수). 지식베이스 생성 `embedding_model`(지식베이스별 고정), 문서 `enabled`, DOCX·PPTX·XLSX·HTML 읽기.
- API 키 `scopes` ⊆ {chat, run, logs}(기본 chat·run), 범위 밖이면 403.
- 로그인 시도 제한(이메일+IP 15분 5번, 이메일 15분 20번 → 429), 비밀번호 규칙(8자 이상·영문+숫자·흔한 비밀번호 거부, 가입·바꾸기·관리자 계정 만들기 공통), X-Forwarded-For는 신뢰 프록시 뒤에서만, CORS는 공개 주소+localhost, 쿼리에 NUL 문자면 400, nginx 보안 헤더.
- 공개 챗 속도 제한 키는 앱별(`chat:{app_id}:{ip}`).

## 마켓·빌더·배우기
| 메서드 | 경로 | 권한 | 응답 |
|---|---|---|---|
| POST | `/workspaces/{ws}/market/installations/{id}/update` | owner, admin | 설치 정보, 최신이면 409 |
| GET·PUT | `/apps/{id}/test-inputs` | owner, admin, builder | `[{name, input}]` (최대 20, 20KB) |
| GET | `/workspaces/{ws}/builder/metrics` | owner, admin | 빌더 지표 평균·앱별 |
| GET | `/workspaces/{ws}/samples` | 모든 역할 | `{installed, project_id, apps[]}` |
| POST | `/workspaces/{ws}/samples` | owner, admin, builder | 201 샘플 10가지 넣기, 이미 있으면 409 |
- 마켓 아이템 `category`, 템플릿 상세 `preview`(단계·앱 종류·빈칸), 설치 `latest_version`·`update_available`.
- 작업본 저장 `PUT /apps/{id}/draft`에 `source`(canvas|builder|import, 기본 canvas) — 빌더 지표용.
- 실행 상세에 `story[]`(실행 이야기)와 단계별 `summary`(한 문장). 빌더 툴 `get_run`.
- Run.trigger 값 추가: `form`(공유 입력 폼).

## v0.6 MCP 게시·외부 추적 (ADR 0010)

### MCP 서버로 게시
| 메서드 | 경로 | 인증 | 설명 |
|---|---|---|---|
| POST | `/service/mcp` | 앱 API 키(`Bearer gk-...`), 권한 `mcp` | MCP Streamable HTTP. JSON-RPC 2.0 메시지(또는 일괄 배열)를 받아 JSON으로 답한다. 알림만 오면 202 |
| GET·DELETE | `/service/mcp` | - | 405(서버가 먼저 보내는 SSE 스트림·세션 없음) |

- 앱 기능 `features.mcp = {enabled, tool_name, description}`. 꺼져 있으면 403. `tool_name`은 영문·숫자·`_-`만(비우면 앱 이름에서, 없으면 `app_<id 앞 8자리>`).
- 지원 메서드: `initialize`, `notifications/*`(받기만), `ping`, `tools/list`(도구 1개), `tools/call`, `resources/list`·`prompts/list`(빈 목록). 그 밖은 -32601.
- 프로토콜 버전: `2025-11-25`, `2025-06-18`, `2025-03-26`, `2024-11-05`. 요청한 버전이 목록에 있으면 그대로, 아니면 `2025-11-25`. `MCP-Protocol-Version` 헤더가 목록 밖이면 400.
- 도구 `inputSchema`: 입력 단계 항목(number→number, boolean→boolean, 나머지 string). 챗 앱은 `query`(필수)가 더해진다.
- `tools/call`: 저장한 최신 버전을 `trigger="mcp"`로 실행하고 최대 60초 기다린다. 성공하면 `content[0].text` + `structuredContent{text, outputs, run_id}`. 실패·승인 대기·필수값 빠짐·시간 초과는 `isError: true`와 두 줄 안내. 모르는 도구는 -32602.
- 속도 제한: 키·IP별 분당 60회(서비스 API 공통) + 키별 분당 120회.
- 앱 API 키 `scopes`에 `mcp`(MCP 도구)를 더했다(최대 4개).

### 외부 추적(Langfuse·LangSmith)
| 메서드 | 경로 | 권한 | 설명 |
|---|---|---|---|
| GET | `/workspaces/{ws}/tracing` | owner, admin | `{langfuse{enabled, host, public_key, secret_key(****abcd), has_secret}, langsmith{enabled, endpoint, project, api_key(****abcd), has_key}}` |
| PUT | `/workspaces/{ws}/tracing` | owner, admin | 같은 모양으로 저장. 비밀 칸이 비었거나 `****`로 시작하면 저장된 값 유지, `clear_secret`·`clear_key`로 지움. 주소가 http(s)가 아니면 422 |
| POST | `/workspaces/{ws}/tracing/test` | owner, admin | `{target: langfuse|langsmith}` → 시험 기록 하나를 보내 `{ok, message}` |

- 저장 위치: `workspaces.settings.tracing`(비밀값은 Fernet 암호문). `GET /workspaces/{ws}` 응답에서는 이 키를 뺀다.
- 실행이 끝나면(성공·실패) 켠 곳에 보낸다. 워커 태스크 `genio.send_trace`(테스트는 바로). 실패는 로그만 남기고 실행에는 영향 없음.
- Langfuse: `POST {host}/api/public/ingestion`, Basic 인증(공개 키:비밀 키), `batch`에 `trace-create`(실행) + 단계마다 `span-create`, AI 단계는 `generation-create`(model, usage{input, output, total}, costDetails.total).
- LangSmith: `POST {endpoint}/runs/batch`, 헤더 `x-api-key`, `post`에 루트 실행(chain) + 단계 자식(AI는 llm, http·connector는 tool). `dotted_order`·`trace_id`·`parent_run_id`, AI 단계 `outputs.usage_metadata`.
- 단계별 AI 사용량은 `run.context.usage[node_id] = {input_tokens, output_tokens, model}`에 남긴다.
- 외부 호출은 safe_http를 거친다(사설 IP 차단, `GENIO_ALLOW_PRIVATE_NETWORK=true`면 사내 Langfuse 허용). 값 하나는 4,000자까지 잘라 보낸다.

## v0.6 지식베이스 Q&A·처리 순서

모두 지식베이스의 소유자·관리자·빌더만 쓸 수 있다(`require_role(EDIT_APPS, via="kb")`). 오류는 `{message, hint}` 두 줄이다.

### 설정(`PATCH /knowledge-bases/{kb_id}`의 `settings`)
- `chunk_mode`: `general` | `parent_child` | `qa`(v0.6). `qa`이면 일반 문서는 일반 방식으로 나눈 뒤, 조각마다 워크스페이스 기본 AI로 질문·답을 `qa_pairs_per_chunk`쌍(1~10, 기본 3) 만든다. 비용을 막으려고 문서당 앞 40조각까지만 쓴다(미리 보기는 3조각). AI 연결이 없으면 문서가 `failed`가 되고, 두 줄 오류가 남는다.
- `pipeline`: 문서 처리 순서. 아래 순서는 바꿀 수 없다.
  - 순서: `extract` → `clean` → `split` → `metadata` → `store`
  - `extract`·`split`·`store`는 항상 켜져 있다.
  - `clean`: `collapse_spaces`, `mask_urls`(→`[주소]`), `mask_emails`(→`[이메일]`), `remove_repeated_lines`, `remove_patterns`
    - `remove_repeated_lines`: 80자 이하이면서 3번 이상 나오는 줄을 지운다(머리글·바닥글).
    - `remove_patterns`: 정규식, 최대 10개.
  - `metadata`: `fixed`(꼬리표 묶음), `filename_pattern`(이름 붙은 묶음 정규식). 처리할 때 문서 꼬리표에 더한다.
  - 정규식이 잘못되면 422를 돌려준다.

### `POST /knowledge-bases/{kb_id}/qa/columns` (multipart `file`: CSV·XLSX, 최대 5MB)
→ `{columns, question_column, answer_column, sample: [[...]], row_count}`. 질문·답 열은 이름(질문/question/Q, 답/답변/answer/A)으로 추측한다.

### `POST /knowledge-bases/{kb_id}/documents/qa` (multipart `file`, `question_column?`, `answer_column?`)
- 질문·답 표를 가져온다. 결과는 문서 하나이고 `source`가 `qa_table`이다.
- 질문과 답이 모두 채워진 줄 하나가 조각 하나가 된다.
  - 임베딩과 키워드 검색은 질문만 쓴다.
  - 돌려주는 글(`content`)은 `"질문: …\n답: …"`이다.
- 고른 열 이름은 문서 꼬리표 `qa_question_column`·`qa_answer_column`에 남는다(다시 나누기용).
- 검색 결과(`POST /knowledge-bases/{kb_id}/search`, 지식 검색 단계의 `results`)에서 이런 조각은 `question`·`answer`가 더 붙는다. `context`는 그대로 쓴다.

### `POST /knowledge-bases/{kb_id}/preview` (multipart: `file` 또는 `document_id`, `settings?`: JSON 글)
- 지금 설정에 `settings`를 더해 처리 순서를 돌려 본다.
- 문서·조각·설정 중 아무것도 저장하지 않는다. 임베딩도 하지 않는다.
- 응답: `{total, chunks: [{index, content, parent_content, question?, answer?, char_count}] (앞 50개), metadata, log: [문장], text_preview, chunk_mode}`

### `POST /knowledge-bases/{kb_id}/reprocess`
지식베이스의 모든 문서를 지금 설정으로 다시 나눈다(워커). 응답은 `{queued}`이다.

## v0.6 AI 공급자·비전
| 메서드 | 경로 | 역할 | 설명 |
|---|---|---|---|
| GET | `/llm/providers` | 로그인한 모든 사용자 | AI 공급자 목록: `key`, `name`, `group`(기본·국내·해외·오픈 모델 호스팅·직접 입력), `base_url`, `default_model`, `models[]`(`model`, `label`, `vision`, `json`), `note`, `native`, `needs_base_url`, `embedding`, `vision` |

- `POST /workspaces/{ws}/llm-providers`의 `provider`는 위 목록의 `key`(22곳). 기본 5종(openai·anthropic·google·azure·openai-compatible) 외에는 OpenAI 호환 preset이라 `base_url`을 비우면 목록의 기본 주소를 쓴다. 목록에 없는 key는 422(두 줄 오류). 주소는 http(s)만.
- `/llm/catalog`에 preset 모델이 더해진다(단가를 모르는 모델은 0 → 비용 미집계).
- AI 단계(`llm`) `images`: 문자열 목록(최대 4). 값은 올린 파일 id(입력 단계 `type: "file"` 항목, `{{n1.photo}}`) 또는 공개 http(s) 이미지 주소. 엔진이 읽어 형식(PNG·JPG·GIF·WEBP, 앞 바이트로 판별)·크기(장당 5MB)를 검사하고 공급자 형식(OpenAI `image_url` data URL, Anthropic `image` base64, Gemini `inline_data`)으로 보낸다. 주소는 서버가 받으며 사설망·localhost 차단 규칙이 그대로 적용된다.
- 챗 첨부: 파일 올리기를 켠 챗 앱에서 사진을 첨부하면 입력 단계의 파일 항목으로 들어가고, AI 단계 `images`로 넘기면 AI가 사진을 본다(화면은 첨부 전 미리 보기를 보여 줌).

## v0.6 마켓 확대

기본 마켓 아이템이 21개에서 52개로 늘었다(커넥터 21 · 템플릿 21 · 프롬프트 팩 9 · 단계 1). API 형식은 그대로다. `GET /market/items`의 `category`·`q`·`type`으로 거른다.

| 종류 | 새 아이템 |
|---|---|
| 커넥터(13) | `notion`(페이지 만들기·DB 조회), `jira`(이슈 만들기·JQL 찾기), `teams`(워크플로 웹후크 카드), `discord`(웹훅), `telegram`(봇 메시지), `github`(이슈 만들기·목록), `trello`(카드), `asana`(할 일), `airtable`(줄 추가·읽기), `hubspot`(연락처), `linear`(이슈·팀 목록), `dooray`(수신 웹훅), `kakaowork`(사람·대화방 메시지) |
| 템플릿(11) | 병렬 갈래 5개: `tpl_parallel_translate_summary`, `tpl_parallel_order_check`, `tpl_parallel_broadcast`, `tpl_lead_capture`, `tpl_daily_digest_kr`. 그 밖: `tpl_bug_to_github`, `tpl_request_to_jira`, `tpl_meeting_to_notion`, `tpl_survey_to_airtable`, `tpl_feedback_to_linear`, `tpl_chat_to_task` |
| 프롬프트 팩(7) | `prompts_writing`, `prompts_meeting`, `prompts_tone`, `prompts_translate`, `prompts_summary`, `prompts_hr`, `prompts_marketing` |

- 모든 커넥터는 `net.http`(safe_http: 사설 IP 차단, 타임아웃·응답 크기 제한)로만 호출하고, manifest `permissions`에 선언한 도메인만 접속한다.
- 비밀값은 헤더로만 보낸다. Trello는 OAuth 헤더를 쓰고, 텔레그램만 주소에 토큰이 들어간다. 오류 문장에는 주소를 넣지 않고, 런타임이 비밀값을 지운다.
- Google Calendar는 OAuth가 필요해 넣지 않았다. LINE Notify는 서비스가 종료돼 넣지 않았다.
- 화면: 마켓 종류 칩에 개수를 보이고, 분류 칩(개수 포함, 누르면 거르기)과 정렬(많이 설치한 순·이름순·새로 나온 순)을 넣었다.

## 운영 준비(시스템 상태·서버 오류 기록·활동 기록 내보내기)
| 메서드 | 경로 | 권한 | 설명 |
|---|---|---|---|
| GET | `/admin/status` | 인스턴스 관리자 | `{checked_at, overall, version, env, items[{status: ok\|warn\|error\|unknown, label, detail}], counts{users, workspaces, runs_24h, failed_runs_24h, server_errors_24h}}` |
| GET | `/admin/errors?limit=500` | 인스턴스 관리자 | 최근 서버 오류 `[{id, created_at, source: api\|engine, where, error_type, message, request_id, user_id, workspace_id}]`(30일 보관, 비밀값 가림) |
| GET | `/workspaces/{ws}/audit-logs/export?area=&action=&user=&days=&q=` | 소유자·관리자 | 활동 기록 CSV(UTF-8 BOM, 최대 5만 줄). `user=(시스템)`은 사람 없이 남은 기록 |

- 모든 응답 헤더에 `X-Request-ID`가 붙는다. 요청에 안전한 형식(영숫자·`._-`, 6~64자)의 `X-Request-ID`를 보내면 그 값을 그대로 쓴다.
- 처리하지 못한 오류(500)는 `detail.hint`에 문의 번호가 들어간다.


## v0.7 계정 스스로 관리
| 메서드·경로 | 권한 | 설명 |
|---|---|---|
| POST /auth/password/forgot `{email}` | 공개(IP 10회·이메일 3회/15분) | 재설정 링크 메일. 있는 계정·없는 계정 모두 같은 답. 메일 설정이 없으면 503 |
| POST /auth/password/reset `{token, password}` | 공개 | 30분·1회용 토큰. 비밀번호 규칙 적용, 모든 기기 로그아웃 |
| POST /auth/verify-email `{token}` | 공개 | 이메일 확인(48시간) |
| POST /auth/verify-email/resend `{email}` | 공개(같은 답) | 확인 메일 다시 |
| POST /me/verify-email/resend | 로그인 | 내 확인 메일 다시 |
| POST /auth/login | 공개 | 토큰, 또는 `{verify_required, email}`, 또는 `{mfa_required, mfa_token(5분)}` |
| POST /auth/login/mfa `{mfa_token, code}` | 공개(5회 틀리면 15분) | 앱 코드 6자리 또는 복구 코드(1회) → 토큰 |
| POST /me/2fa/setup · /me/2fa/enable `{code}` · /me/2fa/disable `{password, code}` · /me/2fa/recovery-codes `{password}` | 로그인 | TOTP(RFC 6238, SHA1·6자리·30초). 비밀값은 Fernet, 복구 코드는 SHA-256 해시 |
| GET /me/sessions · DELETE /me/sessions/{id} · POST /me/sessions/revoke-all | 로그인 | 로그인한 기기. revoke-all은 이 기기용 새 토큰을 돌려줌 |
| GET /me/export | 로그인 | 내 데이터 JSON(비밀값 제외) |
| POST /me/delete `{password, confirm:"탈퇴"}` | 로그인 | 하나뿐인 소유자(다른 멤버 있음)면 409. 계정 익명화·멤버십 삭제 |
| GET/PUT /admin/system/mail · POST /admin/system/mail/test | 인스턴스 관리자 | 시스템 SMTP. 비밀번호는 ****abcd |
| PATCH /admin/system `{require_email_verification}` | 인스턴스 관리자 | 메일 설정이 없으면 422 |
| POST /workspaces/{ws}/members/{id}/reset-2fa | 소유자·관리자(소유자·관리자 대상은 소유자만) | 휴대폰 분실 시 2단계 인증 끄기 |

토큰: JWT에 `sid`(user_sessions.id)를 넣고, 요청마다 기기가 끊겼는지와 `users.tokens_valid_after`(비밀번호 재설정·모든 기기 로그아웃·탈퇴 시각)를 확인한다. 마이그레이션 0010.


## v0.8 일괄 실행·단계 시험·값 확인창
흐름(워크플로우) 앱 전용이다(챗 앱·파일 입력 칸이 있는 흐름은 422). 새 DB 테이블·마이그레이션은 없다.

### 일괄 실행
| 메서드·경로 | 권한 | 설명 |
|---|---|---|
| GET /apps/{id}/batches/template.csv | 제작자 이상 | 입력 칸 이름이 머리글인 CSV 양식(UTF-8 BOM) |
| POST /apps/{id}/batches/preview (multipart `file`) | 제작자 이상 | CSV·XLSX(2MB)를 읽어 `{fields, max_rows, columns[{header, field}], unmatched[], rows[{row, values, errors[{message, hint}]}], total, ok_count, error_count}`. 열은 입력 칸 key·이름으로 맞춘다(순서 무관) |
| POST /apps/{id}/batches `{rows[{row, values}], skip_invalid?, version?}` | 제작자 이상 | 최대 200줄. `version`이 없으면 검사를 통과한 작업본. `201 {batch_id, total}`. 월 비용 한도에 걸리면 429 |
| GET /apps/{id}/batches/{batch_id} | 운영자 이상 | `{batch_id, total, counts{queued, running, succeeded, failed, cancelled, waiting_approval}, settled, done, cancelled, created_at, rows[{row, status, input, text, error?, run_id}]}` |
| POST /apps/{id}/batches/{batch_id}/cancel | 제작자 이상 | 아직 시작하지 않은 줄만 취소 `{cancelled: n}` |
| GET /apps/{id}/batches/{batch_id}/results.csv | 운영자 이상 | 줄·상태·입력 칸들·결과·오류(UTF-8 BOM). `=`·`+`·`-`·`@`로 시작하는 글은 앞에 `'`를 붙여 수식 실행을 막는다 |
| 공유 링크 | 접근 권한 확인 | 같은 경로가 `/public/apps/{token}/batches[...]`에 있다. 한 번에 **50줄**, 앱·IP당 분당 6번(양식·상태 읽기 제외), 끝나지 않은 공개 일괄 실행은 앱당 3개까지(넘으면 429). 줄별 `run_id`와 내부 오류 원문은 내보내지 않는다. 다른 앱의 batch_id는 404 |

- 줄마다 `Run`(trigger=`batch`) 한 개를 미리 만들고, 번호·줄·보냄 표시는 `run.context`(`batch_id`, `row`, `source`, `dispatched`, `cancelled`)에 둔다. 서버를 다시 켜도 상태가 이어진다.
- **동시 실행 한도 5줄**: 처음에 5줄만 큐에 넣고, 줄이 끝날 때마다(executor `_after_finish`) 다음 줄을 넣는다. 상태를 읽을 때도 한 번 더 밀고, 5분 넘게 '대기'에 머문 줄은 다시 큐에 넣는다. PostgreSQL에서는 batch마다 advisory lock으로 여러 워커가 같은 줄을 넣지 않게 한다.
- 한 줄이 실패해도 나머지는 계속 간다. 일괄 실행의 줄은 '실패하면 다른 앱 실행'을 부르지 않는다. 실행 목록에는 `일괄`로 보인다.
- 줄 검사: 필수 칸이 비면 `'이름' 칸이 비어 있어요.`, 숫자 칸에 글이 있으면 `'수량'에는 숫자를 넣어 주세요(지금 '많이').`처럼 두 줄(message·hint)로 돌려준다.

### 단계 하나만 시험(제작자 이상)
| 메서드·경로 | 설명 |
|---|---|
| POST /apps/{id}/nodes/{node_id}/test-inputs `{data?}` | 이 단계가 쓰는 앞 단계 값 목록 `{node_id, type, label, testable, reason, warn, risky, last_run_id, groups[{scope, label, editable, fields[{field, path, value, kind, from_last_run}]}]}`. 값은 가장 최근에 성공한 실행에서 채운다. `data`는 아직 저장하지 않은 설정 패널의 값. `{{ 100 // n1.qty }}`처럼 식 안의 참조도 찾는다 |
| POST /apps/{id}/nodes/{node_id}/test `{values?, data?}` | 그 단계 하나만 실행. `values`는 `{"n1": {...}, "input": {...}, "conv": {...}}`이고 안 보내면 최근 성공한 실행의 값. `{ok, output, handle, summary, error{message, hint}, ms, logs[], tokens{input_tokens, output_tokens}}` |

- 실행 기록은 남기지 않는다. 시간 제한·사설망 차단·코드 격리는 실제 실행과 같은 경로(`engine/executor.run_node_once`)를 쓴다. 월 비용 한도에 걸리면 429.
- 승인·질문·배정 같은 사람 단계는 `422 사람 단계는 단독으로 시험할 수 없어요.`
- 바깥에 영향을 주는 단계(연결·쓰기 방식 HTTP·데이터 표 쓰기·다른 앱 실행·에이전트)는 `risky: true`와 `warn` 문장을 돌려주고, 화면이 실행 전에 한 번 더 확인한다.

### 값 확인창
화면 기능이다(새 API 없음). 실행 로그 패널·실행 상세에서 `run.steps[].output`을 `경로 = 값` 목록으로 펼쳐 검색하고, 복사 단추로 `{{단계.경로}}`를 복사한다. 캔버스에서 단계를 고르면 설정 패널에 그 단계의 지난 테스트 실행 값이 나온다.

## v0.8 지식 데이터 소스·외부 지식베이스·검색 튜닝 (ADR 0012)
DB 변경 없음: 지식베이스 설정(`knowledge_bases.settings` JSON)과 문서 꼬리표(`documents.doc_metadata`)만 쓴다. `kind`·`external`·`sources`·`tuning` 키는 아래 전용 API로만 바꾸고, `PATCH /knowledge-bases/{id}`의 `settings`로는 바꿀 수 없다(무시).

### 가져오기 소스
소스 한 개 = `{id, type: web|notion|google, name, config, schedule: none|daily, last_sync_at, last_status: new|ok|partial|failed, last_summary{added, updated, unchanged, missing, failed, notes[], failures[]}, last_error, running, progress{done,total}}`.

| 메서드·경로 | 권한 | 설명 |
|---|---|---|
| GET `/knowledge-bases/{kb}/sources` | 소유자·관리자·제작자·운영자 | 소유 소스 목록(가져오는 중이면 진행 상황) |
| POST `/knowledge-bases/{kb}/sources` `{type, name?, config, schedule?, sync_now?=true}` | 소유자·관리자·제작자 | 만들고 바로 가져오기 시작 |
| PATCH `/knowledge-bases/{kb}/sources/{sid}` `{name?, config?, schedule?}` | 소유자·관리자·제작자 | 이름·설정·매일 동기화 |
| DELETE `/knowledge-bases/{kb}/sources/{sid}?delete_documents=false` | 소유자·관리자·제작자 | `true`면 이 소스로 가져온 문서도 삭제 |
| POST `/knowledge-bases/{kb}/sources/{sid}/sync` | 소유자·관리자·제작자 | 지금 동기화(202). 이미 도는 중이면 409(20분 넘게 멈춘 것은 다시 시작 가능) |

`config`:
- **web**: `{url, depth 0~2, max_pages 1~50, include[], exclude[]}`. 같은 도메인만, `robots.txt` 준수(없으면 전체 허용, `Crawl-delay` 최대 5초), 정규 주소(조각·`utm_*`·꼬리 슬래시 정리, `<link rel=canonical>`)로 중복 제거, 쪽당 글 20만 자·응답 1MB 제한, 쪽 사이 0.3초(`GENIO_CRAWL_DELAY_SECONDS`). 모든 요청은 `safe_http`(사설 IP·localhost 차단, 리다이렉트 재검사).
- **notion**: `{credential_id(커넥터 'notion'의 내부 통합 토큰), targets[주소 또는 32자리 id], include_children}`. `api.notion.com`만 호출(`Notion-Version: 2022-06-28`), 블록(깊이 3·500개까지)을 마크다운으로 변환, 데이터베이스는 안의 페이지를 모두 가져옴(최대 100쪽). `last_edited_time`이 같으면 블록을 다시 읽지 않는다. 토큰은 응답·기록에 나오지 않는다.
- **google**: `{urls[], name?}`. `docs.google.com`의 문서(txt)·시트(csv → `머리글: 값` 줄)·슬라이드(txt), `drive.google.com` 파일(PDF·텍스트). 로그인 화면(HTML)이나 401·403·404면 "링크가 있는 모든 사용자로 공유" 안내와 함께 실패. 개인 드라이브(OAuth)는 범위 밖.

동기화는 Celery(`genio.sync_kb_source`)에서 돌고, 같은 쪽은 문서를 늘리지 않으며 내용 해시가 바뀐 쪽만 다시 임베딩한다. 가져오기 기록은 `doc_metadata`의 밑줄 키(`_source_id`·`_source_key`·`_content_hash`·`_edited`)에 두며 화면·검색 결과·꼬리표 수정에서 숨기고 보존한다. `schedule=daily`는 beat(`genio.sync_due_sources`, 1시간마다)가 23시간 지난 소스를 다시 동기화한다. 문서의 `source`는 `web`·`notion`·`google`.

### 외부 지식베이스
| 메서드·경로 | 권한 | 설명 |
|---|---|---|
| POST `/workspaces/{ws}/knowledge-bases` `{name, kind:"external", external:{endpoint, knowledge_id, credential_id?}}` | 소유자·관리자·제작자 | 외부 지식베이스 만들기. `credential_id`는 이 워크스페이스의 'HTTP 인증 정보'(Bearer 토큰). 목록·상세에 `kind`가 나온다 |
| POST `/workspaces/{ws}/knowledge-bases/external/test` `{endpoint, knowledge_id, credential_id?, query?}` | 소유자·관리자·제작자 | 저장 전 연결 시험 `{ok, message, hint, records, ms, sample[]}` |
| POST `/knowledge-bases/{kb}/external/test` | 소유자·관리자·제작자 | 저장된 연결 시험(일반 지식베이스면 409) |
| PUT `/knowledge-bases/{kb}/external` `{endpoint, knowledge_id, credential_id?}` | 소유자·관리자·제작자 | 연결 고치기 |

검색은 Dify External Knowledge API 모양이다. `POST {endpoint}/retrieval`(끝의 `/retrieval`은 겹치지 않게 정리) · `Authorization: Bearer <토큰>` · 본문 `{"knowledge_id", "query", "retrieval_setting": {"top_k", "score_threshold"}}` → `{"records": [{"content", "score", "title", "metadata"}]}`. 결과는 일반 검색과 같은 모양(`content`·`matched`·`score`·`filename`(=title)·`metadata`, `external: true`)이라 `knowledge_search` 단계(`results`·`context`)와 검색 시험·에이전트가 그대로 쓴다. 외부 지식베이스에는 문서 올리기·URL 가져오기·질문답 표·소스·다시 나누기·미리 보기·튜닝이 409로 막힌다. 호출은 `safe_http`를 거치므로 사설망 주소는 `GENIO_ALLOW_PRIVATE_NETWORK` 없이는 막힌다.

### 검색 튜닝
| 메서드·경로 | 권한 | 설명 |
|---|---|---|
| GET `/knowledge-bases/{kb}/tuning` | 소유자·관리자·제작자·운영자 | `{questions[], last_run, estimate, current(검색 설정), max_questions}` |
| PUT `/knowledge-bases/{kb}/tuning/questions` `{questions:[{id?, question, expect_keyword, expect_document_id}]}` | 소유자·관리자·제작자 | 최대 30개. 질문마다 `expect_keyword`나 `expect_document_id`가 하나 이상 있어야 하고, 문서는 이 지식베이스의 것이어야 한다 |
| POST `/knowledge-bases/{kb}/tuning/run` `{include_rerank?, confirm_rerank?}` | 소유자·관리자·제작자 | 조합 비교. 재정렬은 `confirm_rerank=true`가 있어야 한다(없으면 422 비용 안내) |

조합: 검색 방식 3(vector·keyword·hybrid) × 개수 3(3·5·8) = 9, 재정렬을 켜면 방식마다 5개 재정렬 조합 3개를 더해 12. 방식마다 검색을 한 번(8개)만 하고 3·5·8개 자르기는 같은 결과로 계산한다(점수 기준은 지금 설정). 응답 `{at, questions, include_rerank, threshold, rows[{method, top_k, rerank, hit_rate, hits, avg_top_score, avg_ms, is_best, is_current}], best, current_row, suggested_threshold, errors, truncated}`. 적중률 = 정답(낱말 포함 또는 지정 문서)이 상위 k개 안에 있는 질문 비율, 가장 좋음 = 적중률 → 평균 최고 점수 → 평균 시간 순. `current_row`는 지금 설정(개수가 8 넘으면 8로)을 같은 결과로 계산한 비교 기준. 적용은 기존 `PATCH /knowledge-bases/{kb}`의 `settings.retrieval`을 쓴다. 150초가 넘으면 `truncated`.

### 지식 사용 한도
| 메서드·경로 | 권한 | 설명 |
|---|---|---|
| GET `/workspaces/{ws}/knowledge/usage` | 소유자·관리자·제작자·운영자 | `{usage{documents, bytes}, limits{max_documents, max_total_mb, max_writes_per_min}, can_edit, labels}` |
| PUT `/workspaces/{ws}/knowledge/limits` `{max_documents?, max_total_mb?, max_writes_per_min?}` | 소유자·관리자 | 0 = 제한 없음. `workspace.settings.knowledge_limits`에 저장 |

기본 한도는 문서 2,000개·전체 2,048MB·분당 120번. 파일 올리기·웹 주소·질문답 표·소스 만들기·소스 동기화(문서마다)가 한도를 지키며, 넘는 새 문서만 막는다(문서·크기 409, 분당 429, 두 줄 안내). 이미 있는 문서는 그대로 둔다.

## v0.8 MCP 클라이언트·API 도구·연동 (ADR 0012)
외부 MCP 서버와 OpenAPI로 가져온 API를 흐름 단계(`mcp_tool`·`api_tool`)와 에이전트에서 도구로 쓴다.
둘 다 **연결 정보**(`connector_credentials`)에 암호화해 저장하므로 DB 마이그레이션은 없다.
- `mcp_server`: 항목(market-items)은 동작 없는 `credential_only`. 값 `url`·`token`·`header_name`(모두 암호화, 응답에는 `****abcd`).
- `api_tool_set`: 값 `operations`(도구 목록 JSON, 300KB 이하)·`base_url`·`auth_type`·`auth_credential_id`(HTTP 인증 정보 id). 인증 비밀값은 여기에 없다.
- 두 종류 모두 처음 만들 때 이 워크스페이스에 자동으로 설치된다.

### MCP 서버
| 메서드 | 경로 | 권한 | 설명 |
|---|---|---|---|
| GET | `/workspaces/{ws}/mcp/servers` | 제작자 이상 | `[{id, name, host, has_token, created_at}]`(주소 전체는 비밀이 섞일 수 있어 호스트만) |
| POST | `/workspaces/{ws}/mcp/servers` | 소유자·관리자 | `{name, url, token?, header_name?}` → 201 `{id, name, host, has_token}`. 최대 30개. 주소는 http(s)만, 헤더 이름은 영문·숫자·하이픈 |
| GET | `/workspaces/{ws}/mcp/servers/{id}/tools?refresh=` | 제작자 이상 | 서버에 붙어 도구 목록을 읽는다 `{ok, message, tools[{name, description, input_schema}]}`. 실패해도 200이고 `ok=false`(비밀값 마스킹). 기본은 60초 캐시, `refresh=1`은 다시 연결 |
| POST | `/workspaces/{ws}/connectors/credentials/{id}/test` | 제작자 이상 | 공통 연결 테스트. `mcp_server`는 도구 목록을 읽어 `연결됐어요. 도구 N개: …`를 돌려준다 |

- 삭제는 공통 `DELETE /workspaces/{ws}/connectors/credentials/{id}`(소유자·관리자).
- 프로토콜: Streamable HTTP JSON-RPC 2.0. `initialize`(요청 규격 2025-06-18, 서버가 2025-11-25·2025-06-18·2025-03-26·2024-11-05 중 하나로 답하면 받아들임) → `notifications/initialized` → `tools/list`(`nextCursor`로 최대 10쪽, 도구 200개·설명 500자·스키마 2만 자 상한) · `tools/call`.
  - 응답은 `application/json` 또는 `text/event-stream` 한 번의 답. `Mcp-Session-Id`가 오면 이후 요청에 붙이고, 404면 한 번만 새 세션으로 다시 시작한다. 끝나면 DELETE로 세션을 닫는다(실패해도 무시).
  - 모든 요청은 `safe_http`를 거친다(사설 IP·localhost 차단, 15초, 응답 1MB). 인증 실패(401·403)·MCP 주소가 아님(404·405·406·415)·규격 불일치·JSON-RPC 오류는 두 줄 한국어 오류다.
  - 결과 정리: `{text, content[], structured, is_error}`. 이미지·오디오 데이터는 싣지 않고 길이만 적는다. 서버가 되돌려 보낸 주소·토큰은 `****abcd`로 가린다.

### API 도구(OpenAPI)
| 메서드 | 경로 | 권한 | 설명 |
|---|---|---|---|
| POST | `/workspaces/{ws}/api-tools/preview` | 제작자 이상 | `{url}` 또는 `{text}`(JSON·YAML 중 하나만) → `{title, version, base_url, operations[], total, truncated}`. 저장하지 않는다 |
| POST | `/workspaces/{ws}/api-tools` | 소유자·관리자 | `{name, url\|text, base_url?, selected[], auth_type: none\|bearer\|basic\|header, auth_credential_id?}` → 201 `{id, name, tools, base_url}`. 최대 20묶음 |
| GET | `/workspaces/{ws}/api-tools` | 제작자 이상 | `[{id, name, base_url, tools, auth_type, created_at}]` |
| GET | `/workspaces/{ws}/api-tools/{id}` | 제작자 이상 | 도구 목록(인증 값 없음). 흐름 단계가 도구·값 칸을 만들 때 쓴다 |

- 명세 1MB 이하, OpenAPI 3.x만, 도구(연산) 200개 이하(넘으면 앞의 200개만 미리 보기에 나오고 `truncated=true`), 같은 문서 안의 `$ref`(`#/…`)만 풀고 깊이 6을 넘거나 바깥 참조는 빈 객체로 바꾼다. 쿠키 파라미터와 JSON이 아닌 본문은 무시한다.
- `auth_type`이 `none`이 아니면 `auth_credential_id`는 같은 워크스페이스의 `http_credentials` 연결 정보여야 한다(아니면 422).
- 호출은 HTTP 단계와 같은 길(`safe_http` + `auth_headers`)로 나간다. 경로 값은 주소 조각으로 안전하게 바꾸고(`quote(safe="")`), 빠진 필수 값·필수 본문은 한국어 오류다.

### 새 단계
| 타입 | 이름 | 설정 | 출력 |
|---|---|---|---|
| `mcp_tool` | 외부 도구 호출(MCP) | `credential_id`(mcp_server), `tool`, `arguments`(값 끌어오기 가능), `fail_on_tool_error` | `text`, `content`, `structured`, `is_error` |
| `api_tool` | API 도구 호출 | `tool_set`(api_tool_set), `operation`, `params`, `body`, `fail_on_error_status` | `status`, `ok`, `body`, `text` |

- 그래프 검증: 두 단계의 연결 정보 칸이 없는 id이거나 종류가 다르면 오류.
- 에이전트 단계 도구에 `{"type":"mcp","credential_id":…,"tools":["이름",…]}`를 쓰면 그 서버의 도구를 AI가 스스로 부른다(이름을 비우면 앞의 20개).
- 실행 기록의 단계 설명(`summary`)에 두 단계의 한 문장 설명이 들어간다.

### 새 마켓 커넥터 12개와 템플릿 3개
- 커넥터: `twilio`·`sendgrid`·`mailgun`·`google_chat`·`zendesk`·`freshdesk`·`shopify`·`salesforce`·`clickup`·`monday`·`solapi`·`naver_sens`. 기본 항목 `mcp_server`·`api_tool_set`을 더해 마켓은 69개.
- 서명이 필요한 서비스(솔라피·SENS)를 위해 커넥터 `net`에 `sign_hmac_sha256(key, message, encoding="hex"|"base64")`, `now_ms()`, `now_iso()`, `random_hex(n)`이 생겼다(번들은 hmac·time 모듈을 직접 쓸 수 없는 허용 목록 유지).
- 템플릿: `tpl_inquiry_zendesk_slack`(병렬), `tpl_order_sms_notify`(병렬), `tpl_shopify_orders_mail`.
- `safe_http` 응답 헤더 허용 목록에 `mcp-session-id`가 추가됐다.
- 새 의존성: `PyYAML>=6`.

## v0.8 Dify 앱 가져오기 (ADR 0012)
| 메서드·경로 | 권한 | 설명 |
|---|---|---|
| POST /workspaces/{ws}/apps/import-dify | 소유자·관리자·제작자 | multipart `file`(`.yml`·`.yaml`·`.json`, 2MB 이하)와 선택 `project_id`, 또는 JSON `{text, project_id?}`. 새 앱(초안)과 변환 보고서를 돌려준다(201) |

응답 `{app, report}`:
- `app`: 만들어진 앱 상세(`draft_graph` 포함). 앱은 늘 초안이다.
- `report`: `{mode, dify_version, converted[{node, label, dify_type, genio_type}], needs_attention[{node, label, message}], unsupported[{node, label, dify_type, message}], warnings[], validation_errors[{node, message}], stats{converted, needs_attention, unsupported, validation_errors}}`. `validation_errors`는 변환 뒤 검증기를 한 번 돌린 결과이고, 가져오기를 막지 않는다.

오류(두 줄 문구): 422 YAML을 읽지 못함·Dify 파일이 아님·별칭(`*a`) 사용·지원하지 않는 앱 종류(`rag-pipeline` 등)·단계 300개 초과, 413 2MB 초과, 404 없는 프로젝트, 403 권한 없음.

보안: `yaml.safe_load` 기반 로더에 별칭을 금지했다(부풀리기 공격 방지). 비밀 환경 값(`secret`)과 웹 요청 인증 키는 옮기지 않고 보고서에 '다시 넣어 주세요'로 적는다.

### 앱 종류 → 제니오 앱
| Dify `app.mode` | 제니오 | 내용 |
|---|---|---|
| `workflow` | 흐름 앱(workflow) | `workflow.graph`를 단계·연결로 변환 |
| `advanced-chat`(챗플로우) | 챗 앱(chat) | 같은 변환 + 입력 단계의 첫 칸이 `message`(= `sys.query`) |
| `chat`(챗봇) | 챗 앱 | `model_config`로 입력 → (지식 검색) → AI 답변 → 결과 흐름을 만든다 |
| `agent-chat` | 챗 앱 | 입력 → (지식 검색) → 에이전트 → 결과 |
| `completion` | 흐름 앱 | 입력 칸(`user_input_form`) → AI 답변 한 단계로 바꾸고 알림을 남긴다 |
| 그 밖(`rag-pipeline` 등) | — | 422 |

### 단계 대응표 (Dify `data.type` → 제니오)
| Dify | 제니오 | 비고 |
|---|---|---|
| `start` | `input`(id `n1`) | 변수 → 입력 칸(text-input·paragraph·select→글, number→숫자, checkbox→참거짓, file·file-list→파일). select의 선택지는 이름에 적는다 |
| `llm` | `llm` | 시스템/사용자 메시지 → `system`/`prompt`, `{{#context#}}` → 지식 검색 결과, memory → 대화 기억, vision → `images`, 온도. 모델 이름은 메모로 남기고 기본 AI 연결을 쓴다 |
| `knowledge-retrieval` | `knowledge_search` | 지식베이스는 옮겨지지 않아 `kb_id`를 비운다(보고서에 안내). top_k·점수 기준은 옮긴다 |
| `if-else` | `condition` | 비교 연산자를 조건식으로(`contains`·`start with`·`is`·`=`·`>`·`empty`·`in` 등). `and`/`or` 지원. 출구 `false` → `else` |
| `code` | `code` | python3·javascript. `def main(...)`/`function main({...})`를 부르는 줄을 덧붙인다 |
| `http-request` | `http` | method·url·params(주소 뒤에 붙임)·headers·json/raw 본문. 폼 본문은 JSON으로. 인증 키는 안 옮김 |
| `template-transform` | `template` | 변수 이름을 `{{단계.값}}` 경로로 바꿈 |
| `question-classifier` | `question_classifier` | 분류 id를 출구 이름으로 그대로 쓴다 |
| `parameter-extractor` | `parameter_extractor` | 형식 string·number·bool·array를 옮김 |
| `variable-aggregator`(옛 이름 `variable-assigner`) | `variable_aggregator` | 그룹 기능은 옮기지 못함 |
| `assigner` | `variable_assigner` | over-write·set·append·extend·clear. 계산형 연산(`+=` 등)은 옮기지 못함 |
| `document-extractor` | `document_extractor` | |
| `list-operator` | `list_operator` | 거르기는 첫 조건만, 정렬·개수 제한 |
| `answer`·`end` | `output` | `end`의 여러 출력은 "이름: 값" 줄로 |
| `iteration` | `iteration` | 안에 단계가 하나(llm·template-transform·http-request)일 때만. `{{#반복.item#}}` → `{{item}}` |
| `loop` | `loop` | 같은 조건. 멈춤 조건은 옮기지 못함 |
| `agent` | `agent` | 지시·요청·최대 횟수. 도구는 옮기지 못함 |
| `human-input` | `approval`(승인/반려 갈래) | 입력 칸이 있으면 `ask_person`. 버튼은 앞의 둘만 승인·반려로 |
| `tool`·`trigger-*`·그 밖 | 꺼 둔 `template` 자리 표시 | 연결을 그대로 남겨 흐름 모양을 보이게 하고 `unsupported`에 적는다 |
| 캔버스 메모(`custom-note`) | 메모(`notes`) | Lexical JSON이면 글자만 |

변수 참조: `{{#노드.값#}}`·`value_selector`를 `{{노드.값}}`으로 바꾼다. `sys.query` → `{{n1.message}}`, `sys.files`·시작 파일 값 → 입력 단계의 파일 칸, `env.x` → `{{env.x}}`, `conversation.x` → `{{conv.x}}`. 값 이름이 다른 곳은 함께 바꾼다(`knowledge-retrieval.result` → `context`, `http-request.status_code` → `status`, `iteration.output` → `results`). `sys.user_id` 같은 제니오에 없는 시스템 값은 빈 값으로 바꾸고 알린다.

앱 기능: `opening_statement`·`suggested_questions`·`suggested_questions_after_answer`(→ 이어질 질문)·`retriever_resource`(→ 출처)·`speech_to_text`/`text_to_speech`·`file_upload`·`sensitive_word_avoidance`(키워드 방식 → 금지어)를 옮긴다. 환경 변수는 앱 환경 값으로(비밀은 값 없이). 대화 변수의 처음 값은 옮기지 않는다.

확인 한계: 시험 자료는 Dify DSL(0.1.x)을 알고 있는 대로 직접 쓴 것이다. 실제 Dify에서 내보낸 파일로는 아직 확인하지 못했다.

## v0.8 파일 저장소·코드 샌드박스 (ADR 0012)

기존 API의 요청·응답 모양은 바뀌지 않는다. 바뀐 것은 아래와 같다.

- **파일 저장소** — 환경 값 `GENIO_STORAGE=db|disk|s3`(기본 `db`). 파일을 올리는 API(`POST /workspaces/{ws}/files`, 지식베이스 문서 올리기, 웹 페이지·질문·답 표 가져오기)와 읽는 곳(흐름의 파일 입력, 공유 썸네일 `GET /public/apps/{token}/share-image`, 문서 처리)은 모두 저장소 서비스(`services/storage.py`)를 거친다. 응답에는 저장 위치가 드러나지 않는다.
  - DB: `files`·`documents`에 `storage`(`db|disk|s3`, 기본 `db`)와 `storage_key`(저장소 안의 키) 두 칸이 생겼다(마이그레이션 0013, 추가만). 저장소가 `db`가 아니면 `content`는 비어 있다(`files`는 빈 바이트, `documents`는 NULL).
  - 저장소에 문제가 생기면 두 줄 오류가 나온다: 읽기·쓰기 실패 503("파일 저장소(S3)에 연결하지 못했어요 / 저장소 주소·버킷·접근 키 설정을 확인해 달라고 관리자에게 요청하세요"), 저장된 파일이 없으면 404("저장된 파일을 찾지 못했어요 / 파일을 다시 올려 주세요"). 오류 문장에는 주소·키가 들어가지 않는다.
  - 문서·지식베이스를 지우면 저장소의 본문도 지운다. 옮기기·되돌리기·고아 파일 찾기: `scripts/migrate_files_to_storage.py`(docs/runbook.md).
- **관리 > 시스템 상태**(`GET /admin/status`)의 `items`에 **"코드 실행"** 한 줄이 늘었다.
  - 격리 서버를 쓰지 않으면 `status: "unknown"`, `mode: "in-process"`.
  - 켜 두었으면 응답 시간과 함께 `ok`(500ms 미만)·`warn`, 응답이 없으면 `error`(`mode: "sandbox"`, `ms`).
- **코드 실행 격리 서버** — 별도 컨테이너(`apps/sandbox`), 제니오 API가 아니라 api·worker가 내부망에서만 부른다. 이 서버의 계약:
  - `GET /health` → `{"status":"ok"}`(인증 없음, 다른 정보 없음)
  - `POST /run` 헤더 `X-Sandbox-Key`, 본문 `{"language":"python|javascript","code":str,"inputs":{...},"timeout":1~60}` → `{"ok":true,"result":{...}}` 또는 `{"ok":false,"kind":"error|timeout|memory|output","error":str}`(HTTP 200). 인증 실패 401, 키 미설정 503(`kind:"config"`), 본문 1MB 초과 413, 형식 오류 422, 동시 실행 초과 429(`kind:"busy"`).
  - 제니오 쪽은 `GENIO_SANDBOX_URL`이 있을 때만 이 서버를 부르고, 없으면 지금처럼 서버 안에서 실행한다. 사용자가 고른 주소는 절대 쓰지 않는다(운영자가 정한 환경 값만).
- **오류 수집(Sentry)** — `SENTRY_DSN`이 있을 때만 켜진다. 사용자·요청 정보와 지역 변수는 보내지 않고 글 속 비밀값은 `****`로 가린다.

## v0.8 검색창·스니펫·웹앱 로고·IP 제한·공개 API 문서

마이그레이션 `0014`(추가만): `snippets` 테이블, `deployments.allowed_ips`(JSON 목록, 기본 `[]`). `0013`은 다른 작업의 것이다.

### 전체 검색창(Ctrl+K)
| 요청 | 권한 | 설명 |
|---|---|---|
| GET /workspaces/{ws}/search?q=&limit= | 워크스페이스 멤버 | 앱·프로젝트·지식베이스·데이터 표·연결 정보·마켓·화면(메뉴)을 묶음별로. `limit`은 묶음마다(1~20, 기본 6), `q`는 100자까지. 검색어가 비면 화면 바로 가기만 |

- 응답: `{query, groups:[{kind, label, items:[{id, title, subtitle, to, icon?}]}]}`. `to`는 화면 주소다.
- 역할에 맞는 것만 나온다.
  - 사용자(member): 배포된 앱만(공유 화면 주소 `/share/…`). 지식베이스·연결 정보·관리 화면은 없다.
  - 운영자: 지식베이스와 앱 실행 화면. 연결 정보는 없다.
  - 제작자 이상: 연결 정보와 빌더. 관리 화면은 소유자·관리자만.
  - 비공개 프로젝트 안의 항목은 볼 수 없는 사람에게 존재도 드러내지 않는다. 연결 정보는 이름만, 비밀값은 없다.
- 검색어의 `%`·`_`는 글자 그대로 찾는다.

### 스니펫(단계 묶음)
| 요청 | 권한 | 설명 |
|---|---|---|
| GET /workspaces/{ws}/snippets | 워크스페이스 멤버 | 목록(그래프 없이). `node_count`, `node_types`, `reselect`, `outer_refs` |
| GET /workspaces/{ws}/snippets/{id} | 워크스페이스 멤버 | 하나(그래프 포함) |
| POST /workspaces/{ws}/snippets `{name, description?, nodes, edges}` | 제작자 이상 | 저장. 워크스페이스당 200개, 한 묶음 단계 50개까지 |
| PATCH /workspaces/{ws}/snippets/{id} `{name?, description?}` | 제작자 이상 | 이름·설명 |
| DELETE /workspaces/{ws}/snippets/{id} | 제작자 이상 | 지우기(이미 끼워 넣은 단계는 그대로) |

저장할 때 서버가 정리한다.
- 고른 단계끼리 이어진 연결만 남긴다. 시작(input) 단계는 넣을 수 없다(422).
- `credential_id`·`kb_id`·`table_id`·`app_id`·`assignee_user_id`·`file_id`는 비운다(`reselect`에 칸 이름을 남긴다).
- 고르지 않은 바깥 단계의 값 `{{n5.text}}`는 `{{__outer.n5.text}}`로 바꾼다. 끼워 넣은 흐름에 같은 id의 단계가 있어도 엉뚱한 값이 조용히 이어지지 않고 검사에서 '없는 단계'로 드러난다.
- 끼워 넣기는 화면(캔버스)이 새 id로 바꿔 한가운데에 놓는다(붙여넣기와 같은 함수).
- 활동 기록: `snippet.create`·`snippet.update`·`snippet.delete`.

### 웹앱 로고
- `deployments.appearance.share_logo`(파일 id). 올릴 때는 `POST /workspaces/{ws}/files` 뒤 `PATCH /deployments/{id}`로 `appearance.share_logo`를 넣는다.
- 허용: PNG·JPG·WEBP, 1MB 이하, 같은 워크스페이스의 파일. 아니면 422(두 줄).
- 공개 경로 `GET|HEAD /public/apps/{token}/share-logo`가 그림을 준다(`Cache-Control: public, max-age=300`, `nosniff`). 로고가 없으면 404이고 화면은 기본 아이콘을 쓴다. IP 제한이 있으면 이 경로도 막힌다.

### IP 접근 제한
| 요청 | 권한 | 설명 |
|---|---|---|
| PATCH /deployments/{id} `{allowed_ips:[…]}` | 제작자 이상 | 허용 IPv4·IPv6·CIDR 목록. `[]`이면 제한 없음. 최대 50개 |
| POST /apps/{id}/deployments `{…, allowed_ips}` | 제작자 이상 | 처음부터 제한을 걸어 배포 |
| GET /me/ip | 로그인한 사용자 | 지금 요청한 곳의 IP. 제한을 넣을 때 '내 IP 추가'가 쓴다 |

- 한 대 주소는 `/32`(IPv6는 `/128`) 없이 저장한다. 호스트 비트가 있는 CIDR(`203.0.113.5/24`)은 대역(`203.0.113.0/24`)으로 정리한다. 잘못된 값은 422(두 줄).
- 요청한 사람의 IP는 `client_ip()`로 구한다. 믿을 수 있는 프록시(`GENIO_TRUSTED_PROXIES`)가 붙인 `X-Forwarded-For`의 오른쪽부터 처음 만나는 믿을 수 없는 주소를 쓰므로, 바깥에서 헤더를 꾸며도 우회할 수 없다. `::ffff:1.2.3.4`는 IPv4로 본다. 주소를 알 수 없으면 제한이 있을 때 거절한다.
- 막으면 403 `이 주소에서는 이 앱을 열 수 없어요.`(두 줄). 허용 목록은 알려 주지 않는다.
- 적용 범위: `/api/v1/public/apps/{token}/…` 전체(앱 정보·챗·실행 폼·결과·대화 기록·파일 올리기·피드백·위젯 스크립트·일괄 실행·로고). 앱 전체(전역) 의존성 `public_ip_guard`라 새로 생기는 공개 경로도 자동 적용된다. 제외: `share-image`(메신저 로봇이 가져가는 썸네일). 서비스 API(키)·웹훅·MCP는 이 제한과 별개다.
- 제한이 있는 배포는 메신저 링크 미리보기에도 앱 이름·소개가 나가지 않고 일반 소개만 나간다.
- 활동 기록: `app.deploy_ips`(`{count}`). 같은 값을 다시 저장하면 기록하지 않는다.

### 공개 API 문서(OpenAPI)와 명령줄 도구
| 요청 | 권한 | 설명 |
|---|---|---|
| GET /openapi-public.json | 로그인 불필요 | 밖에서 부를 수 있는 API만 담은 OpenAPI 3 문서(5분 캐시) |

- 담는 경로: `/api/v1/public/apps/{token}/…`(공유 링크 앱), `/api/v1/service/…`(서비스 API·MCP), `/api/v1/hooks/{token}`(외부에서 받기). 묶음 이름(tags)은 서버가 붙인다: 공유 링크 앱(챗·입력 폼), 서비스 API(앱 API 키), 외부에서 받기(웹훅), MCP 서버.
- 담지 않는 것: `/workspaces`, `/auth`, `/admin`, 실행 승인 같은 내부·관리 경로, 썸네일·로고·위젯 스크립트·미리보기 HTML. 쓰는 스키마만 `components.schemas`에 남긴다.
- 화면 `/api-docs`(로그인 없이 열림, 앱의 API 화면과 사용설명서에서 링크)가 이 문서를 방식·주소·매개변수·보내는 내용·응답·curl 예시로 보여 준다.
- 명령줄 도구 `scripts/genio_cli.py`(파이썬 표준 라이브러리만): 앱 API 키 하나가 앱 하나에 묶여 있어 '앱 목록'은 없다.

```bash
export GENIO_URL=https://genio.example.com   # 기본값 http://127.0.0.1:5190
export GENIO_API_KEY=gk-xxxxxxxx
python scripts/genio_cli.py info                          # GET  /service/parameters
python scripts/genio_cli.py run -i city=도쿄 -i days:=3   # POST /service/workflows/run (끝까지 기다림)
python scripts/genio_cli.py chat "휴가 규정 알려줘" -c <conversation_id>   # POST /service/chat-messages
python scripts/genio_cli.py runs --limit 5 --status failed   # GET /service/runs ('기록 읽기' 권한)
python scripts/genio_cli.py run-status <run_id>          # GET /service/runs/{id}
python scripts/genio_cli.py run gk-xxxxxxxx -i name=김    # 키를 첫 인자로 줘도 된다
```
- 입력값: `이름=글`은 글, `이름:=JSON`은 JSON 값. `--json`은 결과를 그대로 출력.
- 오류는 서버의 `{message, hint}`를 두 줄로 보여 주고, 종료 코드는 0 성공 · 1 API 오류 · 2 사용법 오류.

### 공통 화면 부품
- 모든 대화상자(`components/ui/dialog.tsx`)는 Tab 키를 창 안에 가두고, 열릴 때 본문 첫 입력으로 포커스를 옮기며, 닫으면 열기 전 자리로 돌려준다(`lib/useFocusTrap.ts`).
- 단축키는 `lib/shortcuts.ts`가 한곳에서 관리한다. 단축키 보기(Shift+?)와 캔버스 도움말이 같은 목록을 쓴다.

## v0.9 서비스 이벤트 트리거·사람 단계 전달·시간 초과

### 서비스 이벤트로 시작(ADR 0013)
자동 실행(트리거)의 새 종류 `kind: "service"`. 서비스가 보내는 알림을 받아 흐름을 시작한다. 만들기·고치기·지우기·주소 다시 만들기·받은 값 보기는 기존 `/apps/{id}/triggers`, `/triggers/{id}` 경로를 그대로 쓴다(제작자 이상).

| 요청 | 권한 | 설명 |
|---|---|---|
| GET /apps/{id}/service-presets | 제작자 이상 | 서비스 6개의 설정 안내·이벤트 칩·비밀값 종류(`key_origin`·`key_label`)·샘플 받은 값 `[{key, name, key_origin, key_label, events[{id,label}], instructions[], sample{headers,body}}]` |
| POST /apps/{id}/triggers `{kind:"service", name?, config:{service, events?, mapping?, include_bot?, version?}, secret?}` | 제작자 이상 | `key_origin=generated`(GitHub·Telegram·Jira·Typeform)는 제니오가 비밀값을 만들어 **응답에서 한 번만** `secret`으로 준다. `provider`(Slack 서명 비밀값·Shopify 앱 비밀 키)는 `secret`을 꼭 보내야 하고(8자 이상) 응답에 되돌려 주지 않는다. 응답 `url`은 `/api/v1/events/{token}` |
| POST /triggers/{id}/secret `{secret?}` | 제작자 이상 | generated는 새로 만들어 한 번 보여 준다(예전 값은 바로 거절). provider는 `secret`으로 바꿔 넣는다(없으면 422) |
| POST /triggers/{id}/test-sample | 제작자 이상 | 서비스의 샘플 받은 값으로 실행한다(서명 확인만 건너뜀, 이벤트 읽기·값 연결은 그대로). `201 {run, input}`. 받은 값 목록에 '샘플로 시험'으로 남는다 |
| POST /events/{token} | 로그인 불필요, 서명이 권한 | 서비스가 부르는 주소. 성공 `202 {run_id, status}`, 걸러냄·재전송 `200 {ignored: 이유}`, Slack 주소 확인 `200 {challenge}`, 서명 틀림 `401`, JSON 아님 `400`, 256KB 초과 `413`, 모르는·꺼진 주소 `404`, 트리거당 분당 120번 초과 `429` |

- `config`: `service`(slack·github·shopify·telegram·jira·typeform), `events`(이벤트 칩 id 목록, 비우면 모두 받음), `mapping`(`{입력 칸 이름: 받은 값 위치}`, 위치는 `issue.title`·`answers[0].text` 같은 점·대괄호 표기, 30개까지), `include_bot`(Slack 봇 메시지도 받기), `version`.
- 실행 입력: `message`(한 줄 요약), `service`, `event`, 그리고 `mapping`으로 고른 값(없는 위치는 빈 글, 목록·묶음은 JSON 글, 8,000자까지). 실행의 방식(`trigger`)은 `service`.
- 서명 방식과 이벤트 칩:

| 서비스 | 서명 | 이벤트 칩 | 재전송 구분 |
|---|---|---|---|
| Slack | `X-Slack-Signature` = `v0=` + HMAC-SHA256(`v0:{X-Slack-Request-Timestamp}:{본문}`), 시각 차이 5분 안 | message · app_mention · reaction_added | `event_id` |
| GitHub | `X-Hub-Signature-256` = `sha256=` + HMAC-SHA256(본문) | issues:opened · issues:closed · pull_request:opened · pull_request:closed · issue_comment:created · push · release:published (`ping`은 건너뜀) | `X-GitHub-Delivery` |
| Shopify | `X-Shopify-Hmac-Sha256` = base64(HMAC-SHA256(본문)) | orders/create · orders/paid · orders/cancelled · customers/create · refunds/create | `X-Shopify-Webhook-Id` |
| Telegram | `X-Telegram-Bot-Api-Secret-Token` = 비밀값(setWebhook의 secret_token) | message | `update_id` |
| Jira | `X-Hub-Signature`(`sha256=`+HMAC) 또는 `X-Genio-Secret` 헤더 또는 주소 뒤 `?secret=` | jira:issue_created · jira:issue_updated · comment_created | `X-Atlassian-Webhook-Identifier` |
| Typeform | `Typeform-Signature` = `sha256=` + base64(HMAC-SHA256(본문)) | form_response | `event_id` |

- 모든 비교는 일정 시간 비교(`hmac.compare_digest`)이고, 비밀값은 암호화해 저장하며 로그·오류·받은 값 목록에 남기지 않는다(서명·비밀 헤더는 받은 값 목록에서 뺀다).
- 같은 서비스 알림(재전송)은 10분 안에 한 번만 실행한다. 고르지 않은 이벤트·봇 메시지·ping·재전송은 실행을 만들지 않고, 받은 값 목록에 `걸러냄: 이유`로 남는다.
- Slack 주소 확인(`url_verification`): 비밀값이 있으면 서명을 확인한 뒤 `challenge`를 돌려준다. 비밀값을 아직 안 넣었으면 확인 응답만 하고 실행은 만들지 않는다.

### 사람 단계: 전달
| 요청 | 권한 | 설명 |
|---|---|---|
| GET /workspaces/{ws}/tasks/forward-targets | 운영자 이상 | 전달할 수 있는 `{users[{id,name,role}], roles[{id,name}]}`(이메일은 없음) |
| POST /workspaces/{ws}/tasks/{id}/forward `{to_user_id? , to_role?, comment?}` | 지금 처리할 수 있는 사람(담당자·소유자·관리자) | 사람(워크스페이스 멤버) **또는** 역할 하나로 담당을 바꾼다. 처리된 일은 409, 멤버가 아닌 사람·잘못된 역할·둘 다/둘 다 없음은 422 |

- 전달하면 담당이 바뀌어 보낸 사람은 더 처리할 수 없다(소유자·관리자는 계속 가능). 승인 일을 역할로 전달하면 그 역할이 승인할 수 있게 된다.
- 이력(`history`)에 `{at, via(forward|timeout), by_name, to_name, to_user_id, to_role, comment, notified}`가 쌓이고(최대 50개), 활동 기록에 `task.forward`가 남는다. 링크 화면(`/public/tasks/{token}`)에는 이력·내부 값이 나오지 않는다.
- 알림: 일을 만들 때 정한 알림 설정(이메일 연결 정보·슬랙 채널)이 있으면 전달받은 사람에게 보낸다. 이메일은 받는 사람이 그 사람(또는 그 역할 멤버, 20명까지) 메일로 바뀐다. 알림 설정이 없으면 받은 쪽 작업함에만 나타난다.
- 작업함 응답에 `timeout_mode`, `escalated`, `overdue`, `history`가 더해졌다.

### 사람 단계: 시간 초과·다시 알리기
승인·사람에게 묻기·할 일 맡기기 단계의 새 설정:

| 설정 | 설명 |
|---|---|
| `due_hours` | 기한(시간). 승인 단계에도 생겼다 |
| `on_timeout` | 기한이 지나면: `none`(계속 기다림, 기본) · `reject`(자동 반려) · `approve`(자동 승인) · `escalate`(올리기) · `continue`(정해 둔 값으로 계속) · `branch`('시간 초과' 길) |
| `timeout_escalate_to` | 올릴 곳: 역할 이름(owner·admin·builder·operator·member) 또는 사용자 id |
| `timeout_default` | `continue`일 때 답 대신 쓸 값 `{받을 칸 이름: 값}` |
| `remind_before_hours` | 기한 몇 시간 전에 한 번 다시 알림(기한보다 짧아야 함) |

- 처리는 워커 beat 작업 `genio.sweep_human_tasks`가 **5분마다** 한다(`services/tasks.sweep`). 기한이 지난 열린 일 중 `on_timeout`이 있고 실행이 승인 대기 중인 것만 처리한다.
  - `reject`: 승인 단계는 `approved=false`로 끝내고(반려 길이 있으면 그 길, 없으면 실행 실패 "정해 둔 시간 안에 승인되지 않아 자동으로 반려되어…"). 묻기·맡기기 단계는 실행을 실패로 끝낸다.
  - `approve`·`continue`: 승인은 `approved=true`. 묻기는 `timeout_default` 값(없는 칸은 빈 값)으로, 맡기기는 완료로 이어 간다.
  - `escalate`: 올릴 곳으로 전달하고 기한을 **같은 만큼 한 번** 늘린다(`via: timeout`, 이력). 올릴 곳이 없거나 올린 뒤에도 기한이 또 지나면 `reject`와 같이 처리한다.
  - `branch`: 단계의 `timeout` 출구로 이어 간다. 출구가 이어져 있지 않으면 실행이 실패한다.
- 시간 초과로 끝난 일은 사람이 처리한 것과 똑같이 `run.approval`에 결정(`decided_by_name: 시스템`, `decided_via: timeout`, `timed_out: true`, `timeout_mode`)을 적고 실행을 이어 가므로, 병렬 갈래·일괄 실행 안에서도 그대로 동작한다. 단계 출력에 `timed_out: true`가 들어간다.
- 검증: `on_timeout`·`remind_before_hours`는 `due_hours`가 있어야 하고, `escalate`는 `timeout_escalate_to`가 있어야 하며, `timeout` 출구는 `on_timeout: "branch"`인 사람 단계에서만 쓸 수 있다(한 곳으로만 이을 수 있음). 캔버스 카드에 "⏱ 기한 …" 한 줄과 노란 '시간 초과' 출구가 보인다. 빌더의 `connect`·`add_node`는 `handle: "timeout"`을 쓸 수 있다.
- 다시 알리기는 일마다 한 번만 보낸다(`rules.reminded`). 알림 설정이 없으면 보내지 않는다.
- DB: 마이그레이션 `0017`이 `human_tasks.rules`(JSON)·`human_tasks.history`(JSON)를 더한다(추가만, downgrade 있음).

## v0.9 동시 편집·댓글
ADR 0013. 마이그레이션 0015(`apps.draft_rev`·`updated_by`, `draft_snapshots`, `canvas_comments`).

### 작업본 번호와 저장 합치기
- 앱의 작업본(`draft_graph`)이 **어디서든**(캔버스 저장, 빌더 에이전트 툴, 버전 되돌리기, 가져오기) 바뀌어 저장되면 `draft_rev`가 1 오르고 `updated_by`가 적힌다(`models/draft_hooks.py`가 세션 `before_flush`에서 처리). 같은 내용을 다시 저장하면 번호를 올리지 않는다.
- 번호가 오를 때마다 그 흐름을 `draft_snapshots`에 쌓고(앱마다 최근 **20번**), 바뀌기 전 번호의 기록이 없으면 함께 남긴다.
- 커밋이 끝난 뒤에만 `draft_changed` 알림을 보낸다(롤백하면 보내지 않는다).
- `GET /apps/{id}`의 응답에 `draft_rev`가 들어 있다.

| 요청 | 권한 | 설명 |
|---|---|---|
| PUT /apps/{id}/draft `{graph, source?, base_rev?}` | 제작자 이상 | `base_rev`는 내가 불러온 작업본 번호. 없으면(옛 화면) 그대로 덮어쓴다. 번호가 서버와 같으면 그대로 저장. 다르면 **3자 합치기**: 겹치지 않는 변경은 자동으로 합쳐 `200 {…, merged: true}`로 저장하고, 같은 곳을 고쳤으면 `409`. 같은 앱을 동시에 저장하는 요청은 행 잠금으로 줄을 세운다. |

- 합치는 규칙(`services/graph_merge.py`): 기준(base)은 내 `base_rev` 때의 기록, 내 것(mine), 서버에 저장된 것(theirs)을 비교한다.
  - 단계·메모: 칸(`type`, `disabled`, `data.<키>`…) 단위로 비교해 **같은 칸을 둘 다 다르게 고친 경우만** 충돌. `position`·`width`·`height`는 충돌로 보지 않고 내 것.
  - 연결선: 한쪽만 더하거나 지우면 그대로, 같은 선을 서로 다르게 고쳤을 때만 충돌. 합친 뒤 없는 단계를 가리키는 선과 같은 연결(source·target·handle)이 겹치는 선은 지운다.
  - 한쪽이 지운 단계를 다른 쪽이 고쳤으면 충돌(`field: "*"`, 지운 쪽 값은 `null`). 둘 다 지우면 충돌 없음. 흐름 값(`variables`)은 키 단위로 비교한다.
- 충돌 응답(`409`): `{"detail": {"message", "hint", "conflict": {rev, stale, base, mine, theirs, merged, conflicts[{kind: node|edge|note|variable, node_id, field, label, base, mine, theirs}]}}}`.
  - `rev`는 지금 서버 번호. `merged`는 충돌 항목을 상대 값으로 둔 합친 결과. 화면이 항목마다 고른 쪽을 반영해 `rev`를 `base_rev`로 다시 보내면 저장된다.
  - 기준 기록이 없거나(20번 넘게 지남) 번호가 서버보다 크면 `stale: true`, `conflicts: []`: 자동으로 합칠 수 없다. 화면은 '상대 것으로 새로 불러오기' 또는 '내 것으로 덮어쓰기'(`rev`를 `base_rev`로 다시 저장)를 고르게 한다.
- 화면 구분: 요청 헤더 `X-Genio-Client`(탭마다 다른 값)가 알림의 `client_id`로 돌아가, 내가 한 변경은 내가 무시한다.
- 빌더 에이전트의 `graph_patch` 이벤트에 `draft_rev`가 함께 간다.

### 접속 표시와 알림 스트림
권한: 빌더를 열 수 있는 역할(소유자·관리자·제작자·운영자). 사용자 역할은 403, 다른 워크스페이스는 404.

| 요청 | 설명 |
|---|---|
| POST /apps/{id}/presence `{node_id?, editing?, leave?}` | 10초마다 '나 여기 있어요'. 이름·색은 서버가 정한다(본문으로 속일 수 없다). `editing`은 고칠 수 있는 역할만 켜진다. `leave: true`면 목록에서 뺀다. 응답 `{users[{user_id, name, color, node_id, editing, can_edit}]}`. 30초 동안 알려 오지 않으면 목록에서 빠진다. |
| GET /apps/{id}/presence | 지금 있는 사람 |
| GET /apps/{id}/presence/stream?max_seconds= | SSE 한 줄기. 이벤트 `hello`, `presence {users}`, `draft_changed {rev, user_id, client_id}`, `comment_changed {action, comment_id, node_id, user_id, client_id}`. 15초마다 keep-alive. 기본 1시간 뒤 끝나며 화면이 다시 이어 받는다. |

- 저장소: Redis(`genio:presence:{app}` 해시, `genio:app:{app}` pub/sub). Redis가 없으면 같은 프로세스 안에서만 전달한다(테스트·로컬).
- 알림은 '신호'다. 놓쳐도 화면이 다시 이어질 때(`hello`) 최신 작업본을 읽어 확인한다.

### 캔버스 댓글
| 요청 | 권한 | 설명 |
|---|---|---|
| GET /apps/{id}/comments?status=open\|resolved\|all&node_id= | 소유자·관리자·제작자·운영자 | 스레드 목록(뿌리 댓글마다 `replies`). 앱마다 최대 2,000개 |
| POST /apps/{id}/comments `{body≤2000, node_id?, x?, y?, parent_id?, mentions[]}` | 소유자·관리자·제작자 | 단계(`node_id`)나 캔버스 위치(`x`, `y`)에 단다. `parent_id`가 있으면 답글(단계·위치는 뿌리를 따르고, 답글에 답글은 422). 응답은 스레드 |
| PATCH /apps/{id}/comments/{cid} `{body, mentions?}` | 쓴 사람만 | 새로 넣은 사람만 다시 알린다 |
| DELETE /apps/{id}/comments/{cid} | 쓴 사람, 소유자·관리자 | 뿌리를 지우면 답글도 함께 |
| POST /apps/{id}/comments/{cid}/resolve · /reopen | 소유자·관리자·제작자 | 뿌리 댓글만(답글은 422) |
| GET /apps/{id}/collaborators | 소유자·관리자·제작자·운영자 | @멘션 후보 `[{id, name, role}]`(이메일은 보내지 않는다) |

- 멘션: `mentions`는 사용자 id 목록. 이 워크스페이스에서 빌더를 열 수 있는 사람만 인정하고(중복 제거, 최대 10명) 나 자신은 알리지 않는다. 불린 사람마다 활동 기록 `comment.mention`(`target_id`=불린 사람, `meta`={app_id, comment_id})이 남고, **시스템 메일이 설정돼 있으면** 앱 빌더 링크가 든 메일을 보낸다(1분에 10통까지, 보내기에 실패해도 댓글은 저장되고 비밀값은 어디에도 남기지 않는다).
- 다른 워크스페이스의 앱·댓글은 404. 다른 앱 주소로 이 댓글을 건드릴 수 없다.

## v0.9 이미지 만들기·파일 만들기·파일 내려받기

### 단계
| 단계 | 설정 | 출력 |
|---|---|---|
| `image_generate`(이미지 만들기, 분류 AI) | `prompt`(설명), `style`(스타일·피할 것, 설명 뒤에 붙임), `size`(`1024x1024`·`1536x1024`·`1024x1536`), `count`(1~4), `provider`(기본 `default`), `model`(비우면 연결의 대표 이미지 모델) | `files[{id, filename, mime, size, kind}]`, `first_file_id`, `count`, `revised_prompt` |
| `file_export`(파일 만들기, 분류 데이터) | `format`(`txt`·`md`·`csv`·`json`·`xlsx`·`docx`), `filename`, `source`(`text`·`table`), `text`, `rows`(표: 목록 값 또는 JSON 글), `columns`(쉼표), `sheet`, `bom`(CSV) | `file{id, filename, mime, size}`, `file_id`, `filename` |

- **이미지**: OpenAI 호환(`POST {base}/images/generations`, Azure 포함)만 지원한다. Google Imagen은 요청 형식을 문서로 확인하지 못해 넣지 않았다. 연결은 단계에서 고른 것, 아니면 기본 연결(이미지를 못 만들면 만들 수 있는 연결 중 첫 번째). 모델을 비우면 `llm/presets.py`의 `IMAGE_PROVIDERS`에 적힌 대표 모델을 쓴다(OpenAI `gpt-image-1`, xAI `grok-2-image`, Together `black-forest-labs/FLUX.1-schnell`; Azure·호환 서버는 직접 적어야 함). `GET /llm/providers`의 각 공급자에 `image`(지원 여부)·`image_models`가 붙는다.
  - 그림은 b64나 주소로 오고, 주소는 `safe_http`(사설망 차단)로 받는다. 한 장 10MB 이하, 내용을 읽어 png·jpg·webp가 아니면 거절한다.
  - 크기는 모델에 맞게 바꾼다(dall-e-3는 `1792x1024`·`1024x1792`, 한 번에 한 장씩 여러 번 호출).
  - 비용: 공급자가 장당 비용을 알려 주지 않아 `engine/pricing.py`의 `IMAGE_PRICES`(정사각 1024 기준 **참고용 추정**, 정사각이 아니면 ×1.5)로 어림해 실행 비용에 더한다. 공급자가 토큰 사용량을 알려 주면 토큰으로도 올린다. 월 비용 한도(실행 시작 때 확인)에 포함된다.
  - 단계 제한 시간 기본 120초(`_timeout`으로 바꿈). 오류는 두 줄 한국어(안전 규칙·크기·모델·한도·권한·연결).
- **파일**: 엑셀·워드·CSV는 이미 설치된 openpyxl·python-docx로 만든다(PDF는 쓸 수 있는 라이브러리가 없어 제외). CSV/엑셀은 `=`·`+`·`-`·`@`·탭으로 시작하는 칸이 수식이 되지 않게 CSV는 앞에 `'`, 엑셀은 글 형식으로 저장한다. 파일 이름은 경로·제어 문자를 지우고 100자 안으로 줄여 확장자를 붙인다. 파일은 최대 10MB, 표는 5만 줄·50열.
- 만든 파일은 워크스페이스 파일(`files`)로 저장되고(`app_id` 설정, 저장소 설정을 따름) 단계 출력에 `{id, filename, mime, size}`가 담긴다. **마이그레이션은 없다.**
- 단계 시험(`POST /apps/{id}/nodes/{node_id}/test`)은 두 단계를 `risky`(비용·저장이 생김)로 표시해 화면이 먼저 확인을 받는다.

### 실행이 만든 파일 판정
단계 출력의 `files`(목록)·`file`(하나)에 든 `{id, ...}` 중, 같은 앱·워크스페이스의 파일만 그 실행의 결과로 친다(입력으로 올린 파일은 id 글자만 들어 있어 섞이지 않는다).

### 내려받기
| 경로 | 권한 | 내용 |
|---|---|---|
| GET /runs/{run_id}/files | 운영자 이상 | `{files:[{id, filename, mime, size, kind, node_id}]}` |
| GET /runs/{run_id}/files/{file_id}[?inline=1] | 운영자 이상 | 파일 내용. 그 실행의 결과 파일만(아니면 404). `inline=1`은 이미지만 화면에 바로 보이게 한다 |
| GET /public/apps/{token}/files/{file_id}?sig=&exp=[&inline=1] | 접근 권한 확인 + 서명 | 공유 링크용. 서명이 맞고 만료 전이며 그 파일이 이 앱의 것일 때만. 멤버 전용 앱은 로그인 필요(401). IP 제한 대상이고 앱·IP당 분당 120번 |

- 서명: `HMAC-SHA256(서버 비밀 키, "app_id:file_id:exp")`(40자), 유효 24시간. 변조·만료·다른 앱·다른 파일은 403(두 줄 오류), 파일이 없거나 다른 앱의 것이면 404.
- 응답 머리글: `Content-Disposition`(한글 파일 이름은 RFC 5987), `X-Content-Type-Options: nosniff`, `Cache-Control: private`, `Content-Security-Policy: default-src 'none'; sandbox`. 알려진 형식(이미지·txt·md·csv·json·xlsx·docx)이 아니면 `application/octet-stream`으로 내려준다.
- 실행 상세(`GET /runs/{id}`)에 `files`가 함께 온다.

### 챗·입력 폼·지난 대화·일괄 실행
- 챗 `answer` 이벤트: `{text, message_id, files?:[{id, filename, mime, size, kind, run_id, sig, exp}]}`. 파일을 만든 흐름에서만 `files`가 붙는다(검열된 답에는 안 붙임). 화면은 공유 토큰과 `sig`·`exp`로 받고, 앱 안 시험(토큰 없음)은 `run_id`로 `/runs/{run_id}/files/{id}`를 받는다.
- `GET /public/apps/{token}/sessions/{id}/messages`: 파일이 있는 답에는 새로 서명한 `files`가 붙는다(지난 대화를 다시 열 때).
- `GET /public/apps/{token}/runs/{run_id}`(입력 폼 결과): 성공하면 `files`가 붙는다.
- 일괄 실행 결과: 파일을 만드는 흐름이면 줄마다 `files[{id, filename, kind, url}]`가 붙는다. 로그인한 화면의 `url`은 실행 기록 화면(`{origin}/runs/{run_id}`), 공유 링크는 서명된 내려받기 주소다. 결과 CSV에는 `파일` 열이 **파일이 있을 때만** 더해진다(파일 없는 흐름의 CSV는 그대로).

### 마켓
템플릿 2개 추가: `tpl_product_image`(제품 사진 만들기, 챗, 이미지 생성 연결 필요), `tpl_weekly_report_xlsx`(주간 보고 엑셀 파일로 받기, AI 없이 동작). 마켓 항목은 71개.



## v0.9 관측 도구 확대(OpenTelemetry·Phoenix·Arize·Opik·Weave) (ADR 0013)

외부 추적을 **여러 서비스를 한꺼번에** 쓸 수 있게 확대했다. 설정은 `workspaces.settings["tracing"]`(마이그레이션 없음), 소유자·관리자만 읽고 쓴다. v0.6 때 저장한 `{"langfuse": …, "langsmith": …}` 모양도 그대로 읽고, 다음 저장 때 목록으로 옮긴다.

| 메서드·경로 | 권한 | 설명 |
|---|---|---|
| GET /workspaces/{ws}/tracing | 소유자·관리자 | `{include_content, kinds[], providers[], langfuse, langsmith}`. `kinds`는 서비스 종류와 입력 칸 목록(화면이 폼을 그린다), `providers`는 연결한 서비스(비밀값은 `{has, masked}`로만), `langfuse`·`langsmith`는 v0.6 호환 모양 |
| PUT /workspaces/{ws}/tracing | 소유자·관리자 | `{include_content?, providers?[]}` — `providers`를 보내면 **그 목록으로 통째로 바꾼다**(빠진 서비스는 지움, 최대 10개). 목록 없이 `langfuse`·`langsmith`만 보내면 예전처럼 그 둘만 고친다 |
| POST /workspaces/{ws}/tracing/test `{target}` | 소유자·관리자 | `target`은 서비스 id(예전 이름 `langfuse`·`langsmith`도 받음). 작은 '연결 시험' 기록 하나를 보내고 `{ok, message}`를 돌려준다. 결과는 서비스의 `last`에도 남는다 |

**서비스 한 개(providers 항목)**: `{id?, kind, name, enabled, sample_rate(0~100), only_failed, fields{}, secrets{}, clear_secrets[], headers[{name, value}]}`.
- `kind`: `langfuse` · `langsmith` · `otlp` · `phoenix` · `arize` · `opik` · `weave`.
- `id`가 없으면 새 서비스(서버가 id를 정한다). 있으면 그 서비스를 고친다.
- 비밀 칸(`secrets`)과 헤더 값은 **비우거나 `****`로 시작하면 저장된 값을 그대로 둔다**. 지우려면 `clear_secrets`에 칸 이름을 넣는다.
- 응답: `ready`(필수 칸이 찼는지), `experimental`, `last {at, ok, message}`(마지막 전송 결과, 비밀값 없음).
- 오류는 두 줄: 알 수 없는 서비스, 주소가 http(s)가 아님, 헤더 이름·값이 잘못됨, 서비스가 10개를 넘음 → 422.

**서비스별 보내는 방식**
| 서비스 | 보내는 곳 | 인증·특징 | 공식 문서로 확인 |
|---|---|---|---|
| Langfuse | `{host}/api/public/ingestion` | Basic(공개 키:비밀 키) | v0.6 |
| LangSmith | `{endpoint}/runs/batch` | `x-api-key` | v0.6 |
| OpenTelemetry(OTLP) | `{endpoint}/v1/traces`(이미 붙어 있으면 그대로) | 사용자가 넣은 헤더, OTLP/HTTP **JSON**(trace id 32자·span id 16자 16진수, 시각은 나노초 문자열, 정수는 문자열) + GenAI 속성(`gen_ai.*`) | 인코딩 규칙은 구현 사례들로 확인(공식 명세 본문은 못 읽음) |
| Arize Phoenix | `{endpoint}/v1/traces` | `Authorization: Bearer 키`(있을 때), `x-project-name`, 리소스 속성 `openinference.project.name`, OpenInference 속성(LLM·CHAIN·TOOL) | 엔드포인트·Bearer는 확인, 프로젝트 속성 이름은 확인 못 함 |
| Arize AX | `{endpoint}/v1/traces`(기본 `https://otlp.arize.com`) | 문서마다 헤더 이름이 달라 `arize-space-id`·`arize-api-key`와 `space_id`·`api_key`를 **둘 다** 보냄, 리소스 속성 `model_id` | **실험적**: 엔드포인트만 확인, 헤더는 문서 간 충돌 |
| Opik | `{host}/v1/private/traces/batch`, `/v1/private/spans/batch` | `Authorization: 키`, `Comet-Workspace`, id는 UUID v7 | **실험적**: spans 경로만 확인, traces 경로·본문은 못 확인 |
| W&B Weave | `{host}/call/upsert_batch` | Basic(`api:키`), 호출마다 start·end 쌍 | **실험적**: 경로만 확인, 인증 방식·본문 못 확인 |

**개인정보(기본은 내용 빼고)**
- `include_content`가 꺼져 있으면(기본) 단계 이름·상태·시간·모델·토큰·비용만 보낸다. 사용자 입력, AI 답, 단계 설정, 오류 원문은 보내지 않고 오류는 "실행이 실패했어요." 같은 일반 문장으로 바꾼다.
- 켜면 입력·결과·단계 입력/출력을 보내되 값마다 **2KB(2,048자)로 자르고**(`…(잘림)`), 앱의 비밀 환경 값은 `****`로 가린다.
- v0.6에서 저장한 설정도 같은 규칙(기본 꺼짐)을 따른다.

**보내는 조건**: 켜져 있고 필수 칸이 찬 서비스만. `sample_rate`(실행 id로 정해서 같은 실행은 늘 같은 결정), `only_failed`(실패한 실행만)를 통과한 서비스에만 보낸다. 받을 서비스가 하나도 없으면 큐에 올리지도 않는다. 실패는 기록만 남기고(비밀값 없음) 실행에는 영향이 없다. 모든 호출은 `safe_http`를 거친다(사설 IP 차단).

감사 기록: `tracing.update`(켠 서비스 종류, 내용 포함 여부).


## v0.9 키 분산·공급자 폴백·재정렬 모델 (ADR 0013)

### 키 여러 개 (AI 연결 하나에)
- 마이그레이션 0018: `llm_providers.extra_keys`(JSON, 더 둔 키 `[{id, label, key_encrypted, weight, disabled}]`), `key_strategy`(`failover`|`round_robin`|`weighted`), `primary_weight`.
- `GET /workspaces/{ws}/llm-providers`(제작자 이상)는 이제 `{..., rerank, key_strategy, keys[{id, label, masked, weight, disabled, primary, position, calls, errors, last_error, cooldown_seconds}]}`를 돌려준다. 키 값은 `****abcd`뿐이고, 첫 키 `primary`(기본 키)는 끄거나 지울 수 없다.

| 요청 | 권한 | 설명 |
|---|---|---|
| PATCH /workspaces/{ws}/llm-providers/{id} `{key_strategy?, primary_weight?}` | 소유자·관리자 | 돌려쓰기 방식·기본 키 비중(1~10) |
| POST /workspaces/{ws}/llm-providers/{id}/keys `{label?, api_key, weight?}` | 소유자·관리자 | 키 더하기(암호화 저장, 연결당 최대 10개 → 넘으면 409). 감사 기록에는 키 값 대신 id·이름만 |
| PATCH .../keys/{key_id} `{label?, weight?, disabled?}` | 소유자·관리자 | 이름·비중·끄기(기본 키는 끌 수 없음 409) |
| DELETE .../keys/{key_id} | 소유자·관리자 | 키 지우기(기본 키는 지울 수 없음 409) |
| POST .../keys/{key_id}/test | 제작자 이상 | 키 하나만 연결 테스트. 성공하면 쉬던 키를 바로 다시 쓴다 |

- 호출 순서: failover=목록 순서, round_robin=호출마다 시작 키를 한 칸씩 돌림, weighted=비중으로 무작위 순서(키마다 한 번씩).
- 오류 종류(`LlmError.kind`): `auth`·`rate_limit`·`outage`·`content_filter`·`context_length`·`other`. 어댑터(openai·anthropic·google)가 분류한다.
- `rate_limit`이면 그 키를 60초, `auth`이면 1시간(또는 키 테스트 성공 때까지) 쉬게 하고 같은 호출을 다음 키로 다시 한다(최대 5번). `outage`·요청 오류는 키가 원인이 아니라 바꾸지 않는다.
- 쉬는 시간·호출 수·실패 수는 Redis(없으면 프로세스 메모리)에 둔다(`llm/keypool.py`).
- 실행 단계 기록에 "키 1번을 쓸 수 없어 키 2번으로 바꿔 다시 시도했어요."가 남는다.

### 공급자 간 자동 전환
- 워크스페이스 설정: `workspace.settings.llm_fallback = {enabled, links[{provider_id, model}], triggers{outage, rate_limit, content_filter, context_length, auth}}`. 기본 조건은 outage·rate_limit만 켜짐.
- 앱별 설정: `app.features.llm_fallback = {mode: inherit|off|custom, links, triggers}`(`PATCH /apps/{id}/features`). `custom`은 워크스페이스 설정이 꺼져 있어도 이 앱에서 동작한다.

| 요청 | 권한 | 설명 |
|---|---|---|
| GET /workspaces/{ws}/llm-fallback | 제작자 이상 | `{enabled, links[{provider_id, label, provider, model, missing}], triggers, default_triggers, connections[{id, label, provider, default_model, key_count}]}`(재정렬 전용 연결은 목록에 없다) |
| PUT /workspaces/{ws}/llm-fallback `{enabled, links[], triggers{}}` | 소유자·관리자 | 저장. 연결은 이 워크스페이스의 대화 연결만, 중복 없이 최대 5곳. 켰는데 비어 있으면 422 |
| POST /workspaces/{ws}/llm-fallback/test | 소유자·관리자 | 기본 연결이 실패한 것처럼 만들어(첫 연결은 실제로 부르지 않음) 대신 답하는 연결을 본다. `{ok, message, answered_by{label, provider, model}, trail[{label, model, status: failed|skipped|answered, error}], notes[], simulated}`. 순서가 없거나 켜진 조건이 없으면 422 |

- 적용 범위: `resolve_llm(purpose="chat")`가 만드는 모든 호출 — AI 단계, 에이전트, 빌더, 대화 요약, 질문 만들기, 지식 검색의 AI 재정렬. 임베딩은 키만 돌려 쓰고 다른 공급자로 넘어가지 않는다.
- 넘어가는 조건: 기본 연결의 키를 모두 써 본 뒤 오류 종류가 켜진 조건에 맞을 때. `auth`는 켜져 있을 때만.
- 건너뛰기: JSON 출력(`model_supports_json`)·이미지(`model_supports_vision`)·도구 호출(`provider_supports_tools`; Google 어댑터는 도구 대화 미지원)이 필요한 호출은 지원하는 연결로만 넘어간다. 다른 공급자로 넘어갈 때 대화의 공급자 원본(`native`)은 뺀다.
- 답의 글자가 이미 나가기 시작했다면 키도 연결도 바꾸지 않고 오류를 낸다.
- 비용·사용량은 실제로 답한 모델 기준이다. AI 단계 출력에 `model_used`(실제 모델)가 새로 생겼다. 실행 단계 기록에 "대체 연결(○○)로 답했어요."가 남는다.

### 재정렬 전용 모델
- 공급자 키: `cohere-rerank`·`jina-rerank`·`voyage-rerank`·`rerank-compatible`(`GET /llm/providers`에서 `rerank: true`, 묶음 `재정렬 전용`). 대화·임베딩 연결로 고를 수 없고 기본 연결·자동 전환 순서·모델 카탈로그에도 들어가지 않는다. 키 여러 개 돌려쓰기는 그대로 쓸 수 있다.
- 호출 모양(`llm/rerank.py`):

| 공급자 | 요청 | 응답 | 문서로 확인한 정도 |
|---|---|---|---|
| Cohere | `POST {base}/v2/rerank` `{model, query, documents[str], top_n}` | `{results:[{index, relevance_score}]}` | 공식 문서 페이지는 검색에서 확인하지 못했고, Cohere 문서를 인용한 제3자 문서(Vercel AI Gateway 등)로 엔드포인트·필드·응답을 확인. `top_n`은 제3자 문서에서 보지 못했지만 공개된 Cohere 요청 형식 |
| Jina | `POST {base}/v1/rerank` `{model, query, documents[str], top_n}` | `{results:[{index, relevance_score}]}` | 제3자 문서만(공식 페이지 미확인) |
| Voyage | `POST {base}/v1/rerank` `{model, query, documents[str], top_k}` | `{data:[{index, relevance_score}]}` | Voyage 문서를 인용한 자료로 엔드포인트·`top_k`·`data` 응답 확인(공식 레퍼런스 페이지는 열지 못함) |
| 호환 서버 | `POST {주소}/rerank`(주소 끝이 `rerank`면 그대로) Cohere 형식 | `results` 또는 `data`, `relevance_score` 또는 `score` | 형식 가정(실제 vLLM·TEI 서버로는 확인 못 함) |

  응답은 `results`/`data`, `relevance_score`/`score` 이름을 모두 읽고, 인덱스 범위·중복을 걸러낸다. 실제 키로는 어느 공급자도 호출해 보지 못했다.
- 한도: 한 번에 문서 100개, 문서마다 2,000자, 응답 2MB, 30초. 오류는 두 줄 한국어(키 오류·한도·서버 오류·주소 오류·읽지 못함)이고 키는 들어가지 않는다.
- 지식베이스 설정: `retrieval.rerank_connection`(재정렬 전용 연결 id)·`retrieval.rerank_model`. 저장할 때 연결이 이 워크스페이스의 재정렬 전용 연결이 아니면 422. 설정되어 있고 `rerank`가 켜져 있으면 검색 결과를 전용 모델로 줄 세우고 결과에 `rerank_score`가 붙는다(`score`는 검색 점수 그대로). 전용 모델 호출이 실패하면 AI(LLM) 재정렬로 이어 가고, 그것도 안 되면 검색 순서 그대로 돌려준다. 검색 시험·검색 튜닝·`knowledge_search` 단계가 같은 경로를 쓴다.
- `GET /workspaces/{ws}/rerank-connections`(제작자 이상): 재정렬 전용 연결 목록(키 없음).
- 연결 테스트: `POST /workspaces/{ws}/llm-providers/test`에 `model`을 줄 수 있다. 재정렬 전용 연결은 문서 두 개로 한 번 재정렬해 본다.

## v0.9 지식 처리 캔버스·이미지 색인

문서 처리 순서가 8단계로 늘고(`kb.settings.pipeline`), 단계마다 결과를 돌려줘 화면의 '처리 캔버스'가 숫자와 미리 보기를 그린다. 이미지 색인은 DB 구조를 바꾸지 않는다(그림 파일은 워크스페이스 파일, 설명은 조각 메타데이터).

### 처리 순서(8단계)
순서는 고정: `extract → clean → split → translate → summarize → metadata → image → store`. 예전 5단계로 저장된 설정은 빠진 단계를 기본값으로 채워 읽는다.

| 단계 | 켜기 | 설정 | 비고 |
|---|---|---|---|
| translate(번역) | 기본 꺼짐 | `target_language`(기본 영어, 30자) | 조각·부모 문단마다 AI 한 번. 한 번에 최대 200개 |
| summarize(요약 붙이기) | 기본 꺼짐 | 없음 | 조각마다 한 줄 요약을 검색용 글 앞에 붙임. 최대 200개 |
| image(이미지 설명) | 기본 꺼짐 | `max_images` 1~20(기본 20), `min_size` 50~2000(기본 100) | 그림 한 장마다 비전 모델 한 번 |

- 질문·답(`chunk_mode=qa`) 방식에서는 번역·요약 붙이기를 건너뛴다(로그에 안내).
- AI 단계는 이번 달 AI 사용 한도(`monthly_budget_usd`)를 이미 넘었으면 **건너뛴다**(문서는 글만 처리됨, 단계 결과 `skipped`에 이유). 이 단계들의 AI 비용은 실행 비용 합계에 들어가지 않는다(문서 꼬리표 `_ai_usage`에 호출 수·토큰만 남김).

### 요청
| 요청 | 권한 | 설명 |
|---|---|---|
| GET /knowledge-pipeline-templates | 로그인한 누구나 | 처리 순서 모음 4가지 `[{id, name, description, settings{pipeline[8], chunk_mode, chunk_size…}}]`: `general`(일반 문서), `rules`(규정집, 머리글·바닥글 제거 + 부모-자식), `faq`(FAQ 표, 질문·답), `minutes`(회의록, 파일 이름의 날짜를 `날짜` 꼬리표로) |
| POST /knowledge-bases/{id}/preview | 제작자 이상 | (v0.6) 저장 없이 돌려 본다. 응답에 `stages`·`ai_calls`가 더해졌다 |
| GET /knowledge-bases/{id}/image-estimate?max_images=&min_size= | 제작자 이상 | 앞의 100개 문서 기준 `{documents, scanned, partial, images, vision_calls, estimated_cost_usd, model, model_ok, message, enabled, budget_message}`. 실제 AI는 부르지 않는다. 외부 지식베이스는 409 |
| GET /knowledge-bases/{id}/images/{file_id} | 운영자 이상 | 지식베이스 그림 파일(이 지식베이스 것만, 아니면 404) |
| GET·HEAD /public/apps/{token}/kb-images/{file_id}?exp=&sig= | 서명 또는 로그인 | 공개 챗의 그림. 서명(24시간)이 맞으면 로그인 없이, 아니면 로그인한 사용자가 배포 접근 규칙을 통과해야 한다. 배포가 공개가 아니면 서명만으로는 안 열린다. 같은 워크스페이스의 지식베이스 그림만(아니면 404). 허용 IP 제한은 전역 가드가 막는다 |

### 미리 보기 응답 `stages`
단계 이름 → 결과(없는 값은 빠질 수 있다). 미리 보기는 아무것도 저장하지 않고, AI 단계는 앞의 3조각(그림 3장)에만 AI를 부른다.

| 단계 | 값 |
|---|---|
| extract | `chars`, `kind`, `sample` |
| clean | `enabled`, `before_chars`, `after_chars`, `before_sample`, `after_sample` |
| split | `chunks`, `mode`, `samples[]` |
| translate | `enabled`, `language`, `calls`, `calls_full`(전부 돌릴 때), `estimated_cost_usd`(전체 어림), `samples[{before, after}]`, `cut`, `skipped` |
| summarize | `calls`, `calls_full`, `estimated_cost_usd`, `samples[{summary}]`, `skipped` |
| metadata | `enabled`, `tags` |
| image | `found`, `images`, `described`, `failed`, `calls`, `calls_full`, `estimated_cost_usd`, `model`, `too_small`, `too_big`, `unsupported`, `duplicates`, `truncated`, `cut`, `errors[]`, `skipped` |
| store | `chunks` |

`chunks[]`에는 `kind`(`text`|`image`)가 붙고, 그림 조각은 `image{caption, page, index}`와 150KB 이하면 `thumb`(data URL)이 붙는다. 글 조각은 앞의 50개, 그림 조각은 모두 보여 준다.

### 이미지 색인
- 뽑는 곳: PDF(쪽마다, 200쪽까지), DOCX·XLSX(문서 안 미디어), PPTX(슬라이드마다, `page`=슬라이드 번호), 올린 PNG·JPG·WEBP 파일(한 장). 문서당 `max_images`장, `min_size` 미만·5MB 초과·그림이 아닌 파일·같은 그림(SHA-256)은 뺀다. 읽지 못하는 문서는 그림 0장으로 처리한다(문서 처리는 계속).
- 설명: 비전을 지원하는 모델이 `이 그림을 검색에 쓸 수 있게 한국어로 2~3문장으로 설명하고, 그림 속 글자는 그대로 옮겨 적어 주세요`에 답한다. 기본 모델이 그림을 못 읽으면 같은 워크스페이스의 다른 연결에서 비전 모델을 찾는다(없으면 이 단계만 건너뜀, 두 줄 안내). 연속 3번 실패하면 남은 그림은 건너뛴다.
- 저장: 그림 파일은 워크스페이스 파일로 두며(`files.filename=kbimg/{kb}/{doc}/{n}.{확장자}`, v0.8 파일 저장소 설정을 따름) 설명은 조각(`content="[그림 3쪽] …"`, 메타데이터 `kind="image"`, `file_id`, `caption`, `page`)이 된다. 문서 꼬리표의 `_image_files`(그림 파일 id), `_image_report`는 밑줄 키라 화면·검색에는 안 보인다. 다시 나누면 새 결과를 만든 뒤 예전 그림 파일을 지우고, 문서·지식베이스를 지우면 그림 파일도 지운다.
- 문서 목록 응답에 `image_report{found, images, described, failed, calls, truncated, skipped}`(그림 색인을 안 돌렸으면 null)가 붙는다. 조각 목록에는 `kind`, `image_file_id`, `page`가 붙는다.
- 검색 결과(`knowledge_search` 단계의 `results[]`, 검색 시험)에 그림 조각은 `kind:"image"`와 `image{file_id, caption, page, kb_id}`가 붙는다. 챗 인용(`citations`)에도 `image`가 실리고, **누구나 열 수 있는 배포**에서는 보낼 때 24시간 서명 주소 `image.url`을 붙인다(저장된 인용에는 주소를 남기지 않고, 지난 대화를 다시 열 때 새로 서명한다). 멤버 전용 배포·빌더 시험은 `url` 없이 `image.kb_id`로 로그인 상태에서 불러온다.
- 서명 주소: `HMAC-SHA256(GENIO_SECRET_KEY, "kbimg\n{token}\n{file_id}\n{exp}")`(v0.9 실행 결과 파일의 서명과 이름이 겹치지 않게 접두어 `kbimg`를 쓴다).
