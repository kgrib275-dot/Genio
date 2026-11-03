"""데이터 표 관리 API(ADR 0008). 표 보기는 모든 역할, 표 구조는 제작자 이상, 줄 쓰기는 운영자 이상."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import or_, select

from api.core.audit import audit
from api.core.errors import AppError, not_found
from api.deps import ANY_MEMBER, EDIT_APPS, VIEW_RUNS, Ctx, require_role
from api.models import DataRow, DataTable, Project
from api.services import data_tables as svc
from api.services.projects import can_access, hidden_project_ids

router = APIRouter(tags=["data-tables"])
WsMembers = Annotated[Ctx, Depends(require_role(ANY_MEMBER))]
WsBuilders = Annotated[Ctx, Depends(require_role(EDIT_APPS))]
TableViewers = Annotated[Ctx, Depends(require_role(ANY_MEMBER, via="data_table"))]
TableBuilders = Annotated[Ctx, Depends(require_role(EDIT_APPS, via="data_table"))]
TableWriters = Annotated[Ctx, Depends(require_role(VIEW_RUNS, via="data_table"))]
RowWriters = Annotated[Ctx, Depends(require_role(VIEW_RUNS, via="data_row"))]


def _table(ctx: Ctx, table_id: str) -> DataTable:
    t = ctx.db.get(DataTable, table_id)
    if t is None:
        raise not_found("데이터 표")
    return t


def _check_project(ctx: Ctx, project_id: str | None) -> None:
    if not project_id:
        return
    proj = ctx.db.get(Project, project_id)
    if (
        proj is None
        or proj.workspace_id != ctx.workspace_id
        or not can_access(ctx.db, proj, ctx.user.id, ctx.role)
    ):
        raise not_found("프로젝트")


def _dup_name(ctx: Ctx, name: str, exclude: str | None = None) -> None:
    q = select(DataTable.id).where(
        DataTable.workspace_id == ctx.workspace_id, DataTable.name == name
    )
    if exclude:
        q = q.where(DataTable.id != exclude)
    if ctx.db.scalar(q) is not None:
        raise AppError(409, f"'{name}' 이름의 데이터 표가 이미 있어요.", "다른 이름을 지어 주세요.")


@router.get("/workspaces/{ws}/data-tables")
def list_tables(ws: str, ctx: WsMembers) -> list[dict[str, Any]]:
    q = select(DataTable).where(DataTable.workspace_id == ws).order_by(DataTable.name)
    hidden = hidden_project_ids(ctx.db, ws, ctx.user.id, ctx.role)
    if hidden:
        q = q.where(or_(DataTable.project_id.is_(None), DataTable.project_id.not_in(hidden)))
    tables = list(ctx.db.scalars(q))
    counts = svc.row_counts(ctx.db, [t.id for t in tables])
    return [svc.table_dict(t, counts.get(t.id, 0)) for t in tables]


class TableIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=2000)
    columns: list[dict[str, Any]] = Field(default_factory=list)
    project_id: str | None = None


@router.post("/workspaces/{ws}/data-tables", status_code=201)
def create_table(ws: str, body: TableIn, ctx: WsBuilders) -> dict[str, Any]:
    name = body.name.strip()
    if not name:
        raise AppError(422, "표 이름이 비어 있어요.", "알아보기 쉬운 이름을 지어 주세요.")
    _dup_name(ctx, name)
    _check_project(ctx, body.project_id)
    t = DataTable(
        workspace_id=ws,
        project_id=body.project_id or None,
        name=name,
        description=body.description,
        columns=svc.clean_columns(body.columns),
        created_by=ctx.user.id,
    )
    ctx.db.add(t)
    ctx.db.flush()
    audit(
        ctx.db,
        workspace_id=ws,
        user_id=ctx.user.id,
        action="data_table.create",
        target_type="data_table",
        target_id=t.id,
        meta={"name": name},
    )
    ctx.db.commit()
    return svc.table_dict(t, 0)


@router.get("/data-tables/{table_id}")
def get_table(table_id: str, ctx: TableViewers) -> dict[str, Any]:
    t = _table(ctx, table_id)
    return svc.table_dict(t, svc.row_count(ctx.db, t.id))


class TablePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=2000)
    columns: list[dict[str, Any]] | None = None
    project_id: str | None = None


@router.patch("/data-tables/{table_id}")
def update_table(table_id: str, body: TablePatch, ctx: TableBuilders) -> dict[str, Any]:
    t = _table(ctx, table_id)
    sent = body.model_fields_set
    if body.name is not None:
        name = body.name.strip()
        _dup_name(ctx, name, exclude=t.id)
        t.name = name
    if body.description is not None:
        t.description = body.description
    if body.columns is not None:
        t.columns = svc.clean_columns(body.columns)
    if "project_id" in sent:
        _check_project(ctx, body.project_id)
        t.project_id = body.project_id or None
    audit(
        ctx.db,
        workspace_id=t.workspace_id,
        user_id=ctx.user.id,
        action="data_table.update",
        target_type="data_table",
        target_id=t.id,
        meta={"name": t.name},
    )
    ctx.db.commit()
    return svc.table_dict(t, svc.row_count(ctx.db, t.id))


@router.delete("/data-tables/{table_id}", status_code=204)
def delete_table(table_id: str, ctx: TableBuilders) -> Response:
    t = _table(ctx, table_id)
    audit(
        ctx.db,
        workspace_id=t.workspace_id,
        user_id=ctx.user.id,
        action="data_table.delete",
        target_type="data_table",
        target_id=t.id,
        meta={"name": t.name},
    )
    ctx.db.delete(t)
    ctx.db.commit()
    return Response(status_code=204)


@router.get("/data-tables/{table_id}/rows")
def list_rows(
    table_id: str,
    ctx: TableViewers,
    limit: int = Query(default=50, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    q: str | None = Query(default=None, max_length=200),
) -> dict[str, Any]:
    _table(ctx, table_id)
    total, rows = svc.search_rows(ctx.db, table_id, q, limit, offset)
    return {"total": total, "rows": [svc.row_dict(r) for r in rows]}


class RowIn(BaseModel):
    row_key: str | None = Field(default=None, max_length=200)
    data: dict[str, Any] = Field(default_factory=dict)


@router.post("/data-tables/{table_id}/rows", status_code=201)
def add_row(table_id: str, body: RowIn, ctx: TableWriters) -> dict[str, Any]:
    t = _table(ctx, table_id)
    row = svc.insert_row(ctx.db, t, body.row_key, body.data)
    ctx.db.commit()
    return svc.row_dict(row)


class RowPatch(BaseModel):
    row_key: str | None = Field(default=None, max_length=200)
    data: dict[str, Any] | None = None


@router.patch("/data-rows/{row_id}")
def update_row(row_id: str, body: RowPatch, ctx: RowWriters) -> dict[str, Any]:
    row = ctx.db.get(DataRow, row_id)
    if row is None:
        raise not_found("데이터 줄")
    table = _table(ctx, row.table_id)
    if "row_key" in body.model_fields_set:
        key = svc.clean_key(body.row_key)
        if key is not None and key != row.row_key:
            other = svc.find_by_key(ctx.db, table.id, key)
            if other is not None and other.id != row.id:
                raise AppError(
                    409, f"'{key[:40]}' 키를 가진 줄이 이미 있어요.", "다른 키를 쓰세요."
                )
        row.row_key = key
    if body.data is not None:
        row.data = svc.clean_data(table, body.data)
    ctx.db.commit()
    return svc.row_dict(row)


@router.delete("/data-rows/{row_id}", status_code=204)
def delete_row(row_id: str, ctx: RowWriters) -> Response:
    row = ctx.db.get(DataRow, row_id)
    if row is None:
        raise not_found("데이터 줄")
    ctx.db.delete(row)
    ctx.db.commit()
    return Response(status_code=204)


@router.post("/data-tables/{table_id}/import")
async def import_rows(
    table_id: str, ctx: TableBuilders, file: Annotated[UploadFile, File()]
) -> dict[str, Any]:
    t = _table(ctx, table_id)
    content = await file.read(svc.MAX_IMPORT_BYTES + 1)
    result = svc.import_csv(ctx.db, t, content)
    audit(
        ctx.db,
        workspace_id=t.workspace_id,
        user_id=ctx.user.id,
        action="data_table.import",
        target_type="data_table",
        target_id=t.id,
        meta={"name": t.name, "rows": result["imported"]},
    )
    ctx.db.commit()
    return result


@router.get("/data-tables/{table_id}/export.csv")
def export_rows(table_id: str, ctx: TableViewers) -> Response:
    t = _table(ctx, table_id)
    text = svc.export_csv(ctx.db, t)
    from urllib.parse import quote

    return Response(
        content=text.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(t.name)}.csv"},
    )
