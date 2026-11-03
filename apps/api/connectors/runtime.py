"""커넥터 실행 런타임.

커넥터 코드(market-items/<key>/connector.py)는 액션 이름과 같은 함수를 둔다:
    def post_message(params: dict, secrets: dict, net: ConnectorNet) -> dict
네트워크는 net으로만 쓸 수 있고, manifest의 permissions에 선언한 도메인만 호출할 수 있다.
비밀값은 함수에만 넘기고, 로그·오류에서는 지운다.
"""

import smtplib
from email.message import EmailMessage
from typing import Any

from jsonschema import Draft202012Validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.connectors import database
from api.core.crypto import decrypt_json, redact
from api.engine import safe_http
from api.market.bundle import BundleError, allowed_domains, load_module
from api.market.service import bundle_path, installed_items
from api.models import ConnectorCredential, ConnectorDefinition, Workspace
from nodes import NodeError

SMTP_PORTS = {25, 465, 587, 2525}


class ConnectorNet:
    def __init__(self, manifest: dict[str, Any], allow_hosts: list[str] | None = None) -> None:
        self.domains = allowed_domains(manifest)
        self.smtp_allowed = bool(manifest.get("smtp"))
        self.database_allowed = bool(manifest.get("database"))
        # 워크스페이스 관리자가 허용한 내부 호스트(사내 DB 등)
        self.allow_hosts = list(allow_hosts or [])

    def _sql(self, mode: str, secrets: dict[str, Any], sql: str, params: Any) -> dict[str, Any]:
        if not self.database_allowed:
            raise NodeError("이 커넥터는 데이터베이스 접속 권한을 선언하지 않았어요.")
        try:
            port = int(secrets.get("port") or 0)
        except (TypeError, ValueError) as exc:
            raise NodeError("데이터베이스 포트는 숫자여야 해요. 연결 정보를 확인하세요.") from exc
        engine = str(secrets.get("engine") or "postgresql").strip().lower()
        if not port:
            port = 3306 if engine == "mysql" else 5432
        return database.run_sql(
            engine=engine,
            host=str(secrets.get("host") or ""),
            port=port,
            database=str(secrets.get("database") or ""),
            user=str(secrets.get("user") or ""),
            password=str(secrets.get("password") or ""),
            ssl=str(secrets.get("ssl") or "").strip().lower() in ("1", "true", "yes", "예", "on"),
            sql=sql,
            params=params if isinstance(params, dict) else {},
            mode=mode,
            allow_hosts=self.allow_hosts,
        )

    def sql_query(self, secrets: dict[str, Any], sql: str, params: Any = None) -> dict[str, Any]:
        return self._sql("query", secrets, sql, params)

    def sql_execute(self, secrets: dict[str, Any], sql: str, params: Any = None) -> dict[str, Any]:
        return self._sql("execute", secrets, sql, params)

    def check_mail(
        self, *, host: str, port: int, username: str, password: str, use_ssl: bool = False
    ) -> dict[str, Any]:
        """메일 서버에 로그인만 해 본다(연결 테스트)."""
        if not self.smtp_allowed:
            raise NodeError("이 커넥터는 메일 발송 권한을 선언하지 않았어요.")
        if int(port) not in SMTP_PORTS:
            raise NodeError(f"메일 서버 포트 {port}는 쓸 수 없어요(25, 465, 587, 2525만 가능).")
        safe_http.check_url(f"https://{host}:{port}/")
        try:
            if use_ssl or int(port) == 465:
                with smtplib.SMTP_SSL(host, int(port), timeout=15) as smtp:
                    smtp.login(username, password)
                    smtp.noop()
            else:
                with smtplib.SMTP(host, int(port), timeout=15) as smtp:
                    smtp.starttls()
                    smtp.login(username, password)
                    smtp.noop()
        except smtplib.SMTPAuthenticationError as exc:
            raise NodeError(
                "메일 서버 로그인에 실패했어요. 연결 정보의 아이디·비밀번호를 확인하세요."
            ) from exc
        except (TimeoutError, smtplib.SMTPException, OSError) as exc:
            raise NodeError(f"메일 서버에 연결하지 못했어요({type(exc).__name__}).") from exc
        return {"ok": True}

    def http(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json: Any = None,
        form: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        return safe_http.request(
            method.upper(), url, headers=headers, body=json, form=form, allowed_domains=self.domains
        )

    def send_mail(
        self,
        *,
        host: str,
        port: int,
        username: str,
        password: str,
        sender: str,
        to: list[str],
        subject: str,
        body: str,
        use_ssl: bool = False,
    ) -> dict[str, Any]:
        if not self.smtp_allowed:
            raise NodeError("이 커넥터는 메일 발송 권한을 선언하지 않았어요.")
        if int(port) not in SMTP_PORTS:
            raise NodeError(f"메일 서버 포트 {port}는 쓸 수 없어요(25, 465, 587, 2525만 가능).")
        safe_http.check_url(f"https://{host}:{port}/")
        msg = EmailMessage()
        msg["From"] = sender
        msg["To"] = ", ".join(to)
        msg["Subject"] = subject
        msg.set_content(body)
        try:
            if use_ssl or int(port) == 465:
                with smtplib.SMTP_SSL(host, int(port), timeout=15) as smtp:
                    smtp.login(username, password)
                    smtp.send_message(msg)
            else:
                with smtplib.SMTP(host, int(port), timeout=15) as smtp:
                    smtp.starttls()
                    smtp.login(username, password)
                    smtp.send_message(msg)
        except smtplib.SMTPAuthenticationError as exc:
            raise NodeError(
                "메일 서버 로그인에 실패했어요. 연결 정보의 아이디·비밀번호를 확인하세요."
            ) from exc
        except (TimeoutError, smtplib.SMTPException, OSError) as exc:
            raise NodeError(
                f"메일을 보내지 못했어요({type(exc).__name__}).", retryable=True
            ) from exc
        return {"sent": True, "to": to}


def _definition(
    db: Session, workspace_id: str, key: str
) -> tuple[ConnectorDefinition, dict[str, Any]]:
    items = {i.key: i for i in installed_items(db, workspace_id, "connector")}
    item = items.get(key)
    if item is None:
        raise NodeError(f"'{key}' 서비스가 설치되어 있지 않아요. 마켓에서 설치해 주세요.")
    definition = db.scalar(
        select(ConnectorDefinition).where(
            ConnectorDefinition.key == key, ConnectorDefinition.version == item.version
        )
    )
    if definition is None:
        raise NodeError(f"'{key}' 서비스 정의를 찾지 못했어요. 마켓에서 다시 설치해 주세요.")
    return definition, item.manifest


def run_connector(
    db: Session,
    workspace_id: str,
    *,
    connector: str,
    credential_id: str,
    action: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    definition, manifest = _definition(db, workspace_id, connector)
    cred = db.get(ConnectorCredential, credential_id)
    if cred is None or cred.workspace_id != workspace_id:
        raise NodeError("연결 정보를 찾을 수 없어요. 단계 설정에서 다시 골라 주세요.")
    cred_def = db.get(ConnectorDefinition, cred.definition_id)
    if cred_def is None or cred_def.key != connector:
        raise NodeError("다른 서비스의 연결 정보가 선택돼 있어요.")
    spec = next((a for a in manifest.get("actions", []) if a.get("key") == action), None)
    if spec is None:
        raise NodeError(f"'{connector}' 서비스에는 '{action}' 동작이 없어요.")
    schema = spec.get("input_schema") or {"type": "object"}
    errors = list(Draft202012Validator(schema).iter_errors(params))
    if errors:
        props = schema.get("properties", {})
        missing = [k for k in schema.get("required", []) if k not in params]
        if missing:
            names = ", ".join(props.get(k, {}).get("title", k) for k in missing)
            raise NodeError(f"동작 설정에 빠진 값이 있어요: {names}")
        raise NodeError("동작 설정 값의 형식이 맞지 않아요.")
    secrets = decrypt_json(cred.secret_encrypted)
    secret_values = [str(v) for v in secrets.values()]
    try:
        item_path = bundle_path(_item_for(db, workspace_id, connector))
        module = load_module(item_path / "connector.py", f"{connector}_connector")
        fn = getattr(module, action, None)
        if fn is None or not callable(fn):
            raise NodeError(f"'{action}' 동작 코드가 없어요. 확장 게시자에게 문의하세요.")
        result = fn(
            params, secrets, ConnectorNet(manifest, allowed_private_hosts(db, workspace_id))
        )
    except NodeError as exc:
        raise NodeError(redact(exc.message, secret_values), retryable=exc.retryable) from None
    except BundleError as exc:
        raise NodeError(f"확장 코드를 불러오지 못했어요: {exc}") from None
    except Exception as exc:
        raise NodeError(
            redact(f"서비스 동작 중 오류: {type(exc).__name__}: {exc}", secret_values)
        ) from None
    if not isinstance(result, dict):
        return {"result": result}
    del definition
    return result


def _item_for(db: Session, workspace_id: str, key: str) -> Any:
    for item in installed_items(db, workspace_id, "connector"):
        if item.key == key:
            return item
    raise NodeError(f"'{key}' 서비스가 설치되어 있지 않아요.")


def allowed_private_hosts(db: Session, workspace_id: str) -> list[str]:
    """관리자가 허용한 내부 호스트(워크스페이스 설정 allow_private_hosts)."""
    ws = db.get(Workspace, workspace_id)
    hosts = (ws.settings or {}).get("allow_private_hosts") if ws else None
    return [str(h) for h in hosts] if isinstance(hosts, list) else []


def test_credential(db: Session, workspace_id: str, credential_id: str) -> dict[str, Any]:
    """연결 정보가 실제로 되는지 확인한다. 커넥터 코드의 test(secrets, net) 함수를 부른다.

    반환: {ok, message, checked}. 비밀값은 메시지에서 지운다.
    """
    cred = db.get(ConnectorCredential, credential_id)
    if cred is None or cred.workspace_id != workspace_id:
        raise NodeError("연결 정보를 찾을 수 없어요.")
    cred_def = db.get(ConnectorDefinition, cred.definition_id)
    if cred_def is None:
        raise NodeError("연결 정보의 서비스 정의를 찾지 못했어요.")
    _, manifest = _definition(db, workspace_id, cred_def.key)
    secrets = decrypt_json(cred.secret_encrypted)
    secret_values = [str(v) for v in secrets.values() if str(v)]
    try:
        module = load_module(
            bundle_path(_item_for(db, workspace_id, cred_def.key)) / "connector.py",
            f"{cred_def.key}_connector",
        )
        fn = getattr(module, "test", None)
        if fn is None or not callable(fn):
            return {
                "ok": True,
                "checked": False,
                "message": "이 서비스는 연결 확인 기능이 없어요. 흐름에서 직접 시험해 보세요.",
            }
        out = fn(secrets, ConnectorNet(manifest, allowed_private_hosts(db, workspace_id)))
        detail = str((out or {}).get("message", "")) if isinstance(out, dict) else ""
        return {
            "ok": True,
            "checked": True,
            "message": redact(detail or "연결이 잘 돼요.", secret_values),
        }
    except NodeError as exc:
        return {"ok": False, "checked": True, "message": redact(exc.message, secret_values)}
    except BundleError as exc:
        return {"ok": False, "checked": False, "message": f"확장 코드를 불러오지 못했어요: {exc}"}
    except Exception as exc:
        return {
            "ok": False,
            "checked": True,
            "message": redact(f"확인 중 오류: {type(exc).__name__}: {exc}", secret_values)[:300],
        }
