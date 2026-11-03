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
| 시스템 설정 | **추가** 회원가입 허용, 로그인 화면 데모 계정 표시, 공개 챗 속도 제한 |
| Dataset Operator 역할 | 범위 밖(역할 5개 유지) |
| 결제·요금제·SSO | 범위 밖(CLAUDE.md) |
