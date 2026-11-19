# api 와 worker 가 함께 쓰는 이미지
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/apps:/app/packages

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY apps ./apps
COPY packages ./packages
COPY market-items ./market-items

# 사용자 코드 단계나 의존 라이브러리에 문제가 생겨도 컨테이너 전체 권한을 주지 않도록 일반 사용자로 실행한다.
# /data/files(파일 저장소 볼륨)와 /tmp(celery beat 일정 파일)만 쓰기 가능하게 한다.
RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin genio     && mkdir -p /data/files     && chown -R genio:genio /data/files
USER genio

EXPOSE 8000
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
