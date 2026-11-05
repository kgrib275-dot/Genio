# 실행 안내 (runbook)

## 주소
| 용도 | 주소 |
|---|---|
| 공유 주소(tailnet) | https://genio.tail6bd481.ts.net |
| 예전 공유 주소(계속 동작) | https://desktop-u122bbm.tail6bd481.ts.net:9443 |
| 이 PC에서 | http://127.0.0.1:5190 |
| API 문서(이 PC) | http://127.0.0.1:8190/docs |

포트: web 5190 · api 8190 · postgres 55432 · redis 56379. 모두 127.0.0.1에만 열려 있다(ADR 0004).

## 데모 계정
처음 기동할 때 "데모 회사" 워크스페이스와 계정 5개가 만들어진다. 비밀번호는 모두 `genio1234!`.
로그인 화면에는 더 이상 보여 주지 않는다. 계정은 관리 > 멤버의 **계정 만들기 / 비밀번호 재설정**으로 관리한다.
인터넷에 공개(Funnel)한 상태라면 owner로 로그인해 내 설정에서 비밀번호를 바꾸고, 나머지 데모 계정은 비밀번호를 재설정하거나 내보낸다.

| 역할 | 이메일 |
|---|---|
| owner | owner@example.com |
| admin | admin@example.com |
| builder | builder@example.com |
| operator | operator@example.com |
| member | member@example.com |

템플릿 5개와 프롬프트 팩 2개는 미리 설치돼 있다. 커넥터(Slack·Email·Google Sheets)는 데모 시나리오에서 마켓으로 설치한다.

## 가장 쉬운 실행
`start_genio.bat`을 더블클릭한다. Docker 켜기, `.env` 만들기, 컨테이너 실행, 준비 확인, 브라우저 열기까지 한 번에 한다.
- 코드를 고친 뒤: `start_genio.bat -Rebuild`
- 끄기: `stop_genio.bat` (데이터는 남음)

## 처음 한 번(수동)
```bash
cp .env.example .env
# GENIO_SECRET_KEY, GENIO_FERNET_KEY를 채운다
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# 공유 주소를 쓰면 GENIO_PUBLIC_WEB_URL=https://<기기>.ts.net:9443
docker compose up --build -d          # 또는 make up
```
api 컨테이너가 시작할 때 `alembic upgrade head`를 먼저 실행한다.

## 웹 화면 실행 방식
- docker compose의 web은 **배포용 빌드를 nginx로** 서빙한다(gzip, /assets 1년 캐시, /api·SSE 프록시). 첫 화면이 0.4초 안팎으로 뜬다.
- 화면 코드를 고친 뒤 반영: `start_genio.bat -Rebuild` (직접 할 때는 `docker compose up -d --build web` 다음 `docker compose up -d --force-recreate tailscale` — tailscale이 web 네트워크를 같이 쓰기 때문)
- 고치면서 바로 보고 싶을 때(개발 모드): `cd apps/web && npm run dev` → http://127.0.0.1:5190 (API는 8190으로 프록시). 이때는 web 컨테이너를 먼저 멈춘다.

## 공유 (Tailscale)
- **genio 주소**: compose의 `tailscale` 서비스가 tailnet에 `genio` 기기로 올라가 https://genio.tail6bd481.ts.net 을 연다.
  처음 한 번 `docker compose logs tailscale`에 나오는 로그인 링크로 승인한다(또는 `.env`에 `TS_AUTHKEY`). 링크는 승인할 때까지 바뀌지 않는다.
```bash
tailscale serve --bg --https=9443 http://127.0.0.1:5190   # 켜기(tailnet 전용)
tailscale serve status                                       # 확인
tailscale serve --https=9443 off                             # 끄기
```
- 같은 tailnet 사람은 위 공유 주소로 바로 들어온다. tailnet 밖 사람에게는 Tailscale 관리 화면에서 이 기기를 Share 한다.
- 인터넷 공개(Funnel)는 쓸 수 있는 포트 3개가 모두 다른 서비스에 쓰이고 있어 켜지 않았다(ADR 0004).

