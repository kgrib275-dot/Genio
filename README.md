# Genio (제니오)

**Dify(AI 앱·지식베이스) + n8n(자동화·연결·트리거) + 챗봇**을 하나로 합친 노코드 챗봇 기반 흐름(워크플로우) 도구의 프로토타입이다. 말로 요청하면 빌더가 흐름을 만들고, 캔버스에서 다듬어 챗봇·입력 폼·외부에서 받기·예약으로 운영한다. 목표는 "기획자(비개발자)가 10분 안에 동작하는 앱을 말로 만들어 내는 것".

- **처음이라면**: 첫 로그인 때 나오는 **화면 투어**와 대시보드의 **시작 체크리스트**를 따라 하고, 왼쪽 아래 **배우기**에서 샘플 11가지·강좌 9개를 해 보세요(Dify·n8n 이름 대응표 포함). 막히면 오른쪽 아래 **도움**에서 설명서를 찾거나 문의를 보내요.

- 실행: `start_genio.bat` 더블클릭 (끄기: `stop_genio.bat`, 화면 코드를 고쳤으면 `start_genio.bat -Rebuild`)
- 공유 주소: https://genio.tail6bd481.ts.net (Tailscale Funnel, 인터넷 공개)
- 데모 계정: 처음 기동하면 `owner@example.com` 등 역할별 5개가 만들어진다(비밀번호는 [runbook](docs/runbook.md)). 로그인 화면에는 보이지 않는다. **공개 주소로 운영한다면 비밀번호를 바꾸거나 관리 > 멤버에서 정리할 것.**

## 할 수 있는 것
| 영역 | 기능 |
|---|---|
| 만들기 | 빌더 챗(말로 생성·되묻기 버튼·부분 수정·설명 모드·자동 시험·오류 해결), 캔버스(메모, 단계 끄기, 복사·붙여넣기·복제, 되돌리기, 미니맵, 자동 정렬), 값 끌어오기(칩·자동완성·고급 모드), 대화로 시험, 샘플 입력 저장, 버전 저장·되돌리기·**버전 비교**, **여러 명이 같이 편집(접속 표시·충돌 합치기)·캔버스 댓글** |
| 단계 26종 | 입력·결과·AI·조건·외부 호출(인증·페이지 넘김·시험 호출·cURL)·코드(파이썬·자바스크립트)·지식 검색·연결·승인(승인/반려 갈래·알림·링크), 질문 분류·값 뽑기·템플릿·값 합치기·목록 다루기·반복·되풀이·문서 읽기·값 저장·에이전트, 기다리기·값 정리·날짜·시간·다른 앱 실행·데이터 표, 사람에게 묻기·담당자 배정 |
| 실행 | **병렬 갈래(여러 단계 동시 실행 → 모두 기다려 모으기)**, **일괄 실행(CSV·XLSX 여러 건)**, **단계 하나만 시험·값 확인창**, **이미지 만들기·파일 만들기(XLSX·DOCX 등)**, 테스트 실행, 외부에서 받기(서명 검증·받은 값 미리 보기), 예약, 실패하면 다른 앱 실행, 다시 실행·이 단계부터 다시, 단계별 재시도·제한 시간·실패 갈래, **실행 결과를 문장으로 설명** + '빌더에게 고쳐 달라고 하기' |
| 챗봇 | 공유 링크·위젯·서비스 API·흐름 앱 입력 폼, 실시간 답변·멈추기, 마크다운, 지난 대화·내보내기, 출처·이어질 질문·검열·모범 답변·파일·사진(비전)·음성, **오래된 대화 요약 기억**, **챗에서 흐름·승인 실행 → 결과가 대화로**, 상담원 전환 |
| 사람 개입 | 작업함(승인·질문·배정), **전달·시간 초과 자동 처리·기한 전 알림**, 로그인 없이 링크로 결정, 이메일·슬랙 알림 |
| 데이터 | 지식베이스(PDF·DOCX·PPTX·XLSX·HTML·URL, 조각 설정, 혼합 검색, 재정렬, 문서 켜기·끄기, 지식베이스별 임베딩 모델, **질문·답 형식(표 가져오기·AI 생성)**, **문서 처리 순서·미리 보기**), 데이터 표(CSV 가져오기·내보내기) |
| 연결 | Slack·이메일·Google Sheets·DB(PostgreSQL·MySQL)·HTTP 인증 정보·잔디·네이버웍스·카카오 알림톡·카카오워크·두레이·Notion·Jira·Teams·Discord·Telegram·GitHub·Trello·Asana·Airtable·HubSpot·Linear, 연결 테스트 |
| AI | **키 여러 개 분산·공급자 간 자동 전환**, **연결 테스트**(키로 실제 모델 목록 불러오기), 공급자 23곳(OpenAI·Anthropic·Google·Azure·OpenAI 호환 + DeepSeek·Mistral·Groq·OpenRouter·xAI·Upstage·HyperCLOVA X 등 키만 넣으면 되는 18곳), 이미지 입력(비전), 모델 목록·기본 모델, 실행·앱·사용자별 비용, 모델 교체 예상 비용, 월 한도·알림 |
| 계정 | 관리자가 계정을 만들고 **임시 비밀번호 발급**(첫 로그인 때 새 비밀번호 강제), 회원가입 끄기, 비밀번호 찾기(메일), 이메일 인증(선택), 2단계 인증(인증 앱·복구 코드), 로그인 기기 관리·모든 기기 로그아웃, 내 데이터 내려받기, 탈퇴, 이용약관·개인정보처리방침 동의 |
| 운영·관리 | 로그·모니터링·사용량·활동 기록(CSV 내보내기), 모든 목록 검색·필터·개수(계정별 유지, 기본 10개), 프로젝트 현황판, 소유자·관리자 콘솔(계정 만들기·비밀번호·2단계 인증 초기화, 시스템 메일), **시스템 상태**(DB·Redis·워커·백업·디스크)·**서버 오류 기록**(요청 번호), **매일 자동 백업**(7일 보관), 역할 5개·배포 대상 사용자·API 키 권한 범위, 보관 기간, 개인 설정(다크 모드) |
| 마켓 | 69개: 커넥터 33(Twilio·SendGrid·Zendesk·Salesforce·솔라피 등)·템플릿 24·프롬프트 팩 9·단계, 분류·정렬, 설치·업데이트 |
| 외부 연동 | **MCP로 게시**(흐름 앱을 Claude 등 AI 도구에서 호출), **MCP 클라이언트**(외부 MCP 도구를 단계·에이전트에서 사용), **OpenAPI 가져오기→API 도구**, **외부 추적**(Langfuse·LangSmith), **공개 API 문서(/api-docs)·명령줄 도구**, **Dify 앱 가져오기**, **서비스 이벤트로 시작**(Slack·GitHub·Shopify·Telegram·Jira·Typeform), **외부 추적 7종**(Langfuse·LangSmith·OpenTelemetry·Phoenix·Arize·Opik·Weave) |
| 배우기·도움 | 화면 투어(역할별), 시작 체크리스트, 빈 화면 안내, 샘플 11가지(8개는 AI 키 없이 동작), 따라 하기 강좌 9개, Dify·n8n 이름 대응표, 사용설명서, 도움·문의 창 |

