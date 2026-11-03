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
| POST | `/me/password` | 로그인 | `{current_password, new_password(8자+)}` | `{ok}` (지금 비밀번호가 틀리면 400) |

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
