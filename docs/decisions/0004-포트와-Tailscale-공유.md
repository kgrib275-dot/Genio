# ADR 0004. 로컬 포트와 Tailscale 공유 방식

- 상태: 채택
- 날짜: 2026-11-03

## 배경
프로토타입을 이 PC(desktop-u122bbm)에서 띄우고 Tailscale로 공유해야 한다.
이 PC에는 이미 다른 서비스가 5173·8010·8020·5012 등을 쓰고, Tailscale Funnel(인터넷 공개)이 쓸 수 있는 포트 443·8443·10000은 모두 다른 서비스가 차지하고 있다.

## 결정
- **포트**: 쓰지 않던 번호로 고른다. web 5190, api 8190, postgres 55432, redis 56379. 모두 `127.0.0.1`에만 열어 사내 LAN에 노출하지 않는다.
- **진입점 하나**: 외부에는 web(5190)만 내보낸다. web(Vite)이 `/api`·`/health`를 api 컨테이너로 넘긴다. 그래서 SSE·공유 링크·위젯이 모두 같은 주소에서 동작한다.
- **Tailscale serve(tailnet 전용)**: `tailscale serve --bg --https=9443 http://127.0.0.1:5190`. 주소는 `https://desktop-u122bbm.tail6bd481.ts.net:9443`. 기존 Funnel 3개는 건드리지 않는다.
- **공유 링크 주소**: `.env`의 `GENIO_PUBLIC_WEB_URL`을 위 Tailscale 주소로 둔다. localhost 화면에서 배포해도 다른 사람이 열 수 있는 링크가 나온다.

## 대안
- **Funnel(인터넷 공개)**: 쓸 수 있는 포트 3개가 모두 사용 중이라, 기존 서비스 하나를 내려야 한다. 회원가입이 열린 프로토타입을 인터넷에 여는 위험도 있다. 필요하면 아래 명령으로 바꿀 수 있다(기존 서비스 하나를 대신함).
  ```
  tailscale funnel --bg --https=8443 http://127.0.0.1:5190
  ```
- **경로 공유(기존 443 아래 /genio)**: SPA·SSE의 기준 경로를 모두 바꿔야 해서 복잡하다.

## 영향
- 공유받는 사람은 같은 tailnet에 있거나, Tailscale 관리 화면에서 이 기기를 공유(Share)받아야 한다.
- 공유 해제: `tailscale serve --https=9443 off`
