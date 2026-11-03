"""사람에게 알림 보내기(이메일·슬랙). 승인·질문·배정 요청에 쓴다(기능 정의서 S7).

설치된 커넥터(email, slack)와 워크스페이스 연결 정보로만 보낸다. 실패해도 흐름은 멈추지 않고
실행 기록에 남긴다. 링크 토큰은 비밀값처럼 다뤄 로그에 남기지 않는다.
"""

import logging
from typing import Any

from sqlalchemy.orm import Session

from api.config import get_settings
from api.connectors.runtime import run_connector
from nodes import NodeError

log = logging.getLogger("genio.notify")

KIND_LABEL = {"approval": "승인 요청", "question": "확인 요청", "assignment": "할 일 배정"}


def task_link(token: str) -> str:
    return f"{get_settings().genio_public_web_url.rstrip('/')}/t/{token}"


def send(
    db: Session,
    workspace_id: str,
    notify: dict[str, Any],
    *,
    kind: str,
    app_name: str,
    title: str,
    detail: str,
    token: str,
) -> list[str]:
    """알림을 보내고 결과 문장 목록을 돌려준다(실행 기록용, 받는 주소·토큰은 넣지 않는다)."""
    if not notify:
        return []
    label = KIND_LABEL.get(kind, "요청")
    link = task_link(token)
    text = f"[{app_name}] {label}: {title}\n{detail}\n\n바로 처리하기: {link}".strip()
    results: list[str] = []
    email = notify.get("email") or {}
    if email.get("credential_id") and email.get("to"):
        try:
            run_connector(
                db,
                workspace_id,
                connector="email",
                credential_id=str(email["credential_id"]),
                action="send_email",
                params={
                    "to": ", ".join(email["to"]),
                    "subject": f"[{app_name}] {label}: {title}"[:200],
                    "body": text,
                },
            )
            results.append(f"이메일로 {label}을 보냈어요({len(email['to'])}명).")
        except NodeError as exc:
            results.append(f"이메일을 보내지 못했어요: {exc.message}")
        except Exception:
            log.exception("알림 이메일 실패")
            results.append("이메일을 보내지 못했어요.")
    slack = notify.get("slack") or {}
    if slack.get("credential_id") and slack.get("channel"):
        try:
            run_connector(
                db,
                workspace_id,
                connector="slack",
                credential_id=str(slack["credential_id"]),
                action="post_message",
                params={"channel": str(slack["channel"]), "text": text},
            )
            results.append(f"슬랙 {slack['channel']} 채널로 {label}을 보냈어요.")
        except NodeError as exc:
            results.append(f"슬랙으로 보내지 못했어요: {exc.message}")
        except Exception:
            log.exception("알림 슬랙 실패")
            results.append("슬랙으로 보내지 못했어요.")
    return results
