# Genio (제니오)

말로 요청하면 빌더 챗봇이 흐름(워크플로우) 앱을 만들어 주고, 캔버스에서 다듬어 챗봇·웹훅·예약으로 운영하는 대화형 로우코드 플랫폼의 프로토타입이다. 목표는 "비개발자가 10분 안에 동작하는 앱을 말로 만들어 내는 것".

- 실행: `start_genio.bat` 더블클릭 (끄기: `stop_genio.bat`, 화면 코드를 고쳤으면 `start_genio.bat -Rebuild`)
- 공유 주소: https://genio.tail6bd481.ts.net (Tailscale Funnel, 인터넷 공개)
- 데모 계정: 처음 기동하면 `owner@example.com` 등 역할별 5개가 만들어진다(비밀번호는 [runbook](docs/runbook.md)). 로그인 화면에는 보이지 않는다. **공개 주소로 운영한다면 비밀번호를 바꾸거나 관리 > 멤버에서 정리할 것.**

## 할 수 있는 것
| 영역 | 기능 |
|---|---|
| 만들기 | 빌더 챗(말로 요청 → 블록·연결이 캔버스에 그려짐, 되묻기는 선택지 버튼), 캔버스(메모, 블록 끄기, 복사·붙여넣기·복제, 되돌리기, 미니맵, 자동 정렬, cURL 붙여넣기), 대화로 시험하기, 버전 저장·되돌리기 |
| 블록 24종 | 입력·출력·AI·조건·HTTP·코드·지식 검색·연결(커넥터)·승인, 질문 분류·값 뽑기·템플릿·값 합치기·목록 다루기·반복·되풀이·문서 읽기·변수 저장·에이전트, 기다리기·값 정리·날짜·시간·다른 앱 실행·데이터 표 |
| 실행 | 테스트 실행, 웹훅(외부 호출, 바로 받기·결과 기다리기), 예약(cron·쉬운 선택·시간대), 실패하면 다른 앱 실행, 지난 실행 다시 실행, 블록별 재시도·실패 분기 |
| 챗봇 | 공유 링크·웹사이트 위젯(색·위치·인사 말풍선)·서비스 API, 답변 실시간 표시, 마크다운·코드 복사, 다시 답하기·멈추기, 지난 대화·내보내기, 출처·이어질 질문·검열·모범 답변·파일·음성 |
| 데이터 | 지식베이스(조각 설정·부모-자식·혼합 검색·재정렬·메타데이터·웹 가져오기), 데이터 표(흐름이 저장·조회, CSV 가져오기·내보내기) |
| 운영 | 로그·모니터링·사용량·활동 기록, 모든 목록에 검색·필터·개수, 프로젝트(공개 범위)와 프로젝트 현황판 |
| 관리 | 소유자·관리자 콘솔(개요, 멤버·계정 만들기·비밀번호 재설정, AI 모델, API 키, 시스템 설정), 역할 5개, 개인 설정(테마·다크 모드·글자 크기) |
| 마켓 | 커넥터(Slack·Email·Google Sheets), 템플릿 5, 프롬프트 팩 2, 노드 1 |

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
packages/nodes  NodeSpec 노드 레지스트리(24종)
market-items    기본 제공 마켓 아이템
docs            설계서, API 계약, 운영 안내, 결정 기록(ADR 0001~0008), 점검 보고서
```

## 문서
- 작업 규칙: [CLAUDE.md](CLAUDE.md)
- 설계서: [docs/design.md](docs/design.md)
- API 계약: [docs/api.md](docs/api.md)
- 실행·공유·서버 설정: [docs/runbook.md](docs/runbook.md)
- 결정 기록(ADR): [docs/decisions](docs/decisions)
