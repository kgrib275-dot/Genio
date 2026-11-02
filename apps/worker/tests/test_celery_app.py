from worker.celery_app import celery, ping


def test_ping_task_registered() -> None:
    assert "genio.ping" in celery.tasks
    assert ping.run() == "pong"