## AI 키 등록 (빌더·AI 노드를 쓰려면 필수)
1. owner로 로그인 → 워크스페이스 → AI 연결.
2. Anthropic(빌더용, 모델 `claude-sonnet-5-5`)을 기본으로 등록한다.
3. 지식베이스를 쓰려면 OpenAI(모델 `gpt-4o-mini`, 임베딩은 `text-embedding-3-small` 자동)도 등록한다.
키는 Fernet으로 암호화해 DB에 저장하고, 화면에는 `****abcd`만 보인다.

## 데모 시나리오 (설계서 §12)
1. **문의 분류 → 슬랙**: 빌더에 "고객 문의 메일을 분류해서 담당자 슬랙으로 보내 줘" → 슬랙 설치 카드에서 설치 → 연결 정보 화면에서 Slack Bot Token 등록 → 채널 질문에 답 → 테스트 결과 확인.
2. **규정 FAQ 챗봇**: 지식베이스에 사내 규정 PDF 업로드 → 빌더에 "사내 규정 문서로 질문에 답하는 챗봇 만들어 줘" → 버전 저장 → 배포·설정에서 공유 링크(우리 워크스페이스 멤버) → member 계정으로 링크 열어 질문.
3. **주간 보고 + 승인 메일**: 빌더에 "주간 보고 초안 만들어서 승인 후 메일로 보내 줘" → Google Sheets·Email 설치와 연결 정보 등록 → 테스트 실행이 승인 대기에서 멈춤 → 실행 기록에서 승인 → 메일 발송.

## 검사
```bash
make check            # make가 없으면(Windows): PYTHONUTF8=1 bash scripts/check.sh
```
- Python: ruff, mypy --strict, pytest(SQLite + 외래 키 강제, 가짜 LLM)
- Web: eslint, prettier, tsc, vitest
- 빌더 녹화 스냅샷 갱신: `UPDATE_SNAPSHOTS=1 pytest apps/api/tests/test_builder.py`

## 예약 실행(Celery beat, ADR 0008)
- 워커는 `celery ... worker -B`로 beat를 함께 돌린다. beat가 1분마다 `genio.dispatch_schedules`를 불러 `next_run_at`이 지난 예약 자동 실행을 큐에 넣는다.
- 워커 컨테이너를 2개 이상 띄우면 `-B`는 하나에만 둔다(둘 다 켜면 예약이 두 번 실행된다).
- 밀린 예약(워커가 꺼져 있던 동안)은 한 번만 실행하고 다음 시각부터 이어 간다.
- 웹훅 주소(`/api/v1/hooks/{token}`)는 비밀값이다. 새어 나갔으면 앱 > 자동 실행에서 '주소 다시 만들기'를 누른다. 토큰은 로그에 남기지 않는다.
- 웹훅·예약은 저장한 버전으로만 실행된다. 버전이 없으면 웹훅은 409, 예약은 건너뛰고 마지막 상태를 `no_version`으로 남긴다.

## 마이그레이션
```bash
export DATABASE_URL=postgresql+psycopg://genio:genio@127.0.0.1:55432/genio
alembic -c apps/api/alembic.ini revision --autogenerate -m "설명"
alembic -c apps/api/alembic.ini upgrade head
alembic -c apps/api/alembic.ini check      # 모델과 DB가 같은지
```
규칙: 컬럼 삭제·이름 변경 금지, downgrade 필수.

## Windows에서 알아 둘 것
- `make`가 없다 → `bash scripts/check.sh`.
- `requirements*.txt`, `alembic.ini`는 ASCII만 쓴다(pip·configparser가 cp949로 읽음).
- Docker Desktop 바인드 마운트는 파일 변경 알림을 넘기지 않는다 → web은 폴링 감시(`VITE_USE_POLLING=1`), api는 `apps/api`·`packages`만 감시.

## 문제 해결
| 증상 | 확인 |
|---|---|
| 빌더가 "등록된 AI 연결이 없어요" | 워크스페이스 > AI 연결에 키 등록 |
| 문서가 '실패' | 문서 행의 사유 확인(대부분 OpenAI 연결 없음) |
| 실행이 '대기 중'에서 안 움직임 | `docker compose logs worker` |
| 공유 주소가 안 열림 | `tailscale serve status`, 상대가 tailnet에 있는지 |

