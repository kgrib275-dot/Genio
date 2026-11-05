# Dify 기능 비교와 v0.2 추가 범위

Dify 공식 문서(docs.dify.ai, 2026-11 조사)의 기능을 Genio와 비교했다. "추가"는 이번 v0.2에서 구현, "범위 밖"은 CLAUDE.md 제외 항목이거나 프로토타입에 맞지 않아 ADR 0005 후보로만 남긴다.

## 1. 흐름 노드
| Dify | Genio v0.1 | v0.2 |
|---|---|---|
| Start / End / Answer | input / output | 유지 |
| LLM | llm | 대화 기록(memory) 옵션 추가 |
| Knowledge Retrieval | knowledge_search | 검색 방식(벡터·키워드·혼합), 점수 기준, 메타데이터 필터 추가 |
| IF/ELSE | condition | 유지 |
| HTTP Request, Code | http, code | 유지 |
| Tools / Plugins | connector(마켓) | 유지 |
| Human Input | approval | 유지 |
| Question Classifier | 없음 | **추가** `question_classifier` (분류마다 출구) |
| Parameter Extractor | 없음 | **추가** `parameter_extractor` (`__is_success`, `__reason`) |
| Template | 없음(output만) | **추가** `template` (Jinja2) |
| Variable Aggregator | 없음 | **추가** `variable_aggregator` |
| List Operator | 없음 | **추가** `list_operator` (거르기·정렬·자르기) |
| Iteration | 없음 | **추가** `iteration` (항목마다 하위 동작 1개 실행) |
| Loop | 없음 | **추가** `loop` (멈춤 조건·최대 횟수) |
| Document Extractor | 없음 | **추가** `document_extractor` (올린 파일 → 글) |
| Variable Assigner / 대화 변수 | 없음 | **추가** `variable_assigner` + 대화 변수(`{{conv.x}}`) |
| Agent | 없음 | **추가** `agent` (서비스·웹·지식·다른 앱을 도구로 스스로 사용) |
| 노드 재시도·오류 처리 | http·connector 고정 2회 | **추가** 모든 노드에 재시도 횟수·간격, 실패 시 멈춤/기본값/실패 분기 |

## 2. 앱 기능(App Toolkit)
| Dify | v0.2 |
|---|---|
| 시작 인사·추천 질문 | **추가** |
| 답변 뒤 이어서 물어볼 질문 | **추가** |
| 출처(인용) 표시 | **추가** 지식 검색 결과를 답변에 번호로 표시 |
| 내용 검열(Moderation) | **추가** 금지어 목록 + 미리 정한 답 (입력·출력) |
| 주석 답변(Annotation Reply) | **추가** 질문-답 쌍, 비슷한 질문이면 바로 답 |
| 파일 올리기 | **추가** 입력 항목 `file` + 공유 챗 첨부 |
| 음성 입력·읽어 주기 | **추가** 브라우저 음성 기능(서버 비용 없음) |
| 앱 환경 변수(비밀 포함) | **추가** `{{env.x}}`, 비밀은 암호화·마스킹 |
| 앱 내보내기·가져오기(DSL), 복제 | **추가** JSON |
| 버전 되돌리기 | **추가** |

## 3. 게시·운영
| Dify | v0.2 |
|---|---|
| WebApp·위젯·공유 링크 | 있음 |
| 앱별 API 키 + 서비스 API | **추가** `/api/v1/service/*` (채팅·흐름 실행·파라미터) |
| 로그(대화 기록) | **추가** 앱별 대화·메시지 목록, 좋아요/싫어요 피드백 |
| 모니터링 대시보드 | **추가** 일별 실행·대화·토큰·비용·응답 시간·성공률·만족도 |
| 외부 추적(Langfuse·LangSmith·Opik·Arize) | 범위 밖(ADR 후보) |
| MCP 서버로 게시, 흐름을 도구로 게시 | 흐름을 도구로: **추가**(agent의 `app` 도구). MCP: 범위 밖 |

## 4. 지식베이스
| Dify | v0.2 |
|---|---|
| 일반 청킹(구분자·크기·겹침) | **추가** 설정 화면 |
| 부모-자식 청킹 | **추가** 자식으로 찾고 부모 문단을 돌려줌 |
| Q&A 청킹 | 범위 밖 |
| 벡터·전문(키워드)·혼합 검색, 가중치 | **추가** |
| Rerank | **추가** AI로 다시 순위 매기기(선택) |
| Top K·점수 기준 | **추가** |
| 메타데이터·필터 | **추가** 문서별 메타데이터, 검색·노드에서 필터 |
| 조각 보기·고치기·끄기 | **추가** |
| 검색 테스트 | 있음 → 방식 선택 추가 |
| 웹 페이지 가져오기 | **추가** URL 1개 가져오기 |
| Knowledge Pipeline | 범위 밖 |

