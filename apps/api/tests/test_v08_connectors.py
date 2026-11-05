"""v0.8 마켓 확대: 새 커넥터 12개의 요청 형식(가짜 네트워크), 서명, 도메인 선언, 새 템플릿 3개."""

import base64
import hashlib
import hmac
import json
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from api.connectors.runtime import ConnectorNet
from api.engine import safe_http
from api.engine.validator import ValidationEnv, validate_graph
from api.market.bundle import allowed_domains, load_module, read_manifest, validate_bundle
from api.market.service import items_dir
from api.tests.conftest import Team, install
from api.tests.test_v05_engine import make_app, start
from nodes import NodeError, registry

CONNECTORS = [
    "twilio",
    "sendgrid",
    "mailgun",
    "google_chat",
    "zendesk",
    "freshdesk",
    "shopify",
    "salesforce",
    "clickup",
    "monday",
    "solapi",
    "naver_sens",
]
CREDENTIAL_ONLY = ["mcp_server", "api_tool_set"]
TEMPLATES = ["tpl_inquiry_zendesk_slack", "tpl_order_sms_notify", "tpl_shopify_orders_mail"]


class FakeNet:
    """요청을 기록하고 정해 둔 답을 돌려준다. 서명 도우미는 진짜 계산을 쓰되 시각·무작위는 고정한다."""

    def __init__(self, *responses: dict[str, Any]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def http(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json: Any = None,
        form: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        self.calls.append(
            {"method": method, "url": url, "headers": headers or {}, "json": json, "form": form}
        )
        return self.responses.pop(0) if self.responses else {"status": 200, "body": {}}

    def sign_hmac_sha256(self, key: str, message: str, *, encoding: str = "hex") -> str:
        digest = hmac.new(key.encode(), message.encode(), hashlib.sha256).digest()
        return base64.b64encode(digest).decode() if encoding == "base64" else digest.hex()

    def now_ms(self) -> int:
        return 1_700_000_000_000

    def now_iso(self) -> str:
        return "2026-11-05T01:02:03.000Z"

    def random_hex(self, n: int = 16) -> str:
        return "ab" * (n // 2)


def mod(key: str) -> Any:
    return load_module(items_dir() / key / "connector.py", f"t8_{key}")


def ok(body: Any = None, status: int = 200) -> dict[str, Any]:
    return {"status": status, "body": body if body is not None else {}}


def basic(user: str, pw: str) -> str:
    return "Basic " + base64.b64encode(f"{user}:{pw}".encode()).decode()


# ---------------- 번들 검증 ----------------
@pytest.mark.parametrize("key", [*CONNECTORS, *CREDENTIAL_ONLY, *TEMPLATES])
def test_bundle_validates(key: str) -> None:
    p = items_dir() / key
    validate_bundle(p, read_manifest(p))
    assert (p / "README.md").exists()


@pytest.mark.parametrize("key", CONNECTORS)
def test_actions_exist_and_domains_declared(key: str) -> None:
    m = read_manifest(items_dir() / key)
    module = mod(key)
    for a in m["actions"]:
        assert callable(getattr(module, a["key"]))
        assert a["input_schema"]["type"] == "object"
    assert callable(module.test)
    assert allowed_domains(m)  # 접속할 도메인을 꼭 선언한다
    # 비밀 칸은 secret 표시가 있고, 비밀이 아닌 칸(주소·이름)과 구분된다
    secret_keys = [c["key"] for c in m["requires"]["credentials"] if c["secret"]]
    assert secret_keys


def test_catalog_size(client: TestClient, team: Team) -> None:
    items = client.get("/api/v1/market/items", headers=team.h("member")).json()
    keys = {i["key"] for i in items}
    assert len(items) >= 62
    assert {*CONNECTORS, *CREDENTIAL_ONLY, *TEMPLATES} <= keys
    found = client.get("/api/v1/market/items?q=문자", headers=team.h("member")).json()
    assert {"solapi", "naver_sens", "twilio"} <= {i["key"] for i in found}


# ---------------- 요청 형식 ----------------
def assert_hosts_declared(key: str, net: FakeNet) -> None:
    domains = allowed_domains(read_manifest(items_dir() / key))
    for c in net.calls:
        host = (urlparse(c["url"]).hostname or "").lower()
        assert any(host == d or host.endswith("." + d) for d in domains), (key, host)


def test_twilio() -> None:
    net = FakeNet(ok({"sid": "SM1", "status": "queued"}, 201))
    sec = {"account_sid": "ACabc", "auth_token": "tok", "from_number": "+15005550006"}
    out = mod("twilio").send_sms({"to": "+82 10-1234-5678", "body": "안녕"}, sec, net)
    c = net.calls[0]
    assert c["url"] == "https://api.twilio.com/2010-04-01/Accounts/ACabc/Messages.json"
    assert c["headers"]["Authorization"] == basic("ACabc", "tok")
    assert c["form"] == {"To": "+821012345678", "Body": "안녕", "From": "+15005550006"}
    assert out == {"message_sid": "SM1", "status": "queued"}
    assert_hosts_declared("twilio", net)
    net2 = FakeNet(ok({}, 201))
    mod("twilio").send_sms(
        {"to": "+821012345678", "body": "x", "from": "MGabc"}, {**sec, "from_number": ""}, net2
    )
    assert net2.calls[0]["form"]["MessagingServiceSid"] == "MGabc"
    with pytest.raises(NodeError, match="국가번호"):
        mod("twilio").send_sms({"to": "010-1234-5678", "body": "x"}, sec, FakeNet())
    with pytest.raises(NodeError, match="보내는 번호"):
        mod("twilio").send_sms(
            {"to": "+821012345678", "body": "x"}, {**sec, "from_number": ""}, FakeNet()
        )
    with pytest.raises(NodeError, match="인증"):
        mod("twilio").send_sms({"to": "+821012345678", "body": "x"}, sec, FakeNet(ok({}, 401)))
    t = FakeNet(ok({"friendly_name": "내 계정"}))
    assert "내 계정" in mod("twilio").test(sec, t)["message"]
    assert t.calls[0]["url"].endswith("/Accounts/ACabc.json")


def test_sendgrid() -> None:
    net = FakeNet(ok(None, 202))
    sec = {"api_key": "SG.key", "from_email": "noreply@example.com"}
    out = mod("sendgrid").send_mail(
        {"to": "a@x.com; b@y.com", "subject": "안녕", "text": "본문", "html": "<b>본문</b>"},
        sec,
        net,
    )
    c = net.calls[0]
    assert c["url"] == "https://api.sendgrid.com/v3/mail/send" and c["method"] == "POST"
    assert c["headers"]["Authorization"] == "Bearer SG.key"
    body = c["json"]
    assert body["from"] == {"email": "noreply@example.com"}
    assert body["personalizations"][0]["to"] == [{"email": "a@x.com"}, {"email": "b@y.com"}]
    assert [x["type"] for x in body["content"]] == ["text/plain", "text/html"]
    assert out["sent"] is True
    assert_hosts_declared("sendgrid", net)
    with pytest.raises(NodeError, match="받는 사람"):
        mod("sendgrid").send_mail({"to": "nope", "subject": "s", "text": "t"}, sec, FakeNet())
    with pytest.raises(NodeError, match="보내는 사람"):
        mod("sendgrid").send_mail(
            {"to": "a@x.com", "subject": "s", "text": "t"}, {"api_key": "k"}, FakeNet()
        )
    with pytest.raises(NodeError, match="Mail Send"):
        mod("sendgrid").send_mail(
            {"to": "a@x.com", "subject": "s", "text": "t"}, sec, FakeNet(ok({}, 403))
        )
    msg = mod("sendgrid").test(sec, FakeNet(ok({"scopes": ["mail.send"]})))["message"]
    assert "권한 1개" in msg and "확인하세요" not in msg


def test_mailgun() -> None:
    net = FakeNet(ok({"id": "<m1>"}))
    sec = {
        "api_key": "key-1",
        "domain": "mg.example.com",
        "from_email": "알림 <noreply@mg.example.com>",
    }
    out = mod("mailgun").send_mail({"to": "a@x.com", "subject": "제목", "text": "본문"}, sec, net)
    c = net.calls[0]
    assert c["url"] == "https://api.mailgun.net/v3/mg.example.com/messages"
    assert c["headers"]["Authorization"] == basic("api", "key-1")
    assert c["form"] == {
        "from": sec["from_email"],
        "to": "a@x.com",
        "subject": "제목",
        "text": "본문",
    }
    assert out["message_id"] == "<m1>"
    eu = FakeNet(ok({}))
    mod("mailgun").send_mail(
        {"to": "a@x.com", "subject": "s", "text": "t"}, {**sec, "region": "EU"}, eu
    )
    assert eu.calls[0]["url"].startswith("https://api.eu.mailgun.net/v3/")
    assert_hosts_declared("mailgun", net)
    assert_hosts_declared("mailgun", eu)
    with pytest.raises(NodeError, match="도메인"):
        mod("mailgun").test({**sec, "domain": "x"}, FakeNet())
    with pytest.raises(NodeError, match="도메인을 찾지"):
        mod("mailgun").test(sec, FakeNet(ok({}, 404)))


def test_google_chat() -> None:
    url = "https://chat.googleapis.com/v1/spaces/AAA-bbb/messages?key=K&token=T"
    net = FakeNet(ok({"name": "spaces/AAA/messages/1"}))
    out = mod("google_chat").send_message(
        {"text": "안녕", "thread_key": "주문"}, {"webhook_url": url}, net
    )
    c = net.calls[0]
    assert c["url"].startswith(url) and "messageReplyOption=" in c["url"]
    assert c["json"] == {"text": "안녕", "thread": {"threadKey": "주문"}}
    assert out == {"sent": True, "message_name": "spaces/AAA/messages/1"}
    assert_hosts_declared("google_chat", net)
    plain = FakeNet(ok({}))
    mod("google_chat").send_message({"text": "x"}, {"webhook_url": url}, plain)
    assert plain.calls[0]["url"] == url and plain.calls[0]["json"] == {"text": "x"}
    with pytest.raises(NodeError, match="웹훅 주소"):
        mod("google_chat").send_message(
            {"text": "x"}, {"webhook_url": "https://evil.com/x"}, FakeNet()
        )
    with pytest.raises(NodeError, match="유효한지"):
        mod("google_chat").send_message({"text": "x"}, {"webhook_url": url}, FakeNet(ok({}, 404)))
    t = FakeNet()
    assert "형식이 맞아요" in mod("google_chat").test({"webhook_url": url}, t)["message"]
    assert t.calls == []  # 연결 테스트는 메시지를 보내지 않는다


def test_zendesk() -> None:
    sec = {"subdomain": "acme", "email": "agent@x.com", "api_token": "zt"}
    net = FakeNet(ok({"ticket": {"id": 77}}, 201))
    out = mod("zendesk").create_ticket(
        {
            "subject": "프린터",
            "body": "고장",
            "requester_email": "c@x.com",
            "requester_name": "고객",
            "priority": "high",
            "tags": "a, b",
        },
        sec,
        net,
    )
    c = net.calls[0]
    assert c["url"] == "https://acme.zendesk.com/api/v2/tickets.json"
    assert c["headers"]["Authorization"] == basic("agent@x.com/token", "zt")
    t = c["json"]["ticket"]
    assert t["comment"] == {"body": "고장"} and t["priority"] == "high" and t["tags"] == ["a", "b"]
    assert t["requester"] == {"name": "고객", "email": "c@x.com"}
    assert out == {"ticket_id": "77", "url": "https://acme.zendesk.com/agent/tickets/77"}
    assert_hosts_declared("zendesk", net)
    net2 = FakeNet(ok({"results": [{"id": 1, "subject": "A", "status": "open"}]}))
    res = mod("zendesk").search_tickets({"query": "status:open 환불", "limit": 5}, sec, net2)
    q = parse_qs(urlparse(net2.calls[0]["url"]).query)
    assert q["query"] == ["type:ticket status:open 환불"] and q["per_page"] == ["5"]
    assert res["count"] == 1 and "#1 [open] A" in res["text"]
    with pytest.raises(NodeError, match="서브도메인"):
        mod("zendesk").create_ticket(
            {"subject": "s", "body": "b"}, {**sec, "subdomain": "evil.com/x"}, FakeNet()
        )
    with pytest.raises(NodeError, match="우선순위"):
        mod("zendesk").create_ticket({"subject": "s", "body": "b", "priority": "x"}, sec, FakeNet())
    assert mod("zendesk").create_ticket.__name__ == "create_ticket"
    full = {**sec, "subdomain": "https://acme.zendesk.com/"}
    net3 = FakeNet(ok({"ticket": {"id": 1}}, 201))
    mod("zendesk").create_ticket({"subject": "s", "body": "b"}, full, net3)
    assert net3.calls[0]["url"].startswith("https://acme.zendesk.com/")


def test_freshdesk() -> None:
    sec = {"domain": "acme", "api_key": "fk"}
    net = FakeNet(ok({"id": 5}, 201))
    out = mod("freshdesk").create_ticket(
        {"subject": "문의", "description": "내용", "email": "c@x.com", "priority": 3}, sec, net
    )
    c = net.calls[0]
    assert c["url"] == "https://acme.freshdesk.com/api/v2/tickets"
    assert c["headers"]["Authorization"] == basic("fk", "X")
    assert c["json"] == {
        "subject": "문의",
        "description": "내용",
        "email": "c@x.com",
        "priority": 3,
        "status": 2,
    }
    assert out == {"ticket_id": "5", "url": "https://acme.freshdesk.com/a/tickets/5"}
    assert_hosts_declared("freshdesk", net)
    net2 = FakeNet(ok([{"id": 1, "subject": "A", "status": 2}]))
    res = mod("freshdesk").list_tickets({"limit": 3}, sec, net2)
    assert net2.calls[0]["url"].endswith("/api/v2/tickets?per_page=3") and res["count"] == 1
    with pytest.raises(NodeError, match="우선순위"):
        mod("freshdesk").create_ticket(
            {"subject": "s", "description": "d", "email": "a@x.com", "priority": 9}, sec, FakeNet()
        )
    with pytest.raises(NodeError, match="인증"):
        mod("freshdesk").list_tickets({}, sec, FakeNet(ok({}, 401)))


def test_shopify() -> None:
    sec = {"shop": "my-shop.myshopify.com", "access_token": "shpat_x"}
    net = FakeNet(
        ok(
            {
                "orders": [
                    {
                        "id": 1,
                        "name": "#1001",
                        "email": "a@x.com",
                        "total_price": "12000",
                        "currency": "KRW",
                        "financial_status": "paid",
                    }
                ]
            }
        )
    )
    out = mod("shopify").list_orders({"status": "open", "limit": 99}, sec, net)
    c = net.calls[0]
    parsed = urlparse(c["url"])
    assert (
        parsed.hostname == "my-shop.myshopify.com"
        and parsed.path == "/admin/api/2024-10/orders.json"
    )
    assert parse_qs(parsed.query) == {"status": ["open"], "limit": ["50"]}
    assert c["headers"] == {"X-Shopify-Access-Token": "shpat_x"} and c["method"] == "GET"
    assert out["count"] == 1 and "#1001 12000 KRW (paid)" in out["text"]
    assert_hosts_declared("shopify", net)
    short = FakeNet(ok({"orders": []}))
    mod("shopify").list_orders({}, {**sec, "shop": "my-shop"}, short)
    assert short.calls[0]["url"].startswith("https://my-shop.myshopify.com/")
    with pytest.raises(NodeError, match="상점 주소"):
        mod("shopify").list_orders({}, {**sec, "shop": "evil.com"}, FakeNet())
    with pytest.raises(NodeError, match="주문 상태"):
        mod("shopify").list_orders({"status": "x"}, sec, FakeNet())
    with pytest.raises(NodeError, match="read_orders"):
        mod("shopify").list_orders({}, sec, FakeNet(ok({}, 403)))


def test_salesforce() -> None:
    sec = {"instance_url": "https://acme.my.salesforce.com", "access_token": "sf-token"}
    net = FakeNet(ok({"id": "00Q1", "success": True}, 201))
    out = mod("salesforce").create_lead(
        {"last_name": "김", "company": "ACME", "email": "k@x.com", "lead_source": "Web"}, sec, net
    )
    c = net.calls[0]
    assert c["url"] == "https://acme.my.salesforce.com/services/data/v60.0/sobjects/Lead"
    assert c["headers"]["Authorization"] == "Bearer sf-token"
    assert c["json"] == {
        "LastName": "김",
        "Company": "ACME",
        "Email": "k@x.com",
        "LeadSource": "Web",
    }
    assert out == {"lead_id": "00Q1", "success": True}
    assert_hosts_declared("salesforce", net)
    net2 = FakeNet(ok({"totalSize": 1, "records": [{"attributes": {}, "Id": "1", "Name": "A"}]}))
    res = mod("salesforce").query({"soql": "SELECT Id, Name\n FROM Lead LIMIT 1"}, sec, net2)
    q = parse_qs(urlparse(net2.calls[0]["url"]).query)
    assert q["q"] == ["SELECT Id, Name FROM Lead LIMIT 1"]
    assert res["count"] == 1 and res["records"] == [{"Id": "1", "Name": "A"}]
    with pytest.raises(NodeError, match="SELECT"):
        mod("salesforce").query({"soql": "DELETE FROM Lead"}, sec, FakeNet())
    with pytest.raises(NodeError, match="인스턴스 주소"):
        mod("salesforce").create_lead(
            {"last_name": "a", "company": "b"},
            {**sec, "instance_url": "https://evil.com"},
            FakeNet(),
        )
    with pytest.raises(NodeError, match="만료"):
        mod("salesforce").query({"soql": "SELECT Id FROM Lead"}, sec, FakeNet(ok([], 401)))


def test_clickup_and_monday() -> None:
    net = FakeNet(ok({"id": "t1", "url": "https://app.clickup.com/t/t1"}))
    out = mod("clickup").create_task(
        {"list_id": "9001", "name": "할 일", "description": "설명", "priority": 2},
        {"api_token": "pk_1"},
        net,
    )
    c = net.calls[0]
    assert c["url"] == "https://api.clickup.com/api/v2/list/9001/task"
    assert c["headers"]["Authorization"] == "pk_1"  # Bearer 없이
    assert c["json"] == {"name": "할 일", "description": "설명", "priority": 2}
    assert out == {"task_id": "t1", "url": "https://app.clickup.com/t/t1"}
    assert_hosts_declared("clickup", net)
    with pytest.raises(NodeError, match="우선순위"):
        mod("clickup").create_task(
            {"list_id": "9001", "name": "n", "priority": 7}, {"api_token": "t"}, FakeNet()
        )

    net2 = FakeNet(ok({"data": {"create_item": {"id": "55"}}}))
    res = mod("monday").create_item(
        {"board_id": "123", "item_name": "새 항목", "column_values": {"status": {"label": "Done"}}},
        {"api_token": "mk"},
        net2,
    )
    c2 = net2.calls[0]
    assert c2["url"] == "https://api.monday.com/v2" and c2["headers"]["Authorization"] == "mk"
    assert "create_item" in c2["json"]["query"]
    assert c2["json"]["variables"] == {
        "board": "123",
        "name": "새 항목",
        "cols": json.dumps({"status": {"label": "Done"}}, ensure_ascii=False),
    }
    assert res == {"item_id": "55"}
    assert_hosts_declared("monday", net2)
    with pytest.raises(NodeError, match="거절"):
        mod("monday").create_item(
            {"board_id": "1", "item_name": "n"},
            {"api_token": "t"},
            FakeNet(ok({"errors": [{"message": "Board not found"}]})),
        )
    with pytest.raises(NodeError, match="숫자"):
        mod("monday").create_item(
            {"board_id": "abc", "item_name": "n"}, {"api_token": "t"}, FakeNet()
        )


def test_solapi_signature() -> None:
    sec = {"api_key": "NCSKEY", "api_secret": "sec-ret", "sender": "02-123-4567"}
    net = FakeNet(ok({"groupId": "G1", "messageId": "M1", "statusMessage": "접수"}))
    out = mod("solapi").send_sms({"to": "010-1234-5678", "text": "안녕"}, sec, net)
    c = net.calls[0]
    assert c["url"] == "https://api.solapi.com/messages/v4/send"
    date, salt = "2026-11-05T01:02:03.000Z", "ab" * 8
    sig = hmac.new(b"sec-ret", (date + salt).encode(), hashlib.sha256).hexdigest()
    assert c["headers"]["Authorization"] == (
        f"HMAC-SHA256 apiKey=NCSKEY, date={date}, salt={salt}, signature={sig}"
    )
    assert c["json"] == {"message": {"to": "01012345678", "from": "021234567", "text": "안녕"}}
    assert out == {"group_id": "G1", "message_id": "M1", "status": "접수"}
    assert "sec-ret" not in json.dumps(c["headers"])  # Secret 자체는 보내지 않는다
    assert_hosts_declared("solapi", net)
    net2 = FakeNet(ok({"groupId": "G2", "messageId": "M2"}))
    mod("solapi").send_alimtalk(
        {
            "to": "+82 10 1234 5678",
            "pf_id": "PF1",
            "template_id": "T1",
            "variables": {"#{이름}": "홍길동"},
        },
        sec,
        net2,
    )
    assert net2.calls[0]["json"]["message"]["kakaoOptions"] == {
        "pfId": "PF1",
        "templateId": "T1",
        "variables": {"#{이름}": "홍길동"},
    }
    assert net2.calls[0]["json"]["message"]["to"] == "01012345678"
    with pytest.raises(NodeError, match="받는 번호"):
        mod("solapi").send_sms({"to": "123", "text": "x"}, sec, FakeNet())
    with pytest.raises(NodeError, match="인증"):
        mod("solapi").send_sms({"to": "01012345678", "text": "x"}, sec, FakeNet(ok({}, 401)))
    assert "1500" in mod("solapi").test(sec, FakeNet(ok({"balance": 1500})))["message"]


def test_naver_sens_signature() -> None:
    sec = {
        "access_key": "AK",
        "secret_key": "SK",
        "service_id": "ncp:sms:kr:1234:svc",
        "sender": "0212345678",
    }
    net = FakeNet(ok({"requestId": "R1", "statusName": "success"}, 202))
    out = mod("naver_sens").send_sms({"to": "010-1234-5678", "content": "짧은 글"}, sec, net)
    c = net.calls[0]
    uri = "/sms/v2/services/ncp:sms:kr:1234:svc/messages"
    assert c["url"] == "https://sens.apigw.ntruss.com" + uri
    ts = "1700000000000"
    expect = base64.b64encode(
        hmac.new(b"SK", f"POST {uri}\n{ts}\nAK".encode(), hashlib.sha256).digest()
    ).decode()
    assert c["headers"]["x-ncp-apigw-timestamp"] == ts
    assert c["headers"]["x-ncp-iam-access-key"] == "AK"
    assert c["headers"]["x-ncp-apigw-signature-v2"] == expect
    assert "SK" not in json.dumps(
        {k: v for k, v in c["headers"].items() if k != "x-ncp-apigw-signature-v2"}
    )
    assert c["json"]["type"] == "SMS" and c["json"]["messages"] == [{"to": "01012345678"}]
    assert out == {"request_id": "R1", "type": "SMS", "status": "success"}
    assert_hosts_declared("naver_sens", net)
    long = FakeNet(ok({"requestId": "R2"}, 202))
    mod("naver_sens").send_sms(
        {"to": "01012345678", "content": "가" * 60, "subject": "안내"}, sec, long
    )
    body = long.calls[0]["json"]
    assert body["type"] == "LMS" and body["subject"] == "안내"
    with pytest.raises(NodeError, match="서비스 ID"):
        mod("naver_sens").send_sms(
            {"to": "01012345678", "content": "x"}, {**sec, "service_id": "a b"}, FakeNet()
        )
    t = FakeNet()
    assert "형식이 맞아요" in mod("naver_sens").test(sec, t)["message"] and t.calls == []


# ---------------- 플랫폼의 서명 도우미(진짜 ConnectorNet) ----------------
def test_connector_net_helpers() -> None:
    net = ConnectorNet({"permissions": ["network:api.example.com"]})
    assert net.sign_hmac_sha256("k", "m") == hmac.new(b"k", b"m", hashlib.sha256).hexdigest()
    b64 = net.sign_hmac_sha256("k", "m", encoding="base64")
    assert base64.b64decode(b64) == hmac.new(b"k", b"m", hashlib.sha256).digest()
    assert len(net.random_hex(16)) == 32 and net.random_hex(16) != net.random_hex(16)
    assert net.now_iso().endswith(".000Z") and len(net.now_iso()) == 24
    assert net.now_ms() > 1_700_000_000_000


# ---------------- 끝까지(설치 → 연결 정보 → 흐름 실행 → 연결 테스트) ----------------
def test_connector_end_to_end_and_masking(
    client: TestClient, team: Team, monkeypatch: pytest.MonkeyPatch
) -> None:
    install(client, team, "twilio")
    secrets = {
        "account_sid": "ACabcdef",
        "auth_token": "tw-secret-token-9999",
        "from_number": "+15005550006",
    }
    cred = client.post(
        f"/api/v1/workspaces/{team.ws}/connectors/credentials",
        json={"connector_key": "twilio", "name": "트윌리오", "secrets": secrets},
        headers=team.h("owner"),
    )
    assert cred.status_code == 200, cred.text
    cid = cred.json()["id"]
    assert secrets["auth_token"] not in cred.text
    sent: list[dict[str, Any]] = []

    def fake(
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        body: Any = None,
        form: dict[str, str] | None = None,
        allowed_domains: list[str] | None = None,
        **kw: Any,
    ) -> dict[str, Any]:
        sent.append(
            {
                "url": url,
                "form": form,
                "domains": allowed_domains,
                "auth": (headers or {}).get("Authorization"),
            }
        )
        return {"status": 201, "body": {"sid": "SM9", "status": "queued"}, "headers": {}}

    monkeypatch.setattr(safe_http, "request", fake)
    t = client.post(
        f"/api/v1/workspaces/{team.ws}/connectors/credentials/{cid}/test", headers=team.h("builder")
    )
    assert t.status_code == 200 and t.json()["ok"] and secrets["auth_token"] not in t.text
    graph = {
        "nodes": [
            {"id": "n1", "type": "input", "data": {"fields": [{"key": "phone"}]}},
            {
                "id": "n2",
                "type": "connector",
                "data": {
                    "connector": "twilio",
                    "credential_id": cid,
                    "action": "send_sms",
                    "params": {"to": "{{n1.phone}}", "body": "접수됐어요"},
                },
            },
            {"id": "n3", "type": "output", "data": {"template": "{{n2.message_sid}}"}},
        ],
        "edges": [
            {"id": "e1", "source": "n1", "target": "n2"},
            {"id": "e2", "source": "n2", "target": "n3"},
        ],
    }
    d = start(client, team, make_app(client, team, graph), {"phone": "+821012345678"})
    assert d["status"] == "succeeded", d["error"]
    assert d["output"]["text"] == "SM9"
    call = sent[-1]
    assert call["domains"] == ["api.twilio.com"] and call["form"]["To"] == "+821012345678"
    assert call["auth"] == basic("ACabcdef", "tw-secret-token-9999")
    assert secrets["auth_token"] not in json.dumps(d)


# ---------------- 새 템플릿 ----------------
def graph_of(key: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(
        (items_dir() / key / "template.json").read_text(encoding="utf-8")
    )
    return data


@pytest.mark.parametrize("key", TEMPLATES)
def test_new_templates_validate_and_require_connectors(key: str) -> None:
    result = validate_graph(graph_of(key), ValidationEnv(registry=registry))
    assert result.valid, [e.message for e in result.errors]
    manifest = read_manifest(items_dir() / key)
    used = {n["data"]["connector"] for n in graph_of(key)["nodes"] if n["type"] == "connector"}
    assert used == set(manifest["requires"]["items"])
    for c in used:
        actions = {a["key"] for a in read_manifest(items_dir() / c)["actions"]}
        for n in graph_of(key)["nodes"]:
            if n["data"].get("connector") == c:
                assert n["data"]["action"] in actions
    for blank in manifest["blanks"]:
        node = next(n for n in graph_of(key)["nodes"] if n["id"] == blank["node_id"])
        assert blank["field"].split(".")[0] in node["data"]


def test_two_templates_fan_out() -> None:
    fan = 0
    for key in TEMPLATES:
        counts: dict[str, int] = {}
        for e in graph_of(key)["edges"]:
            counts[e["source"]] = counts.get(e["source"], 0) + 1
        fan += 1 if max(counts.values()) > 1 else 0
    assert fan == 2
