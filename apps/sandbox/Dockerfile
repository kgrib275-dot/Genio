# 코드 실행 격리 서버(v0.8). 빌드 위치: 저장소 루트(docker compose가 context: . 로 부른다)
# DB·Redis·AI 키 라이브러리를 넣지 않는다. 일반 사용자(비 root)로 읽기 전용 파일시스템에서 돈다.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app
COPY apps/sandbox/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY apps/sandbox ./sandbox
# 파이썬 코드 실행기는 API 엔진과 같은 파일을 쓴다(한 곳에서만 고친다)
COPY apps/api/engine/_code_sandbox.py ./sandbox/py_child.py

RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin sandbox \
    && chmod -R a-w /app
USER 10001

EXPOSE 9100
CMD ["uvicorn", "sandbox.main:app", "--host", "0.0.0.0", "--port", "9100", "--workers", "2"]
