"""환경 변수 기반 설정. 값은 .env.example 참고."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    genio_env: str = "dev"
    genio_log_level: str = "INFO"
    database_url: str = "postgresql+psycopg://genio:genio@localhost:5432/genio"
    redis_url: str = "redis://localhost:6379/0"

    genio_builder_llm_provider: str = "anthropic"
    genio_builder_llm_model: str = "claude-sonnet-5-5"
    genio_embedding_provider: str = "openai"
    genio_embedding_model: str = "text-embedding-3-small"
    genio_embedding_dim: int = 1536
    genio_default_locale: str = "ko"


@lru_cache
def get_settings() -> Settings:
    return Settings()
