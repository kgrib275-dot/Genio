"""환경 값 기반 설정. 값의 의미는 .env.example 참고."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    genio_env: str = "dev"
    genio_log_level: str = "INFO"
    # 개발용 기본값. 운영에서는 반드시 .env의 GENIO_SECRET_KEY로 바꾼다.
    genio_secret_key: str = "dev-secret-change-me-please-32bytes!!"  # noqa: S105
    genio_fernet_key: str = ""
    genio_public_web_url: str = "http://localhost:5190"
    genio_seed_demo: bool = True

    database_url: str = "sqlite:///./genio-dev.db"
    redis_url: str = ""
    celery_broker_url: str = ""
    celery_result_backend: str = ""
    # 테스트·로컬에서 워커 없이 바로 실행할 때 true
    genio_run_inline: bool = False

    access_token_minutes: int = 15
    refresh_token_days: int = 7

    genio_builder_llm_provider: str = "anthropic"
    genio_builder_llm_model: str = "claude-sonnet-5-5"
    genio_embedding_provider: str = "openai"
    genio_embedding_model: str = "text-embedding-3-small"
    genio_embedding_dim: int = 1536
    genio_default_locale: str = "ko"

    genio_http_timeout_seconds: float = 15.0
    genio_http_max_response_bytes: int = 1_048_576
    genio_code_node_timeout_seconds: float = 10.0
    genio_node_timeout_seconds: float = 60.0
    genio_run_timeout_seconds: float = 600.0
    # 운영 준비: 화면에 보일 버전(빌드할 때 커밋 짧은 해시를 넣음), 백업 폴더(status.json을 읽음)
    genio_version: str = "dev"
    genio_backup_dir: str = "/backups"
    # v0.6: 한 실행 안에서 동시에 도는 갈래 수(1~16)
    genio_run_parallelism: int = 4
    genio_public_rate_limit_per_minute: int = 30
    # API 프로세스 하나의 작업 스레드 수와 DB 연결 수(프로세스 수는 GENIO_API_WORKERS, compose)
    genio_api_threads: int = 200
    genio_db_pool_size: int = 10
    genio_db_max_overflow: int = 10
    # 사설망 호출 허용(테스트 전용). 운영에서는 항상 false.
    genio_allow_private_network: bool = False
    # v0.5 보안(부하 시험 보고서 §4)
    # X-Forwarded-For를 믿을 프록시(이 주소에서 온 요청만 헤더의 IP를 쓴다). 쉼표로 구분한 CIDR.
    genio_trusted_proxies: str = (
        "127.0.0.0/8,::1/128,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,fc00::/7"
    )
    # 브라우저에서 API를 부를 수 있는 주소(GENIO_PUBLIC_WEB_URL과 localhost는 늘 허용). 쉼표로 구분.
    genio_cors_origins: str = ""
    # 로그인 실패 제한: 같은 이메일+IP 15분에 5번, 같은 이메일 15분에 20번
    genio_login_max_fails: int = 5
    genio_login_max_fails_per_email: int = 20
    genio_login_lock_seconds: int = 900

    market_items_dir: str = "market-items"


@lru_cache
def get_settings() -> Settings:
    return Settings()