## 5. 워크스페이스·관리(소유자·관리자 전용)
| Dify | v0.2 |
|---|---|
| 멤버·역할·초대 | 있음 → 멤버 내보내기, 초대 취소, 소유권 넘기기(소유자만) 추가 |
| 모델 공급자 | 있음 → 기본 모델(대화·임베딩·빌더) 지정 추가 |
| 관리 콘솔 | **추가** 개요(일별 그래프·인기 앱), 멤버, AI 모델, 사용량, 활동 기록, API 키 전체, 시스템 설정 |
| 시스템 설정 | **추가** 회원가입 허용, 공개 챗 속도 제한 (데모 계정 표시는 ADR 0007로 없앰, 대신 관리자 계정 만들기·비밀번호 재설정) |
| Dataset Operator 역할 | 범위 밖(역할 5개 유지) |
| 결제·요금제·SSO | 범위 밖(CLAUDE.md) |


---
# v0.4 (ADR 0008) — n8n·Zapier·Make·Flowise 비교

조사(2026-11): n8n 코어 노드(Webhook·Schedule Trigger·Wait·Merge·Edit Fields·Date & Time·Execute Workflow·Data Table), Zapier(Formatter·Delay·Paths·Tables), Make(Router·Iterator/Aggregator·Data store), Flowise Embed(theme·starter prompts·clearChat).

## 6. 자동화(n8n·Zapier·Make)
| 기능 | 해당 서비스 | v0.4 |
|---|---|---|
| 웹훅으로 시작(외부 호출) | n8n Webhook, Zapier Catch Hook, Make Webhooks | **추가** 앱마다 비밀 주소 `/api/v1/hooks/{token}`(POST·GET), 바로 응답(async) 또는 결과까지 기다림(sync, 최대 30초), 주소 다시 만들기·끄기 |
| 결과로 응답하기 | n8n Respond to Webhook | **추가** sync 모드가 출력(`text`·`outputs`)을 돌려줌 |
| 예약 실행 | n8n Schedule Trigger, Zapier Schedule, Make 시나리오 예약 | **추가** cron 5칸 + 시간대(기본 Asia/Seoul) + 고정 입력, 최소 1분, Celery beat |
| 실패하면 다른 흐름 | n8n Error Workflow, Make error handler | **추가** 앱 기능 `on_failure.app_id` (빌더 테스트·하위 실행은 제외, 무한 반복 방지) |
| 실행 다시 하기 | n8n Retry execution | **추가** `/runs/{id}/rerun` (입력 고쳐서도 가능) |
| 지금 실행(트리거 시험) | n8n Test workflow | **추가** `/triggers/{id}/run-now` |
| 기다리기 | n8n Wait, Zapier Delay | **추가** `wait` (1~300초). 외부 응답이 올 때까지 기다리기는 범위 밖(승인 노드로 대신) |
| 값 정리 | n8n Edit Fields(Set), Zapier Formatter | **추가** `set_fields` (글·숫자·참거짓·JSON 변환) |
| 날짜·시간 | n8n Date & Time, Zapier Formatter(Date) | **추가** `date_time` (지금·형식·더하기·차이, 개월 말일 보정) |
| 하위 흐름 | n8n Execute Workflow, Make Scenario call | **추가** `run_app` (최신 저장 버전, 깊이 2단계) |
| 내장 저장소 | n8n Data Tables, Make Data store, Zapier Tables | **추가** `data_table` 블록 + 데이터 표 화면·API(추가·덮어쓰기·가져오기·찾기·목록·지우기·개수, CSV 가져오기/내보내기, 표당 5,000줄) |
| 분기·반복·합치기 | Zapier Paths, Make Router/Iterator/Aggregator | 있음(condition·question_classifier·iteration·loop·list_operator·variable_aggregator) |
| 병렬 실행 후 합치기 | n8n Merge(Wait for both) | 범위 밖(CLAUDE.md: 병렬 분기 실행) |
| 수백 개 앱 연동 | n8n·Zapier·Make 통합 | 마켓 커넥터 + http 블록으로 대신(범위 밖: 대량 통합) |

## 7. 캔버스(n8n 편집기)
| 기능 | v0.4 |
|---|---|
| 스티커 메모 | **추가** `Graph.notes` (색 5가지, 실행과 무관) |
| 블록 끄기(Deactivate) | **추가** `GraphNode.disabled` — 건너뛰고 앞 값을 넘김, 갈림길은 첫 출구, 끈 블록은 설정 오류를 보지 않음, 입력 블록은 끌 수 없음 |
| 복사·붙여넣기·복제, 되돌리기, 미니맵, 자동 정렬, cURL 가져오기 | **추가**(화면 작업, ADR 0008 §3) |
| 실행 데이터 고정(Pin data) | 범위 밖(ADR 후보) |