기능 정의서와 반영 현황: [docs/feature-spec.md](docs/feature-spec.md) · [docs/feature-coverage.md](docs/feature-coverage.md)
다른 서비스와 비교(Dify·n8n·Zapier·Make·Flowise): [docs/dify-gap.md](docs/dify-gap.md)

## 현재 상태 (2026-11-11)
- 버전: v0.9 + 2026-11-06 보안·안정성 수정(커밋 60870a8). 기능 범위는 [기능 반영 현황](docs/feature-coverage.md), 결정 기록 ADR 0001~0013.
- 운영 주소 반영: 서버 쪽 보안 수정은 운영에 들어가 있다. 마지막 문구 수정은 `docker compose restart api worker`, 화면 쪽 수정(초대 수락 단추·이동 주소 검사·dompurify·문구)은 `start_genio.bat -Rebuild`를 해야 반영된다(메모리가 빠듯하니 시험용 스택을 내린 뒤 빌드).
- 다음 후보: 보안 남은 항목(외부 호출 DNS 재바인딩, 연결 정보 허용 호스트, 압축 폭탄 상한 등), 다중 서비스 운영 준비(속도 제한 Redis 이전, 예약 실행 분리, 외부 백업, 관측 도구), 실제 AI 키·메일로 수동 검수.

## 최근 점검 (2026-11-06) — 안정성·보안·전체 화면
- 자동 검사 전부 통과(pytest 982, 화면 테스트 209). 200명 동시 20 시험: 요청 15,986개 **실패 0**, 사용자 간 접근 600/600 차단.
- 보안: **코드 단계 샌드박스 탈출(치명)**, 초대 수락으로 비밀번호 시험·2단계 인증 건너뛰기(높음), 비밀번호 변경 때 다른 기기 로그인 유지, 72바이트 넘는 비밀번호, 로그인 시간 차로 계정 존재 노출, 주소 토큰 범위, CSV 수식 주입, 한글 서명 500 오류 등 **10건 고침**. 남은 보통·낮음 항목은 대응 방향과 함께 보고서에 기록.
- 화면 35개(데스크톱·모바일) 점검: 오류 0, 어색한 문구 2건 고침. 로그인한 상태로 초대 링크를 열면 단추 하나로 합류.
- 자세히: [docs/test-report-2026-11-06.md](docs/test-report-2026-11-06.md)

