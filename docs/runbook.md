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
- 화면 코드를 고친 뒤 반영: `docker compose up -d --build web`
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