## 동시 사용자·서버 설정 (부하 시험 2026-11-03)
- API는 운영 설정으로 뜬다: `uvicorn --workers ${GENIO_API_WORKERS:-4}`, 코드 자동 재시작 없음. **API 코드를 고친 뒤에는 `docker compose restart api worker`** 로 반영한다.
- 코드를 고치며 바로바로 보고 싶을 때(개발): `docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d api` (프로세스 1개 + 자동 재시작).
- requirements*.txt를 바꾸면 이미지를 다시 만든다: `docker compose up -d --build api worker`.
- 조정 값(.env): `GENIO_API_WORKERS`(프로세스 수, CPU 코어 수 정도), `GENIO_API_THREADS`(프로세스당 작업 스레드, 기본 200), `GENIO_DB_POOL_SIZE`·`GENIO_DB_MAX_OVERFLOW`(프로세스당 DB 연결, 기본 10+10). PostgreSQL `max_connections=200`(compose).
  프로세스 수 x (풀+여분) + 워커가 200을 넘지 않게 한다.
- 요청 DB 세션은 엔드포인트 함수가 끝나면 바로 닫힌다(`DbDep`, scope=function). 응답을 스트리밍하는 동안 DB 연결을 붙잡지 않게 하려는 것이다. 스트리밍 코드 안에서 DB가 필요하면 `with SessionLocal()`로 짧게 열고, 세션 안에서 yield하지 않는다.
- 결과: docs/loadtest-2026-11-03.md


## v0.6 병렬 갈래 운영 값
- `GENIO_RUN_PARALLELISM`(기본 4, 1~16): 실행 하나 안에서 동시에 도는 갈래 수. 동시에 도는 갈래는 갈래마다 DB 연결을 하나씩 더 쓴다.
- DB 연결 어림: API 프로세스 수 × (풀 10 + 넘침 10) + 워커 동시성 × (1 + 병렬 수). 기본값(API 4, 워커 4, 병렬 4) = 80 + 20 = 100 < `max_connections=200`.
- 워커 동시성(`--concurrency`)이 한 번에 처리하는 실행 수다. AI 응답을 기다리는 흐름이 많으면 워커 동시성을 늘리는 것이 가장 효과가 크다(부하 시험 보고서 2026-11-04 참고).

## 운영 준비: 자동 백업·복구
- `docker compose up -d` 하면 `backup` 서비스가 함께 뜬다. 포트를 열지 않는다.
  - 매일 **3시(서울 시간)** `pg_dump -Fc`로 `./backups/genio-YYYYmmdd-HHMM.dump`를 만든다. 처음 켰을 때 최근 하루 안의 백업이 없으면 바로 한 번 만든다.
  - **7일**보다 오래된 백업은 지운다.
  - 바꾸기(.env): `GENIO_BACKUP_HOUR=3`, `GENIO_BACKUP_KEEP_DAYS=7`, `GENIO_BACKUP_TZ=Asia/Seoul`.
  - 결과는 `./backups/status.json`에 남고 **관리 > 시스템 상태**에 보인다. 30시간 넘게 새 백업이 없으면 '주의'로 바뀐다.
  - `./backups`는 깃에 올라가지 않는다. 이 PC가 망가지면 백업도 함께 사라지므로, 주기적으로 다른 곳(외장 디스크·클라우드)에 복사해 둔다.
- 복구: `bash scripts/restore_backup.sh backups/genio-20261104-0300.dump`
  - `yes`를 입력하면 api·worker를 멈추고, 지금 DB를 `backups/before-restore-*.dump`로 먼저 백업한 뒤 복구하고, 다시 시작한다.
  - 되돌리고 싶으면 그 `before-restore-*.dump`로 같은 명령을 다시 쓴다.