## 8. 챗 경험(Flowise·Dify 웹앱)
| 기능 | v0.4 |
|---|---|
| 답변 실시간 표시(스트리밍) | **추가** `delta` 이벤트 (출력 검열 앱은 제외) |
| 마크다운·코드 복사·다시 답하기·멈추기 | **추가**(화면) |
| 이전 대화·새 대화·대화 내보내기 | **추가** 세션 메시지 API + 화면 |
| 위젯 모양(theme) | **추가** `deployments.appearance` |
| 빌더 안 대화 시험(Debug & Preview) | **추가** `/apps/{id}/preview/chat` |
| 리드 수집 폼, 사람 상담원 연결 | 범위 밖(ADR 후보) |


---
# v0.8 (ADR 0012) — dify.ai/ko·docs.dify.ai 재조사(2026-11-05)

| Dify | v0.8 |
|---|---|
| 워크플로우 웹앱 일괄 처리 | **추가** CSV·XLSX 일괄 실행(앱 200건·공유 50건) |
| 단일 노드 실행, Variable Inspector | **추가** 단계 하나만 시험, 값 확인창 |
| MCP 클라이언트(도구 노드·에이전트) | **추가** `mcp_tool` 단계, 에이전트 MCP 도구 |
| OpenAPI 커스텀 도구 | **추가** `api_tool` 단계 |
| Marketplace 플러그인 200개 이상 | 부분: 마켓 69개(커넥터 33), 제3자 플러그인 등록은 범위 밖 |
| 지식 데이터 소스(Notion·웹 크롤·드라이브) | **추가** Notion·웹 크롤·공개 Google 문서(개인 드라이브 OAuth는 범위 밖) |
| 외부 지식베이스 API | **추가** |
| Test and Tune Retrieval | **추가** 검색 튜닝 |
| 지식 요청 한도·저장 용량 | **추가** 문서 수·용량·분당 요청 한도 |
| Snippets | **추가** 스니펫 |
| Go to Anything, Hotkeys | **추가** Ctrl+K 검색창, 단축키 목록 |
| 웹앱 브랜딩, IP Access Control | **추가** 로고, 허용 IP |
| API Reference, difyctl | **추가** `/api-docs`, `scripts/genio_cli.py` |
| 코드 샌드박스 서비스 | **추가** 별도 컨테이너(선택) |
| S3 등 저장소 선택 | **추가** DB·디스크·S3 |
| Sentry | **추가**(선택) |
| DSL 가져오기·내보내기 | **추가** Dify DSL → 제니오 변환(내보내기는 제니오 JSON) |
| 사람 입력(수정·전달·시간 초과) | 부분: 승인·질문·배정, '전달'과 시간 초과 자동 처리는 다음 |
| 캔버스 동시 편집·댓글 | 다음 |
| 이미지 만들기·파일 출력 | 다음 |
| 서비스 이벤트 트리거 | 다음 |
| 관측 도구(Opik·Arize·Phoenix·Weave·OpenTelemetry) | 다음 |
| 키 여러 개 분산·공급자 폴백 | 다음 |
| 재정렬 전용 모델 | 다음 |
| 지식 파이프라인 캔버스·멀티모달 검색 | 다음 |
| SSO·SCIM·사용자 정의 역할·BYOK·다중 워크스페이스·결제 | 범위 밖(ADR 0012) |
| K8s Helm·Terraform·고가용성 | 범위 밖(ADR 0012) |


---
# v0.9 (ADR 0013) — v0.8에서 '다음'으로 남긴 것

| Dify | v0.9 |
|---|---|
| 캔버스 동시 편집·댓글 | **추가** 접속 표시, 충돌 자동 합치기, 댓글 |
| 이미지 만들기·파일 출력 | **추가** `image_generate`·`file_export` 단계, 서명 주소 내려받기 |
| 서비스 이벤트 트리거 | **추가** Slack·GitHub·Shopify·Telegram·Jira·Typeform |
| 사람 입력(수정·전달·시간 초과) | **추가** 전달, 시간 초과 처리·알림. '수정'은 질문 단계가 대신 |
| 관측(Opik·Arize·Phoenix·Weave·OpenTelemetry) | **추가** |
| 키 분산·공급자 폴백 | **추가** |
| 재정렬 전용 모델 | **추가** |
| 지식 파이프라인 캔버스·멀티모달 검색 | **추가** |
| SSO·SCIM·사용자 정의 역할·BYOK·다중 워크스페이스·결제 | 범위 밖 |
| K8s Helm·Terraform·고가용성, 제3자 플러그인 등록 | 범위 밖 |