## 성능·데이터·보안 점검 (2026-11-03, 개발용 PC 1대)
- 1,000명이 각자 가입~앱 만들기~배포~챗~실행~데이터 표~웹훅까지 사용: 요청 25,000개 실패 0.
- 동시 100명: 고치기 전에는 서버가 멈췄으나, API를 운영 설정(프로세스 4개)으로 바꾸고 응답 스트리밍 중 DB 연결을 붙잡지 않게 고친 뒤 **1,000명 모두 성공, 실패 0**. 지금 한계는 PC의 CPU다.
- 데이터: 컨테이너를 지우고 다시 만들어도, 백업(pg_dump)을 새 DB에 복구해도 모든 수치가 같았다.
- 보안: 사용자 간 접근 4,000번 시도 모두 차단, 위조 토큰·내부망 호출·SQL 주입·XSS 차단, 비밀값 마스킹. 이후 로그인 시도 제한·비밀번호 규칙·보안 헤더(HSTS·CSP)·2단계 인증을 더했다(2026-11-04 운영 주소에서 재확인).
- v0.6 병렬 갈래: 같은 단계를 순서대로 4.2초 → 병렬 1.8초(가상 사용자 5명 시험, 가짜 AI). 1,000명 병렬 시험은 PC 메모리 부족으로 끝내지 못했다.
- 자세히: [docs/loadtest-2026-11-03.md](docs/loadtest-2026-11-03.md)

## 오픈 전 남은 일
- **꼭**: 데모 계정 비밀번호 바꾸기(공개 주소), 필요 없으면 회원가입 끄기(관리 > 시스템 설정), 실제 AI 키로 빌더·샘플 ⑧~⑩ 확인, 시스템 메일(SMTP) 설정, 약관·개인정보처리방침 법률 검토.
- **판매형 전환 때 결정 필요**(작업 규칙상 범위 밖, [ADR 0011](docs/decisions/0011-오픈-준비.md)): 결제·요금제, 사용량 과금, 기본 제공 AI·체험 크레딧, SSO, 고객사별 데이터 격리, 클라우드 서버 이전.
- v0.8 선택 설정: 파일을 S3·디스크에 두기(`GENIO_STORAGE`), 코드 실행 샌드박스(`GENIO_SANDBOX_URL`, 컴포즈 프로필 `sandbox`), Sentry(`SENTRY_DSN`). 자세히는 [runbook](docs/runbook.md)의 'v0.8 운영 안전'.
- 보안 남은 항목(보통): 외부 호출 DNS 재바인딩, 연결 정보 허용 호스트, AI 연결 주소의 사설 IP 검사, XLSX·zip 폭탄 상한, 공개 업로드 총량 — [점검 보고서 §3.2](docs/test-report-2026-11-06.md).
- 이 PC는 메모리가 빠듯하다: 운영 중에 이미지를 빌드하면 Docker가 멈출 수 있으니 다른 컨테이너를 줄인 뒤 빌드할 것.
- 실제 계정으로 확인하지 못한 것: 새 커넥터 13개, AI 공급자 18곳, MCP 클라이언트, Langfuse·LangSmith, 메일 발송.

## 빠른 시작
```bash
cp .env.example .env          # 키 채우기(GENIO_SECRET_KEY, GENIO_FERNET_KEY 등)
docker compose up --build -d  # postgres, redis, api(프로세스 4), worker(+예약), web(nginx), backup(매일 3시), tailscale
open http://127.0.0.1:5190
```
- API 코드를 고친 뒤: `docker compose restart api worker` (운영 설정이라 자동 재시작 없음)
- 개발 중 자동 재시작: `docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d api`
- requirements를 바꾼 뒤: `docker compose up -d --build api worker`
- 백업 복구: `scripts/restore_backup.sh <파일>`(지금 DB를 먼저 백업한 뒤 복구, [runbook](docs/runbook.md))
- 검사: `make check` (Windows는 `PYTHONUTF8=1 bash scripts/check.sh`) — ruff·mypy·pytest·eslint·tsc·vitest

## 구성
```
apps/api        FastAPI · SQLAlchemy · Alembic (routers, services, engine, builder, llm, market, connectors)
apps/worker     Celery(흐름 실행, 문서 임베딩, 1분마다 예약 실행)
apps/web        React · Vite · React Flow · TanStack Query · Zustand · Tailwind
packages/nodes  NodeSpec 단계 레지스트리(26종)
market-items    기본 제공 마켓 아이템
docs            설계서, 기능 정의서·반영 현황, API 계약, 운영 안내, 결정 기록(ADR 0001~0013), 점검 보고서
```

## 문서
- 작업 규칙: [CLAUDE.md](CLAUDE.md)
- 설계서: [docs/design.md](docs/design.md)
- 기능 정의서(범위 기준): [docs/feature-spec.md](docs/feature-spec.md), 반영 현황: [docs/feature-coverage.md](docs/feature-coverage.md)
- API 계약: [docs/api.md](docs/api.md)
- 실행·공유·서버 설정: [docs/runbook.md](docs/runbook.md)
- 결정 기록(ADR): [docs/decisions](docs/decisions)
