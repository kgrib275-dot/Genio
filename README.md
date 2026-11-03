# Genio (제니오)

**Dify(AI 앱·지식베이스) + n8n(자동화·연결·트리거) + 챗봇**을 하나로 합친 노코드 챗봇 기반 흐름(워크플로우) 도구의 프로토타입이다. 말로 요청하면 빌더가 흐름을 만들고, 캔버스에서 다듬어 챗봇·입력 폼·외부에서 받기·예약으로 운영한다. 목표는 "기획자(비개발자)가 10분 안에 동작하는 앱을 말로 만들어 내는 것".

- **처음이라면**: 화면 왼쪽 아래 **배우기**에서 샘플 10가지를 열어 강좌 8개를 따라 하세요(Dify·n8n 이름 대응표 포함).

- 실행: `start_genio.bat` 더블클릭 (끄기: `stop_genio.bat`, 화면 코드를 고쳤으면 `start_genio.bat -Rebuild`)
- 공유 주소: https://genio.tail6bd481.ts.net (Tailscale Funnel, 인터넷 공개)
- 데모 계정: 처음 기동하면 `owner@example.com` 등 역할별 5개가 만들어진다(비밀번호는 [runbook](docs/runbook.md)). 로그인 화면에는 보이지 않는다. **공개 주소로 운영한다면 비밀번호를 바꾸거나 관리 > 멤버에서 정리할 것.**

## 할 수 있는 것
| 영역 | 기능 |
|---|---|
| 만들기 | 빌더 챗(말로 생성·되묻기 버튼·부분 수정·설명 모드·자동 시험·오류 해결), 캔버스(메모, 단계 끄기, 복사·붙여넣기·복제, 되돌리기, 미니맵, 자동 정렬), 값 끌어오기(칩·자동완성·고급 모드), 대화로 시험, 샘플 입력 저장, 버전 저장·되돌리기 |
| 단계 26종 | 입력·결과·AI·조건·외부 호출(인증·페이지 넘김·시험 호출·cURL)·코드(파이썬·자바스크립트)·지식 검색·연결·승인(승인/반려 갈래·알림·링크), 질문 분류·값 뽑기·템플릿·값 합치기·목록 다루기·반복·되풀이·문서 읽기·값 저장·에이전트, 기다리기·값 정리·날짜·시간·다른 앱 실행·데이터 표, 사람에게 묻기·담당자 배정 |
| 실행 | 테스트 실행, 외부에서 받기(서명 검증·받은 값 미리 보기), 예약, 실패하면 다른 앱 실행, 다시 실행·이 단계부터 다시, 단계별 재시도·제한 시간·실패 갈래, **실행 결과를 문장으로 설명** + '빌더에게 고쳐 달라고 하기' |
| 챗봇 | 공유 링크·위젯·서비스 API·흐름 앱 입력 폼, 실시간 답변·멈추기, 마크다운, 지난 대화·내보내기, 출처·이어질 질문·검열·모범 답변·파일·음성, **챗에서 흐름·승인 실행 → 결과가 대화로**, 상담원 전환 |
| 사람 개입 | 작업함(승인·질문·배정), 로그인 없이 링크로 결정, 이메일·슬랙 알림 |
| 데이터 | 지식베이스(PDF·DOCX·PPTX·XLSX·HTML·URL, 조각 설정, 혼합 검색, 재정렬, 문서 켜기·끄기, 지식베이스별 임베딩 모델), 데이터 표(CSV 가져오기·내보내기) |
| 연결 | Slack·이메일·Google Sheets·DB(PostgreSQL·MySQL)·HTTP 인증 정보·잔디·네이버웍스·카카오 알림톡, 연결 테스트 |
| AI | OpenAI·Anthropic·Google·Azure·OpenAI 호환, 모델 목록·기본 모델, 실행·앱·사용자별 비용, 모델 교체 예상 비용, 월 한도·알림 |
| 운영·관리 | 로그·모니터링·사용량·활동 기록, 모든 목록 검색·필터·개수, 프로젝트 현황판, 소유자·관리자 콘솔(계정 만들기·비밀번호 재설정), 역할 5개·배포 대상 사용자·API 키 권한 범위, 보관 기간, 개인 설정(다크 모드) |
| 마켓 | 커넥터·템플릿(업무 단위 5개 포함, 미리 보기)·프롬프트 팩·단계, 설치·업데이트 |
| 배우기 | 샘플 10가지(7개는 AI 키 없이 동작), 따라 하기 강좌 8개, Dify·n8n 이름 대응표 |

기능 정의서와 반영 현황: [docs/feature-spec.md](docs/feature-spec.md) · [docs/feature-coverage.md](docs/feature-coverage.md)
다른 서비스와 비교(Dify·n8n·Zapier·Make·Flowise): [docs/dify-gap.md](docs/dify-gap.md)

## 성능·데이터·보안 점검 (2026-11-03, 개발용 PC 1대)
- 1,000명이 각자 가입~앱 만들기~배포~챗~실행~데이터 표~웹훅까지 사용: 요청 25,000개 실패 0.
- 동시 100명: 고치기 전에는 서버가 멈췄으나, API를 운영 설정(프로세스 4개)으로 바꾸고 응답 스트리밍 중 DB 연결을 붙잡지 않게 고친 뒤 **1,000명 모두 성공, 실패 0**. 지금 한계는 PC의 CPU다.
- 데이터: 컨테이너를 지우고 다시 만들어도, 백업(pg_dump)을 새 DB에 복구해도 모든 수치가 같았다.
- 보안: 사용자 간 접근 4,000번 시도 모두 차단, 위조 토큰·내부망 호출·SQL 주입·XSS 차단, 비밀값 마스킹. 남은 과제(로그인 시도 제한 등)는 보고서 참고.
- 자세히: [docs/loadtest-2026-11-03.md](docs/loadtest-2026-11-03.md)

## 빠른 시작
```bash
cp .env.example .env          # 키 채우기(GENIO_SECRET_KEY, GENIO_FERNET_KEY 등)
docker compose up --build -d  # postgres, redis, api(프로세스 4), worker(+예약), web(nginx), tailscale
open http://127.0.0.1:5190
```
- API 코드를 고친 뒤: `docker compose restart api worker` (운영 설정이라 자동 재시작 없음)
- 개발 중 자동 재시작: `docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d api`
- requirements를 바꾼 뒤: `docker compose up -d --build api worker`
- 검사: `make check` (Windows는 `PYTHONUTF8=1 bash scripts/check.sh`) — ruff·mypy·pytest·eslint·tsc·vitest

## 구성
```
apps/api        FastAPI · SQLAlchemy · Alembic (routers, services, engine, builder, llm, market, connectors)
apps/worker     Celery(흐름 실행, 문서 임베딩, 1분마다 예약 실행)
apps/web        React · Vite · React Flow · TanStack Query · Zustand · Tailwind
packages/nodes  NodeSpec 단계 레지스트리(26종)
market-items    기본 제공 마켓 아이템
docs            설계서, 기능 정의서·반영 현황, API 계약, 운영 안내, 결정 기록(ADR 0001~0009), 점검 보고서
```

## 문서
- 작업 규칙: [CLAUDE.md](CLAUDE.md)
- 설계서: [docs/design.md](docs/design.md)
- 기능 정의서(범위 기준): [docs/feature-spec.md](docs/feature-spec.md), 반영 현황: [docs/feature-coverage.md](docs/feature-coverage.md)
- API 계약: [docs/api.md](docs/api.md)
- 실행·공유·서버 설정: [docs/runbook.md](docs/runbook.md)
- 결정 기록(ADR): [docs/decisions](docs/decisions)
