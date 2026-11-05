"""Shopify 커넥터(주문 목록 읽기, 읽기 전용). 플랫폼이 넘겨준 net으로만 *.myshopify.com에 접속한다."""

import re
from typing import Any
from urllib.parse import urlencode

from nodes.spec import NodeError

API_VERSION = "2024-10"
SHOP_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,60}$")
STATUSES = ("any", "open", "closed", "cancelled")


def _shop(secrets: dict[str, Any]) -> str:
    raw = str(secrets.get("shop") or "").strip().lower()
    raw = raw.replace("https://", "").replace("http://", "").split("/")[0]
    if raw.endswith(".myshopify.com"):
        raw = raw[: -len(".myshopify.com")]
    if not SHOP_RE.match(raw):
        raise NodeError("Shopify 상점 주소 형식이 맞지 않아요. 예: my-shop (my-shop.myshopify.com의 앞부분)")
    return f"https://{raw}.myshopify.com/admin/api/{API_VERSION}"


def _headers(secrets: dict[str, Any]) -> dict[str, str]:
    token = str(secrets.get("access_token") or "").strip()
    if not token:
        raise NodeError("Shopify 액세스 토큰이 비어 있어요. 연결 정보에 토큰(shpat_…)을 넣어 주세요.")
    return {"X-Shopify-Access-Token": token}


def _check(res: dict[str, Any], what: str) -> dict[str, Any]:
    status = int(res.get("status", 0))
    body = res.get("body")
    if status in (401, 403):
        raise NodeError("Shopify 인증에 실패했어요. 토큰과 'read_orders' 권한을 확인하세요.")
    if status == 404:
        raise NodeError("Shopify 상점을 찾지 못했어요(404). 상점 주소를 확인하세요.")
    if status == 429:
        raise NodeError("Shopify 요청이 너무 많아요. 잠시 후 다시 시도하세요.", retryable=True)
    if status >= 400:
        raise NodeError(f"Shopify에서 {what}하지 못했어요({status}). 설정 값을 확인하세요.")
    return body if isinstance(body, dict) else {}


def list_orders(params: dict[str, Any], secrets: dict[str, Any], net: Any) -> dict[str, Any]:
    base = _shop(secrets)
    status = str(params.get("status") or "any").lower()
    if status not in STATUSES:
        raise NodeError("주문 상태는 any·open·closed·cancelled 중에서 고르세요.")
    limit = max(1, min(int(params.get("limit") or 10), 50))
    query = {"status": status, "limit": limit}
    if params.get("created_at_min"):
        query["created_at_min"] = str(params["created_at_min"])
    res = net.http("GET", f"{base}/orders.json?{urlencode(query)}", headers=_headers(secrets))
    data = _check(res, "주문을 읽")
    rows = [
        {
            "id": str(o.get("id", "")),
            "name": str(o.get("name", "")),
            "email": str(o.get("email", "")),
            "total_price": str(o.get("total_price", "")),
            "currency": str(o.get("currency", "")),
            "financial_status": str(o.get("financial_status", "")),
            "created_at": str(o.get("created_at", "")),
        }
        for o in data.get("orders") or []
        if isinstance(o, dict)
    ][:limit]
    text = "\n".join(
        f"{r['name']} {r['total_price']} {r['currency']} ({r['financial_status']})" for r in rows
    )
    return {"count": len(rows), "orders": rows, "text": text}


def test(secrets: dict[str, Any], net: Any) -> dict[str, Any]:
    data = _check(net.http("GET", _shop(secrets) + "/shop.json", headers=_headers(secrets)), "연결을 확인")
    shop = data.get("shop") if isinstance(data.get("shop"), dict) else {}
    return {"message": "Shopify에 연결됐어요: " + str(shop.get("name") or "상점")}
