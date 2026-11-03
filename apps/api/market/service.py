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
    """설치된 마켓 단계를 이 프로세스의 단계 레지스트리에 등록한다(API·워커 공통)."""
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
            log.warning("마켓 단계 로딩 실패(%s): %s", item.key, exc)


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


def update_installation(
    db: Session, workspace_id: str, installation_id: str, user_id: str
) -> Installation:
    """설치한 아이템을 마켓의 최신 버전으로 바꾼다(커넥터 정의도 새 버전으로)."""
    inst = db.get(Installation, installation_id)
    if inst is None or inst.workspace_id != workspace_id or inst.status != "installed":
        raise not_found("설치 항목")
    item = db.get(MarketItem, inst.item_id)
    if item is None:
        raise not_found("마켓 아이템")
    if inst.version == item.version:
        raise AppError(409, "이미 최신 버전이에요.", "새 버전이 나오면 업데이트 버튼이 보여요.")
    path = bundle_path(item)
    try:
        validate_bundle(path, item.manifest)
        if item.type == "node":
            registry.register(_load_node_spec(item), replace=True)
    except BundleError as exc:
        raise AppError(
            422, f"업데이트하지 못했어요: {exc}", "지금 버전을 계속 쓰고 게시자에게 문의하세요."
        ) from exc
    if item.type == "connector":
        definition = db.scalar(
            select(ConnectorDefinition).where(
                ConnectorDefinition.key == item.key, ConnectorDefinition.version == item.version
            )
        )
        if definition is None:
            definition = ConnectorDefinition(
                key=item.key,
                name=item.name,
                version=item.version,
                source="market",
                manifest=item.manifest,
            )
            db.add(definition)
            db.flush()
        # 기존 연결 정보는 새 정의로 옮긴다(값은 그대로)
        from api.models import ConnectorCredential

        old_ids = list(
            db.scalars(
                select(ConnectorDefinition.id).where(
                    ConnectorDefinition.key == item.key, ConnectorDefinition.id != definition.id
                )
            )
        )
        if old_ids:
            for cred in db.scalars(
                select(ConnectorCredential).where(
                    ConnectorCredential.workspace_id == workspace_id,
                    ConnectorCredential.definition_id.in_(old_ids),
                )
            ):
                cred.definition_id = definition.id
    before = inst.version
    inst.version = item.version
    audit(
        db,
        workspace_id=workspace_id,
        user_id=user_id,
        action="market.update",
        target_type="market_item",
        target_id=item.key,
        meta={"from": before, "to": item.version},
    )
    db.commit()
    return inst


def category_of(item: MarketItem) -> str:
    """마켓 분류(manifest.category가 없으면 종류로 정한다)."""
    cat = (item.manifest or {}).get("category")
    if isinstance(cat, str) and cat.strip():
        return cat.strip()
    return {
        "connector": "연결",
        "template": "템플릿",
        "node": "단계",
        "prompt_pack": "프롬프트",
    }.get(item.type, "기타")


STEP_NAMES = {
    "input": "입력 받기",
    "output": "결과 내기",
    "llm": "AI에게 묻기",
    "condition": "조건으로 나누기",
    "http": "외부 주소 부르기",
    "code": "코드 실행",
    "knowledge_search": "지식 찾기",
    "connector": "서비스 연결",
    "approval": "승인 받기",
    "question_classifier": "질문 분류",
    "parameter_extractor": "값 뽑기",
    "template": "글 만들기",
    "document_extractor": "문서 읽기",
    "data_table": "데이터 표",
    "agent": "에이전트",
}


def template_preview(item: MarketItem) -> dict[str, Any]:
    """템플릿 미리 보기: 단계 목록·앱 종류·채울 빈칸."""
    try:
        graph = read_json(bundle_path(item) / "template.json")
    except (OSError, ValueError, AppError):
        return {"steps": [], "app_type": None, "blanks": []}
    steps = []
    for n in graph.get("nodes", []) if isinstance(graph, dict) else []:
        data = n.get("data") or {}
        extra = ""
        if n.get("type") == "connector":
            extra = str(data.get("connector") or "")
        steps.append(
            {
                "id": n.get("id"),
                "type": n.get("type"),
                "label": data.get("label") or STEP_NAMES.get(str(n.get("type")), n.get("type")),
                "kind": STEP_NAMES.get(str(n.get("type")), str(n.get("type"))),
                "service": extra or None,
            }
        )
    m = item.manifest or {}
    return {
        "steps": steps,
        "app_type": m.get("app_type") or "workflow",
        "blanks": m.get("blanks") or [],
        "requires": (m.get("requires") or {}).get("items") or [],
    }