## 운영 준비: 시스템 상태·서버 오류 기록
- **관리 > 시스템 상태**(인스턴스 관리자 = 가장 먼저 만든 워크스페이스의 소유자만 보임). 30초마다 새로 확인한다.
  - 볼 수 있는 것: DB(응답 시간), Redis, 실행 워커(ping), 대기 중인 작업 수, 자동 백업, 디스크 남은 공간, 버전.
  - 숫자: 사용자·워크스페이스 수, 24시간 실행·실패·서버 오류 수.
- 버전 표시: 올릴 때 `GENIO_VERSION=<커밋 짧은 해시> docker compose up -d api worker`(비우면 '개발').
- 모든 API 응답에 `X-Request-ID`(문의 번호)가 붙는다. 처리하지 못한 오류(500) 화면에는 "문의할 때 이 번호를 알려 주세요: …"가 나온다.
- 그 오류와 실행 엔진 내부 오류는 `error_events` 표에 남고 **시스템 상태 > 서버 오류 기록**에서 문의 번호로 찾는다.
  - 남기는 것: 시각, 경로 틀, 오류 종류, 짧은 메시지(토큰·키·비밀번호·연결 문자열은 가림), 사용자·워크스페이스 id.
  - 남기지 않는 것: 요청 본문·헤더.
  - 30일 뒤 보관 기간 정리(매일)에서 지운다.

## 운영 준비: 콘텐츠 보안 정책(CSP)
- `apps/web/nginx.conf`가 화면 응답에 CSP를 붙인다.
  - 스크립트는 우리 서버 파일만 실행한다. 인라인 스크립트는 막으므로 테마 적용은 `/boot.js`로 옮겼다.
  - 스타일은 우리 서버, 인라인 style, jsdelivr(Pretendard 글꼴)만 허용한다.
  - 이미지는 `https:`·`data:`·`blob:`(답변 속 그림, 사진 미리 보기)을 허용한다.
  - API·SSE는 같은 주소만 부른다. `object-src 'none'`, `base-uri 'self'`.
- 액자(iframe): 공유 챗 `/share/…`만 모든 사이트에 넣을 수 있다(`frame-ancestors *`, X-Frame-Options 없음). 나머지는 같은 주소만(`'self'`, `SAMEORIGIN`).
  - nginx는 `$request_uri`로 판단한다. 예전 `$uri`는 SPA로 넘긴 뒤 `/index.html`이 되어 공유 챗도 막고 있었다.
- 새 외부 자원(다른 CDN·분석 스크립트)을 붙이면 CSP에 그 주소를 더해야 한다. 막히면 브라우저 콘솔에 "Refused to …"가 보인다.

## 운영 준비: 활동 기록 내보내기
- **관리 > 활동 기록 > CSV로 받기**(소유자·관리자): 화면에서 고른 종류·한 일·사람·기간·검색어 그대로 최대 5만 줄을 받는다.
- 엑셀에서 한글이 깨지지 않게 BOM을 붙인다. 부가 정보 중 key·token·secret·password·credential이 들어간 항목은 `****`로 바꾼다.

## v0.8 운영 안전 (ADR 0012)

### 1. 파일 저장소: DB · 디스크 · S3
올린 파일(채팅 첨부·앱 입력 파일·공유 썸네일)과 지식베이스 문서 본문을 어디에 둘지 고른다. **기본은 `db`(지금과 같음)**이라 아무것도 하지 않으면 바뀌는 것이 없다.

| 값 | 어디에 | 언제 쓰나 |
|---|---|---|
| `db` | DB 열(content) | 기본. 파일이 적을 때. DB 백업에 파일도 함께 들어간다 |
| `disk` | 서버 볼륨(`GENIO_STORAGE_DIR`, 컴포즈의 `filestore`) | 서버 한 대, DB를 가볍게 하고 싶을 때 |
| `s3` | S3 호환 저장소(AWS S3, RustFS, 사내 S3 등) | 서버가 여러 대이거나 파일이 많을 때 |

