"""실행이 만든 파일(v0.9): 이미지 만들기·파일 만들기 단계의 결과를 모으고 내려받기 링크를 붙인다.

어떤 파일이 '이 실행의 결과'인지는 단계 출력에서 찾는다: `files`(목록)·`file`(하나)에 들어 있는
{id, filename, mime, size}만 인정하고, 그 파일이 같은 앱·워크스페이스의 것일 때만 돌려준다.
(입력으로 올린 파일은 id 글자만 들어 있어 여기에 섞이지 않는다.)
"""

from typing import Any
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.models import Run, RunStep, StoredFile
from api.services import file_links

IMAGE_MIMES = ("image/png", "image/jpeg", "image/webp", "image/gif")
MAX_FILES_PER_RUN = 40


PRODUCER_TYPES = ("image_generate", "file_export")


def graph_makes_files(graph: dict[str, Any] | None) -> bool:
    """흐름에 파일을 만드는 단계(이미지 만들기·파일 만들기)가 켜진 채로 있는지.

    지난 대화처럼 실행을 많이 훑는 곳에서, 파일을 안 만드는 앱은 단계 조회를 건너뛰게 한다.
    """
    for n in (graph or {}).get("nodes", []):
        if isinstance(n, dict) and n.get("type") in PRODUCER_TYPES and not n.get("disabled"):
            return True
    return False


def file_kind(mime: str) -> str:
    return "image" if mime in IMAGE_MIMES else "file"


def file_item(f: StoredFile) -> dict[str, Any]:
    return {
        "id": f.id,
        "filename": f.filename,
        "mime": f.mime,
        "size": f.size,
        "kind": file_kind(f.mime),
    }


def _candidates(output: Any) -> list[str]:
    ids: list[str] = []
    if not isinstance(output, dict):
        return ids
    files = output.get("files")
    if isinstance(files, list):
        for it in files:
            if isinstance(it, dict) and isinstance(it.get("id"), str):
                ids.append(it["id"])
    one = output.get("file")
    if isinstance(one, dict) and isinstance(one.get("id"), str):
        ids.append(one["id"])
    return ids


def files_of_run(db: Session, run: Run, workspace_id: str) -> list[dict[str, Any]]:
    """이 실행의 단계들이 만든 파일(순서대로, 중복 없이)."""
    steps = db.scalars(select(RunStep).where(RunStep.run_id == run.id).order_by(RunStep.seq))
    order: list[tuple[str, str]] = []  # (file id, 만든 단계)
    seen: set[str] = set()
    for s in steps:
        if s.status != "succeeded":
            continue
        for fid in _candidates(s.output):
            if fid not in seen:
                seen.add(fid)
                order.append((fid, s.node_id))
        if len(order) >= MAX_FILES_PER_RUN:
            break
    if not order:
        return []
    rows = {
        f.id: f
        for f in db.scalars(select(StoredFile).where(StoredFile.id.in_([i for i, _ in order])))
        if f.workspace_id == workspace_id and f.app_id == run.app_id
    }
    out = []
    for fid, node_id in order:
        f = rows.get(fid)
        if f is not None:
            out.append({**file_item(f), "node_id": node_id})
    return out


def with_public_links(
    items: list[dict[str, Any]], app_id: str, run_id: str
) -> list[dict[str, Any]]:
    """공개 화면에 보낼 목록: 서명(sig)·만료(exp)와 실행 번호를 붙인다(내부 단계 이름은 뺀다)."""
    out = []
    for it in items:
        link = file_links.sign(app_id, str(it["id"]))
        out.append(
            {
                "id": it["id"],
                "filename": it["filename"],
                "mime": it["mime"],
                "size": it["size"],
                "kind": it["kind"],
                "run_id": run_id,
                **link,
            }
        )
    return out


def public_url(origin: str, token: str, item: dict[str, Any]) -> str:
    """서명된 공개 내려받기 주소(일괄 실행 결과 표처럼 화면 밖에서 쓰는 링크)."""
    return (
        f"{origin}/api/v1/public/apps/{token}/files/{item['id']}"
        f"?sig={item['sig']}&exp={item['exp']}"
    )


def content_disposition(filename: str, *, inline: bool) -> str:
    """한글 파일 이름도 깨지지 않게(RFC 5987). 따옴표·줄바꿈은 지운다."""
    clean = "".join(ch for ch in filename if ch not in '"\\\r\n').strip() or "file"
    ascii_name = clean.encode("ascii", "ignore").decode() or "file"
    kind = "inline" if inline else "attachment"
    return f"{kind}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(clean)}"
