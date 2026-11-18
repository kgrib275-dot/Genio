"""스킬: 지시문과 참고 내용을 묶은 '업무 요령'(SKILL.md 형식, 여러 AI 서비스가 쓰는 열린 표준).

- 앞머리(--- 로 감싼 name·description)와 본문(마크다운)으로 이뤄진다. .md 글이나 SKILL.md가 든 .zip을 가져온다.
- 에이전트 단계에 스킬을 붙이면 이름과 설명만 늘 보이고, 에이전트가 필요하다고 판단할 때 본문을 읽는다
  (그래서 스킬이 많아도 긴 글이 매번 AI에 들어가지 않는다).
- 워크스페이스 설정(settings.skills)에 저장한다(마이그레이션 없음). 한 워크스페이스에 최대 50개, 본문 20KB.
"""

import io
import re
import uuid
import zipfile
from typing import Any

from sqlalchemy.orm import Session

from api.core.errors import AppError, not_found
from api.models import Workspace
from api.services.zipguard import ZipBombError, check_zip

MAX_SKILLS = 50
MAX_BODY = 20_000
MAX_ZIP_BYTES = 2 * 1024 * 1024
NAME_RE = re.compile(r"[^0-9A-Za-z가-힣_\- ]+")


def _unquote(v: str) -> str:
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1]
    return v


def parse_skill_md(text: str) -> dict[str, str]:
    """SKILL.md 글에서 name·description·body를 뽑는다. 앞머리가 없으면 첫 줄을 이름으로 본다."""
    text = text.replace("\r\n", "\n").lstrip("﻿")
    meta: dict[str, str] = {}
    body = text
    m = re.match(r"^---\n(.*?)\n---\n?(.*)$", text, re.DOTALL)
    if m:
        lines = m.group(1).split("\n")
        body = m.group(2)
        i = 0
        while i < len(lines):
            kv = re.match(r"^([A-Za-z_][\w-]*)\s*:\s*(.*)$", lines[i])
            i += 1
            if not kv:
                continue
            key, val = kv.group(1).lower(), kv.group(2)
            if val.strip() in (">", "|", ">-", "|-"):
                block: list[str] = []
                while i < len(lines) and (lines[i].startswith(" ") or not lines[i].strip()):
                    block.append(lines[i].strip())
                    i += 1
                val = (" " if val.strip().startswith(">") else "\n").join(x for x in block if x)
            meta[key] = _unquote(val)
    name = meta.get("name", "").strip()
    if not name:
        first = next((ln.strip("# ").strip() for ln in body.split("\n") if ln.strip()), "")
        name = first[:60]
    return {
        "name": name,
        "description": meta.get("description", "").strip(),
        "body": body.strip(),
    }


def skill_from_zip(content: bytes) -> dict[str, str]:
    if len(content) > MAX_ZIP_BYTES:
        raise AppError(
            413, "스킬 압축 파일이 너무 커요(최대 2MB).", "SKILL.md만 담아 다시 올려 주세요."
        )
    try:
        check_zip(content)
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            names = [n for n in z.namelist() if n.rsplit("/", 1)[-1].lower() == "skill.md"]
            if not names:
                raise AppError(
                    422,
                    "압축 파일 안에 SKILL.md가 없어요.",
                    "SKILL.md가 든 압축 파일을 올려 주세요.",
                )
            names.sort(key=lambda n: n.count("/"))
            raw = z.read(names[0])
    except (zipfile.BadZipFile, ZipBombError):
        raise AppError(
            422, "압축 파일을 읽을 수 없어요.", "올바른 .zip(또는 .skill) 파일인지 확인하세요."
        ) from None
    return parse_skill_md(raw.decode("utf-8", errors="replace"))


def clean(raw: dict[str, Any]) -> dict[str, str]:
    name = NAME_RE.sub("", str(raw.get("name") or "")).strip()[:60]
    desc = str(raw.get("description") or "").strip()[:500]
    body = str(raw.get("body") or "").strip()
    if not name:
        raise AppError(422, "스킬 이름이 비어 있어요.", "SKILL.md 앞머리의 name을 적어 주세요.")
    if not desc:
        raise AppError(
            422,
            "스킬 설명이 비어 있어요.",
            "언제 쓰는 스킬인지 description에 한두 문장으로 적어 주세요(에이전트가 이걸 보고 고르거든요).",
        )
    if not body:
        raise AppError(422, "스킬 본문이 비어 있어요.", "지시 내용을 본문에 적어 주세요.")
    if len(body) > MAX_BODY:
        raise AppError(
            413,
            f"스킬 본문이 너무 길어요(최대 {MAX_BODY:,}자).",
            "나눠서 여러 스킬로 만들거나 핵심만 남겨 주세요.",
        )
    return {"name": name, "description": desc, "body": body}


def _all(ws: Workspace) -> list[dict[str, Any]]:
    raw = (ws.settings or {}).get("skills")
    return [dict(s) for s in raw] if isinstance(raw, list) else []


def list_skills(ws: Workspace, with_body: bool = False) -> list[dict[str, Any]]:
    out = []
    for s in _all(ws):
        item = {"id": s["id"], "name": s["name"], "description": s["description"]}
        item["size"] = len(str(s.get("body") or ""))
        if with_body:
            item["body"] = s.get("body", "")
        out.append(item)
    return sorted(out, key=lambda x: str(x["name"]).lower())


def get_skill(ws: Workspace, skill_id: str) -> dict[str, Any]:
    for s in _all(ws):
        if s["id"] == skill_id:
            return s
    raise not_found("스킬")


def save(
    db: Session, ws: Workspace, data: dict[str, Any], skill_id: str | None = None
) -> dict[str, Any]:
    fields = clean(data)
    items = _all(ws)
    if skill_id is None:
        if len(items) >= MAX_SKILLS:
            raise AppError(
                409,
                f"스킬은 워크스페이스에 {MAX_SKILLS}개까지 저장할 수 있어요.",
                "안 쓰는 스킬을 지운 뒤 다시 저장하세요.",
            )
        if any(s["name"].lower() == fields["name"].lower() for s in items):
            raise AppError(
                409, "같은 이름의 스킬이 이미 있어요.", "이름을 바꾸거나 기존 스킬을 고치세요."
            )
        item = {"id": uuid.uuid4().hex[:12], **fields}
        items.append(item)
    else:
        found = next((s for s in items if s["id"] == skill_id), None)
        if found is None:
            raise not_found("스킬")
        item = found
        if any(s["id"] != skill_id and s["name"].lower() == fields["name"].lower() for s in items):
            raise AppError(
                409, "같은 이름의 스킬이 이미 있어요.", "이름을 바꾸거나 기존 스킬을 고치세요."
            )
        item.update(fields)
    ws.settings = {**(ws.settings or {}), "skills": items}
    db.commit()
    return dict(item)


def delete(db: Session, ws: Workspace, skill_id: str) -> None:
    items = _all(ws)
    kept = [s for s in items if s["id"] != skill_id]
    if len(kept) == len(items):
        raise not_found("스킬")
    ws.settings = {**(ws.settings or {}), "skills": kept}
    db.commit()


def catalog_for(db: Session, workspace_id: str, ids: list[str]) -> list[dict[str, Any]]:
    """에이전트에 붙은 스킬(이름·설명·본문). 지워진 id는 건너뛴다."""
    ws = db.get(Workspace, workspace_id)
    if ws is None:
        return []
    by_id = {s["id"]: s for s in _all(ws)}
    return [by_id[i] for i in ids if i in by_id]