**바꾸는 법** (`.env` 수정 뒤 `docker compose up -d`로 api·worker를 다시 만든다)
- 디스크: `GENIO_STORAGE=disk`
- S3: `GENIO_STORAGE=s3`, `GENIO_S3_BUCKET`, `GENIO_S3_ACCESS_KEY`, `GENIO_S3_SECRET_KEY`, (AWS 밖이면 `GENIO_S3_ENDPOINT_URL`, MinIO·RustFS 같은 서버는 `GENIO_S3_PATH_STYLE=true`)
- 바꾼 뒤 **새로 올리는 파일만** 새 저장소에 쌓이고, 이미 올린 파일은 자기가 있던 곳(행의 `storage` 값)에서 계속 읽힌다. 섞여 있어도 된다.

**이미 있는 파일 옮기기** (저장소를 바꾼 뒤, 순서대로)
```bash
# 0) (처음 한 번, S3만) 버킷이 없으면 만든다
docker compose exec api python /app/scripts/migrate_files_to_storage.py --init-bucket
# 1) 먼저 얼마나 옮길지만 센다(아무것도 바꾸지 않음)
docker compose exec api python /app/scripts/migrate_files_to_storage.py --target s3 --dry-run
# 2) 옮긴다. 저장소에서 다시 읽어 크기·sha256이 맞을 때만 행을 바꾸고, DB 본문은 그대로 둔다
docker compose exec api python /app/scripts/migrate_files_to_storage.py --target s3
# 3) 며칠 써 보고 이상이 없으면 DB 본문을 비운다(DB가 가벼워진다)
docker compose exec api python /app/scripts/migrate_files_to_storage.py --target s3 --clear-db
```
- 중간에 멈춰도 같은 명령을 다시 돌리면 이어서 한다(배치마다 커밋). 한 건이라도 실패하면 종료 코드 1과 실패 목록이 나온다.
- **되돌리기**: 2번까지만 했다면(`--clear-db` 전) DB 본문이 그대로 있으니 `GENIO_STORAGE=db`로 돌리고 아래 SQL로 읽는 곳만 DB로 바꾸면 된다.
  `UPDATE files SET storage='db', storage_key=NULL; UPDATE documents SET storage='db', storage_key=NULL;`
  3번까지 했다면 먼저 저장소의 본문을 DB로 되돌린다: `... migrate_files_to_storage.py --restore-to-db`
- **고아 파일 찾기**(저장소에는 있는데 어떤 행도 가리키지 않는 키, 지우지는 않는다): `... --orphans s3`. 파일·문서를 지우면 저장소의 본문도 함께 지워지지만, 워크스페이스·앱을 통째로 지우면 남을 수 있다.
- 내려받은 파일 이름·형식 검사(15MB 상한, 허용 확장자)는 저장소와 상관없이 그대로다.

**자체 S3 서버가 필요하면** (이미 쓰는 S3가 있으면 건너뛴다): 컴포즈에 `objectstore`(RustFS, S3 호환)가 선택 서비스로 들어 있다. MinIO 공식 이미지는 더는 배포되지 않아 RustFS를 썼다.
```bash
# .env: GENIO_S3_ACCESS_KEY, GENIO_S3_SECRET_KEY(꼭 정한다. 비우면 서버가 시작을 거부한다),
#       GENIO_STORAGE=s3, GENIO_S3_ENDPOINT_URL=http://objectstore:9000, GENIO_S3_BUCKET=genio, GENIO_S3_PATH_STYLE=true
COMPOSE_PROFILES=storage docker compose up -d     # objectstore: 관리 화면은 127.0.0.1:59001 에서만 열린다(S3 주소는 내부망 전용)
docker compose exec api python /app/scripts/migrate_files_to_storage.py --init-bucket
```
- 이 서버의 데이터는 `objectdata` 볼륨에 있다. **백업 대상에 넣어야 한다**(아래 4번).

### 2. 코드 실행 격리 서버(sandbox)
코드 단계(파이썬·자바스크립트)를 API 서버 안이 아니라 **별도 컨테이너**에서 돌린다. 여러 사람이 코드를 쓰는 환경에서 권한이 높은 API 프로세스(DB·AI 키를 가진)와 사용자 코드를 떼어 놓기 위한 것이다. **기본은 꺼짐(서버 안 실행)**이고, 관리 > 시스템 상태의 "코드 실행" 줄에 지금 어디서 도는지 보인다.

