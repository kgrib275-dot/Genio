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
