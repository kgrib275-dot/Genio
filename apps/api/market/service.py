"""마켓: 기본 제공 아이템 동기화, 설치(mock 결제 → 검증 → 등록), 제거, 설치분 조회."""

import logging
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.config import get_settings
from api.core.audit import audit
from api.core.errors import AppError, not_found
from api.market.bundle import BundleError, load_module, read_json, read_manifest, validate_bundle
from api.models import ConnectorDefinition, Installation, MarketItem, Purchase
from nodes import NodeSpec, registry

log = logging.getLogger("genio.market")


def items_dir() -> Path:
    p = Path(get_settings().market_items_dir)
    if not p.is_absolute():
        # 저장소 루트 기준
        root = Path(__file__).resolve().parents[3]
        p = root / p
    return p


def sync_catalog(db: Session) -> int:
    """market-items/ 폴더의 기본 제공 아이템을 market_items 테이블에 반영한다."""
    base = items_dir()
    if not base.exists():
        return 0
    count = 0
    for path in sorted(p for p in base.iterdir() if p.is_dir()):
        try:
            manifest = read_manifest(path)
            validate_bundle(path, manifest)
        except BundleError as exc:
            log.warning("마켓 아이템 건너뜀(%s): %s", path.name, exc)
            continue
        readme = path / "README.md"
        item = db.scalar(select(MarketItem).where(MarketItem.key == manifest["key"]))
        if item is None:
            item = MarketItem(key=manifest["key"], installs=0)
            db.add(item)
        item.type = manifest["type"]
        item.name = manifest["name"]
        item.summary = manifest.get("summary", "")
        item.description_md = readme.read_text(encoding="utf-8") if readme.exists() else ""
        item.version = manifest["version"]
        item.publisher = manifest.get("publisher", "platform")
        item.price = int(manifest.get("price", 0))
        item.manifest = manifest
        item.tags = list(manifest.get("tags", []))
        item.bundle_path = str(path)
        count += 1
    db.commit()
    return count


def bundle_path(item: MarketItem) -> Path:
    if item.bundle_path and Path(item.bundle_path).exists():
        return Path(item.bundle_path)
    p = items_dir() / item.key
    if p.exists():
        return p
    raise AppError(
        500, "확장 파일을 찾지 못했어요.", "관리자에게 마켓 설정을 확인해 달라고 알려 주세요."
    )


def installed_items(
    db: Session, workspace_id: str, item_type: str | None = None
) -> list[MarketItem]:
    q = (
        select(MarketItem)
        .join(Installation, Installation.item_id == MarketItem.id)
        .where(Installation.workspace_id == workspace_id, Installation.status == "installed")
    )
    if item_type:
        q = q.where(MarketItem.type == item_type)
    return list(db.scalars(q))


def installed_keys(db: Session, workspace_id: str) -> set[str]:
    return {i.key for i in installed_items(db, workspace_id)}


def _load_node_spec(item: MarketItem) -> NodeSpec:
    module = load_module(bundle_path(item) / "node.py", item.key)
    spec = getattr(module, "SPEC", None)
    if not isinstance(spec, NodeSpec):
        raise BundleError("node.py에 SPEC(NodeSpec)이 없어요.")
    return spec


def ensure_market_nodes(db: Session) -> None:
    """설치된 마켓 노드를 이 프로세스의 노드 레지스트리에 등록한다(API·워커 공통)."""
    items = db.scalars(
        select(MarketItem)
        .join(Installation, Installation.item_id == MarketItem.id)
        .where(MarketItem.type == "node", Installation.status == "installed")
        .distinct()
    )
    for item in items:
        try:
            spec = _load_node_spec(item)
            if registry.get(spec.type) is None:
                registry.register(spec)
        except (BundleError, AppError, OSError) as exc:
            log.warning("마켓 노드 로딩 실패(%s): %s", item.key, exc)


def market_node_types(db: Session, workspace_id: str) -> set[str]:
    types: set[str] = set()
    for item in installed_items(db, workspace_id, "node"):
        node_type = item.manifest.get("node_type")
        if isinstance(node_type, str):
            types.add(node_type)
    return types


def install(db: Session, workspace_id: str, item_key: str, user_id: str) -> Installation:
    item = db.scalar(select(MarketItem).where(MarketItem.key == item_key))
    if item is None:
        raise not_found("마켓 아이템")
    existing = db.scalar(
        select(Installation).where(
            Installation.workspace_id == workspace_id, Installation.item_id == item.id
        )
    )
    if existing is not None and existing.status == "installed":
        return existing
    path = bundle_path(item)
    try:
        validate_bundle(path, item.manifest)
        if item.type == "node":
            spec = _load_node_spec(item)
            registry.register(spec, replace=True)
    except BundleError as exc:
        raise AppError(
            422, f"확장을 설치하지 못했어요: {exc}", "다른 버전을 고르거나 게시자에게 문의하세요."
        ) from exc
    if item.price > 0:
        db.add(
            Purchase(
                workspace_id=workspace_id, item_id=item.id, amount=item.price, status="mock_paid"
            )
        )
    if item.type == "connector":
        definition = db.scalar(
            select(ConnectorDefinition).where(
                ConnectorDefinition.key == item.key, ConnectorDefinition.version == item.version
            )
        )
        if definition is None:
            db.add(
                ConnectorDefinition(
                    key=item.key,
                    name=item.name,
                    version=item.version,
                    source="market",
                    manifest=item.manifest,
                )
            )
        else:
            definition.manifest = item.manifest
    if existing is not None:
        existing.status = "installed"
        existing.version = item.version
        existing.installed_by = user_id
        inst = existing
    else:
        inst = Installation(
            workspace_id=workspace_id, item_id=item.id, version=item.version, installed_by=user_id
        )
        db.add(inst)
    item.installs = (item.installs or 0) + 1
    audit(
        db,
        workspace_id=workspace_id,
        user_id=user_id,
        action="market.install",
        target_type="market_item",
        target_id=item.key,
        meta={"version": item.version, "price": item.price},
    )
    db.commit()
    return inst


def uninstall(db: Session, workspace_id: str, installation_id: str, user_id: str) -> None:
    inst = db.get(Installation, installation_id)
    if inst is None or inst.workspace_id != workspace_id:
        raise not_found("설치 항목")
    inst.status = "disabled"
    item = db.get(MarketItem, inst.item_id)
    audit(
        db,
        workspace_id=workspace_id,
        user_id=user_id,
        action="market.uninstall",
        target_type="market_item",
        target_id=item.key if item else inst.item_id,
    )
    db.commit()


def templates(db: Session, workspace_id: str) -> list[dict[str, Any]]:
    out = []
    for item in installed_items(db, workspace_id, "template"):
        graph = read_json(bundle_path(item) / "template.json")
        out.append({"key": item.key, "name": item.name, "summary": item.summary, "graph": graph})
    return out


def prompt_packs(db: Session, workspace_id: str) -> list[dict[str, Any]]:
    out = []
    for item in installed_items(db, workspace_id, "prompt_pack"):
        data = read_json(bundle_path(item) / "prompts.json")
        out.append({"key": item.key, "name": item.name, "prompts": data.get("prompts", [])})
    return out


def connector_manifest(db: Session, workspace_id: str, key: str) -> dict[str, Any] | None:
    for item in installed_items(db, workspace_id, "connector"):
        if item.key == key:
            return item.manifest
    return None
