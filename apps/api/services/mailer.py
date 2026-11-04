"""시스템 메일(인스턴스 SMTP): 비밀번호 찾기·이메일 인증 메일을 보낸다.

설정은 system_settings의 "mail" 행에 JSON으로 두고, 비밀번호는 Fernet으로 암호화한다.
화면·응답에는 ****abcd로만 보인다. 설정이 없으면 MailNotConfiguredError(두 줄 문장)를 낸다.
테스트는 OUTBOX를 켜서 실제로 보내지 않고 받은 편지함처럼 모은다.
"""

import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr
from typing import Any

from sqlalchemy.orm import Session

from api.core.crypto import decrypt_str, encrypt_str, mask
from api.core.errors import AppError
from api.models import SystemSetting

log = logging.getLogger("genio.mailer")
KEY = "mail"
SECURITY = ("starttls", "ssl", "none")
# 테스트용: None이 아니면 보내지 않고 여기에 쌓는다
OUTBOX: list[dict[str, str]] | None = None


class MailNotConfiguredError(AppError):
    def __init__(self) -> None:
        super().__init__(
            503,
            "메일 설정이 없어 메일을 보낼 수 없어요.",
            "관리자에게 관리 > 시스템 설정 > 시스템 메일 설정을 요청하세요.",
        )


def _raw(db: Session) -> dict[str, Any]:
    row = db.get(SystemSetting, KEY)
    return dict(row.value) if row is not None and isinstance(row.value, dict) else {}


def configured(db: Session) -> bool:
    cfg = _raw(db)
    return bool(cfg.get("host") and cfg.get("from_addr"))


def public_settings(db: Session) -> dict[str, Any]:
    cfg = _raw(db)
    enc = cfg.get("password_encrypted")
    return {
        "host": cfg.get("host") or "",
        "port": int(cfg.get("port") or 587),
        "username": cfg.get("username") or "",
        "password_masked": mask(decrypt_str(str(enc).encode())) if enc else "",
        "from_addr": cfg.get("from_addr") or "",
        "from_name": cfg.get("from_name") or "Genio",
        "security": cfg.get("security") or "starttls",
        "configured": bool(cfg.get("host") and cfg.get("from_addr")),
    }


def save_settings(db: Session, patch: dict[str, Any]) -> dict[str, Any]:
    cfg = _raw(db)
    for k in ("host", "username", "from_addr", "from_name"):
        if k in patch and patch[k] is not None:
            cfg[k] = str(patch[k]).strip()
    if patch.get("port") is not None:
        port = int(patch["port"])
        if not 1 <= port <= 65535:
            raise AppError(
                422, "포트 번호가 올바르지 않아요.", "보통 587(STARTTLS)이나 465(SSL)예요."
            )
        cfg["port"] = port
    if patch.get("security") is not None:
        if patch["security"] not in SECURITY:
            raise AppError(
                422, "보안 방식을 고르지 않았어요.", "STARTTLS·SSL·없음 중에서 고르세요."
            )
        cfg["security"] = patch["security"]
    pw = patch.get("password")
    # 비워 두거나 가려진 값(****)을 그대로 보내면 저장된 비밀번호를 유지한다
    if pw and not str(pw).startswith("****"):
        cfg["password_encrypted"] = encrypt_str(str(pw)).decode()
    if patch.get("clear_password"):
        cfg.pop("password_encrypted", None)
    row = db.get(SystemSetting, KEY)
    if row is None:
        db.add(SystemSetting(key=KEY, value=cfg))
    else:
        row.value = cfg
    db.commit()
    return public_settings(db)


def _deliver(cfg: dict[str, Any], msg: EmailMessage) -> None:
    host = str(cfg["host"])
    port = int(cfg.get("port") or 587)
    security = cfg.get("security") or "starttls"
    user = cfg.get("username") or ""
    enc = cfg.get("password_encrypted")
    password = decrypt_str(str(enc).encode()) if enc else ""
    ctx = ssl.create_default_context()
    if security == "ssl":
        with smtplib.SMTP_SSL(host, port, timeout=15, context=ctx) as smtp:
            if user:
                smtp.login(user, password)
            smtp.send_message(msg)
        return
    with smtplib.SMTP(host, port, timeout=15) as smtp:
        if security == "starttls":
            smtp.starttls(context=ctx)
        if user:
            smtp.login(user, password)
        smtp.send_message(msg)


def send(db: Session, to: str, subject: str, text: str) -> None:
    """시스템 메일 보내기. 설정이 없으면 MailNotConfigured, 보내다 실패하면 두 줄 AppError."""
    cfg = _raw(db)
    if not (cfg.get("host") and cfg.get("from_addr")):
        raise MailNotConfiguredError()
    if OUTBOX is not None:
        OUTBOX.append({"to": to, "subject": subject, "text": text})
        return
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((str(cfg.get("from_name") or "Genio"), str(cfg["from_addr"])))
    msg["To"] = to
    msg.set_content(text)
    try:
        _deliver(cfg, msg)
    except smtplib.SMTPAuthenticationError:
        raise AppError(
            502,
            "메일 서버 로그인에 실패했어요.",
            "관리 > 시스템 설정의 메일 아이디·비밀번호를 확인하세요.",
        ) from None
    except (OSError, smtplib.SMTPException) as exc:
        log.warning("시스템 메일 보내기 실패: %s", type(exc).__name__)
        raise AppError(
            502,
            "메일을 보내지 못했어요.",
            "메일 서버 주소·포트·보안 방식을 확인하거나 잠시 뒤 다시 시도하세요.",
        ) from None
