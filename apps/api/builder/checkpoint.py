"""빌더 차례 되돌리기(체크포인트).

빌더가 한 차례에 흐름을 바꾸면 바꾸기 전 모습과 바꾼 뒤 모습의 지문을 그 차례 기록에 남긴다.
사용자가 '이 차례 되돌리기'를 누르면 작업본을 바꾸기 전 모습으로 되돌린다. 그 뒤에 흐름이 또 바뀌었으면
(내가 캔버스에서 고쳤거나 다음 차례가 바꿨으면) 그 변경까지 사라지므로 한 번 더 확인을 받는다.
"""

import copy
import hashlib
import json
from typing import Any

from sqlalchemy.orm import Session

from api.core.errors import AppError, not_found
from api.models import App, BuilderMessage, BuilderSession
from api.schemas.graph import Graph, empty_graph


def graph_hash(raw: dict[str, Any] | None) -> str:
    g = Graph.model_validate(raw or empty_graph()).dump()
    return hashlib.sha256(json.dumps(g, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def snapshot(raw: dict[str, Any] | None) -> dict[str, Any]:
    return copy.deepcopy(Graph.model_validate(raw or empty_graph()).dump())


def attach(record: dict[str, Any], before: dict[str, Any], after: dict[str, Any] | None) -> None:
    """바꾼 차례의 기록에 체크포인트를 붙인다."""
    record["checkpoint"] = {"graph": before, "after_hash": graph_hash(after)}


def public_record(patch: dict[str, Any] | None) -> dict[str, Any] | None:
    """화면에는 흐름 전체를 보내지 않고 되돌릴 수 있는지만 알린다."""
    if not isinstance(patch, dict) or "checkpoint" not in patch:
        return patch
    out = {k: v for k, v in patch.items() if k != "checkpoint"}
    out["revertible"] = not patch.get("reverted")
    return out


def revert_turn(
    db: Session, session_id: str, message_id: str, *, force: bool = False
) -> dict[str, Any]:
    msg = db.get(BuilderMessage, message_id)
    if msg is None or msg.session_id != session_id or msg.role != "assistant":
        raise not_found("빌더 답변")
    patch = dict(msg.graph_patch or {})
    cp = patch.get("checkpoint")
    if not cp:
        raise AppError(409, "이 답변은 되돌릴 수 없어요.", "흐름을 바꾼 답변만 되돌릴 수 있어요.")
    if patch.get("reverted"):
        raise AppError(409, "이미 되돌린 답변이에요.", "캔버스의 되돌리기나 버전 기능을 쓰세요.")
    sess = db.get(BuilderSession, session_id)
    app = db.get(App, sess.app_id) if sess else None
    if app is None:
        raise not_found("앱")
    changed_after = graph_hash(app.draft_graph) != cp.get("after_hash")
    if changed_after and not force:
        raise AppError(
            409,
            "이 답변 뒤에 흐름이 더 바뀌었어요. 되돌리면 그 변경도 함께 사라져요.",
            "그래도 되돌리려면 한 번 더 확인해 주세요.",
        )
    app.draft_graph = copy.deepcopy(cp["graph"])
    patch["reverted"] = True
    msg.graph_patch = patch  # 새 딕셔너리로 바꿔야 변경으로 저장된다
    db.commit()
    db.refresh(app)
    return {
        "graph": app.draft_graph,
        "draft_rev": app.draft_rev,
        "had_later_changes": changed_after,
    }
