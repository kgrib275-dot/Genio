# Genio (제니오)

말로 요청하면 빌더 챗봇이 흐름(워크플로우) 앱을 만들어 주고, 캔버스에서 다듬어 챗봇으로 배포하는 대화형 로우코드 플랫폼의 프로토타입.

- 실행: `start_genio.bat` 더블클릭 (끄기: `stop_genio.bat`)
- 공유 주소(tailnet): https://genio.tail6bd481.ts.net
- 데모 계정: `owner@example.com` 등 5개, 비밀번호 `genio1234!` ([runbook](docs/runbook.md))

## 문서
- 작업 규칙: [CLAUDE.md](CLAUDE.md)
- 설계서: [docs/design.md](docs/design.md)
- API 계약: [docs/api.md](docs/api.md)
- 실행·공유·데모: [docs/runbook.md](docs/runbook.md)
- 결정 기록(ADR): [docs/decisions](docs/decisions)

## 구성
```
apps/api      FastAPI · SQLAlchemy · Alembic (routers, services, engine, builder, llm, market, connectors)
apps/worker   Celery 태스크(흐름 실행, 문서 임베딩)
apps/web      React · Vite · React Flow · TanStack Query · Zustand · Tailwind
packages/nodes  NodeSpec 노드 레지스트리(기본 9종)
market-items  기본 제공 마켓 아이템(커넥터 3, 템플릿 5, 프롬프트 팩 2, 노드 1)
```

## 빠른 시작
```bash
cp .env.example .env    # 키 채우기
docker compose up --build -d
open http://127.0.0.1:5190
```
