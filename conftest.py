"""테스트 공통 환경. api 패키지를 불러오기 전에 환경 변수를 정한다."""

import os

os.environ.update(
    {
        "DATABASE_URL": "sqlite://",
        "REDIS_URL": "",
        "CELERY_BROKER_URL": "memory://",
        "GENIO_RUN_INLINE": "true",
        "GENIO_SEED_DEMO": "false",
        "GENIO_SECRET_KEY": "test-secret-key-for-genio-tests-0123456789",
        "GENIO_NODE_TIMEOUT_SECONDS": "20",
    }
)
