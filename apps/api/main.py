"""FastAPI 진입점.

`/health`는 인프라 확인용이라 인증이 필요 없다. 업무 라우터는 `routers/`에 두고
모두 `require_role` 의존성을 건다(1단계에서 추가).
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.config import get_settings

app = FastAPI(title="Genio API", version="0.0.1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    settings = get_settings()
    return {"status": "ok", "env": settings.genio_env}