**켜는 법**
```bash
# .env: GENIO_SANDBOX_KEY=<긴 무작위 문자열>, GENIO_SANDBOX_URL=http://sandbox:9100
COMPOSE_PROFILES=sandbox docker compose up -d --build
```
**네트워크·권한 모델**
- `sandbox`는 `sandbox_net`(**internal: true** = 바깥 인터넷으로 나가는 길이 없는 내부망)에만 붙는다. api·worker는 기존 네트워크에 더해 `sandbox_net`에도 붙어서 부를 수 있다. DB·Redis에는 닿지 못한다.
- 비 root 사용자(uid 10001), 읽기 전용 파일시스템(`/tmp`만 64MB tmpfs), 모든 리눅스 권한 제거(`cap_drop: ALL`), `no-new-privileges`, 메모리 2GB·CPU 2개·프로세스 256개 제한.
- 코드 한 건마다 새 프로세스를 띄워 CPU·메모리(기본 512MB, `SANDBOX_MEMORY_MB`)·파일 수·파일 크기·프로세스 수 제한(`resource`)을 걸고, 제한 시간이 지나면 프로세스를 죽인다. 결과는 1MB까지.
- API 요청은 공유 키(`X-Sandbox-Key`)로 인증한다. **키가 비어 있으면 서버가 실행을 거절한다**(열어 둔 채로 뜨지 않음). 동시 실행은 프로세스당 `SANDBOX_MAX_CONCURRENT`(기본 4)개, 넘으면 "바빠요".
- 코드에서 파일·네트워크·`os`는 원래 막혀 있고(허용 모듈만), 이 구성은 그 뒤에 한 겹을 더 두는 것이다.
- 확인: `docker compose logs sandbox`, 시스템 상태 "코드 실행"이 정상(응답 ms)이면 된다. 응답이 없으면 코드 단계가 "코드 실행 서버에 연결하지 못했어요"로 실패한다. 급하면 `.env`의 `GENIO_SANDBOX_URL`을 비우고 api·worker를 다시 만들면 바로 서버 안 실행으로 돌아간다.

### 3. 오류 수집(Sentry, 선택)
- `.env`에 `SENTRY_DSN`을 넣으면 api·worker의 처리되지 않은 오류가 Sentry로 간다. 비워 두면 아무것도 보내지 않는다. 이 서버의 서버 오류 기록(관리 > 시스템 상태)은 Sentry와 상관없이 계속 남는다.
- 사용자·요청(헤더·쿠키·본문·주소의 쿼리)·지역 변수·서버 이름은 보내지 않고, 글에서 토큰·키·비밀번호처럼 보이는 값은 `****`로 가린다. HTTP 호출 기록(breadcrumb)은 보내지 않는다.
- 성능 추적은 기본 꺼짐(`SENTRY_TRACES_SAMPLE_RATE=0`). 버전(`GENIO_VERSION`)이 release로 붙는다.

### 4. 백업: 파일을 S3로 옮기면 무엇을 챙기나
- DB 백업(`backups/`)에는 **저장소를 `db`로 쓴 파일만** 들어 있다. `disk`·`s3`로 옮긴 파일은 DB 백업에 **없다**(행에는 어디에 있는지만 남는다).
- 그래서 저장소를 옮기면 **DB 백업과 파일 저장소를 같은 시점에 맞춰 백업**해야 복구할 수 있다.
  - `disk`: `filestore` 볼륨(컨테이너 `/data/files`)을 같이 백업한다.
  - `s3`: 버킷 버전 관리(또는 다른 버킷으로 복제)를 켜 둔다. 자체 서버면 `objectdata` 볼륨을 백업한다.
- 복구 순서: DB 복구(`scripts/restore_backup.sh`) → 파일 저장소 복구 → 시스템 상태·파일 열어 보기로 확인. 행은 있는데 파일이 없으면 "저장된 파일을 찾지 못했어요"가 나온다.
- 옮기기 전에 백업을 한 번 받아 두고, `--clear-db`는 저장소 쪽 백업까지 확인한 뒤에만 쓴다.
