"""n8n 템플릿 가져오기(ADR 0020 2단계): n8n 워크플로우 JSON을 제니오 흐름 초안으로 바꾼다.

- `convert(doc)`는 DB를 쓰지 않는 순수 변환이다. 안전하게 옮길 수 있는 것만 옮긴다:
  시작(트리거) → 입력, 웹 요청 → 웹 요청, 응답 보내기 → 결과, 메모(sticky) → 메모.
- 나머지(코드·조건·앱 연동 등)는 '꺼 둔 자리 표시 단계'로 남겨 흐름 모양을 보이게 하고, 필요한
  연결 정보 종류를 변환 보고서에 적는다. 코드는 실행하지 않고, 비밀값은 가져오지 않는다.
- n8n 식(`{{ $json.x }}`·`={{ ... }}`)은 제니오 값 참조로 바꿀 수 없어 비우고 개수를 보고서에 적는다.
- 가져온 앱은 늘 '초안'이다.
"""

import re
from typing import Any

from api.core.errors import AppError
from api.services.dify_import import Converted, Report, _as_dict, _as_list, _s

MAX_NODES = 300
EXPR_RE = re.compile(r"\{\{.*?\}\}", re.DOTALL)
HTTP_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")

TRIGGER_HINTS = {
    "webhook": "'외부에서 받기'는 앱 설정에서 새로 만들어 주세요.",
    "scheduletrigger": "예약 실행은 앱의 '예약'에서 새로 정해 주세요.",
    "cron": "예약 실행은 앱의 '예약'에서 새로 정해 주세요.",
    "chattrigger": "챗봇으로 쓰려면 앱 종류를 '챗봇'으로 바꿔 주세요.",
    "formtrigger": "입력 항목은 '시작' 단계에서 직접 만들어 주세요.",
}


def _short_type(t: str) -> str:
    return t.split(".")[-1]


def _is_trigger(t: str) -> bool:
    s = _short_type(t).lower()
    return s.endswith("trigger") or s in ("webhook", "cron", "start")


class _Converter:
    def __init__(self) -> None:
        self.report = Report(mode="n8n")
        self.nodes: list[dict[str, Any]] = []
        self.notes: list[dict[str, Any]] = []
        self.ids: dict[str, str] = {}  # n8n 노드 이름 → 제니오 id
        self.expr_count = 0
        self.counter = 1
        self.has_input = False

    def new_id(self) -> str:
        self.counter += 1
        return f"n{self.counter}"

    def warn(self, msg: str) -> None:
        if msg not in self.report.warnings:
            self.report.warnings.append(msg)

    def attention(self, node: str, label: str, msg: str) -> None:
        self.report.needs_attention.append({"node": node, "label": label, "message": msg})

    def txt(self, value: Any) -> str:
        """n8n 글: 앞의 '='를 떼고 식({{ }})은 비운다."""
        s = _s(value)
        if s.startswith("="):
            s = s[1:]
        s, n = EXPR_RE.subn("", s)
        self.expr_count += n
        return s.strip()

    def add(
        self,
        n8n: dict[str, Any],
        gtype: str,
        data: dict[str, Any],
        gid: str | None = None,
        disabled: bool = False,
    ) -> str:
        name = _s(n8n.get("name"))
        node_id = gid or self.new_id()
        self.ids[name] = node_id
        pos = _as_list(n8n.get("position"))
        x = float(pos[0]) if len(pos) > 0 and isinstance(pos[0], int | float) else 0.0
        y = float(pos[1]) if len(pos) > 1 and isinstance(pos[1], int | float) else 0.0
        node: dict[str, Any] = {
            "id": node_id,
            "type": gtype,
            "position": {"x": x, "y": y},
            "data": {"label": name[:60] or gtype, **data},
        }
        if disabled:
            node["disabled"] = True
        self.nodes.append(node)
        return node_id

    def done(self, gid: str, n8n: dict[str, Any], gtype: str) -> None:
        self.report.converted.append(
            {
                "node": gid,
                "label": _s(n8n.get("name")),
                "dify_type": _short_type(_s(n8n.get("type"))),
                "genio_type": gtype,
            }
        )

    def placeholder(self, n8n: dict[str, Any], why: str) -> None:
        t = _short_type(_s(n8n.get("type"))) or "알 수 없음"
        msg = f"n8n '{t}' 단계는 자동으로 옮기지 않았어요. {why}".strip()
        gid = self.add(n8n, "template", {"template": f"({msg})", "note": msg[:300]}, disabled=True)
        self.report.unsupported.append(
            {"node": gid, "label": _s(n8n.get("name")), "dify_type": t, "message": msg}
        )
        creds = _as_dict(n8n.get("credentials"))
        for ctype in creds:
            self.attention(
                gid,
                _s(n8n.get("name")),
                f"이 단계는 '{ctype}' 연결이 필요해요. 연결 정보를 만든 뒤 알맞은 단계로 바꿔 주세요.",
            )

    # ---- 종류별 ----
    def convert(self, n8n: dict[str, Any]) -> None:
        t = _s(n8n.get("type"))
        short = _short_type(t)
        if _is_trigger(t):
            if not self.has_input:
                self.has_input = True
                hint = TRIGGER_HINTS.get(short.lower(), "")
                gid = self.add(
                    n8n,
                    "input",
                    {
                        "fields": [
                            {"key": "message", "label": "입력", "type": "text", "required": False}
                        ]
                    },
                    gid="n1",
                )
                self.done(gid, n8n, "input")
                if hint:
                    self.attention(gid, _s(n8n.get("name")), hint)
            else:
                self.placeholder(n8n, "시작 단계는 하나만 쓸 수 있어요.")
            return
        if short == "httpRequest":
            self._http(n8n)
        elif short == "respondToWebhook":
            gid = self.add(n8n, "output", {"template": "완료"})
            self.done(gid, n8n, "output")
        else:
            self.placeholder(n8n, "")

    def _pairs(self, block: Any) -> dict[str, str]:
        out: dict[str, str] = {}
        for p in _as_list(_as_dict(block).get("parameters")):
            p = _as_dict(p)
            if p.get("name"):
                out[_s(p["name"])] = self.txt(p.get("value"))
        return out

    def _http(self, n8n: dict[str, Any]) -> None:
        p = _as_dict(n8n.get("parameters"))
        method = (_s(p.get("method")) or "GET").upper()
        if method not in HTTP_METHODS:
            self.warn(f"웹 요청 방식 '{method}'는 GET으로 바꿨어요.")
            method = "GET"
        url = self.txt(p.get("url"))
        if p.get("sendQuery"):
            q = "&".join(f"{k}={v}" for k, v in self._pairs(p.get("queryParameters")).items())
            if q:
                url = f"{url}{'&' if '?' in url else '?'}{q}"
        data: dict[str, Any] = {"method": method, "url": url}
        if p.get("sendHeaders"):
            headers = self._pairs(p.get("headerParameters"))
            if headers:
                data["headers"] = headers
        if p.get("sendBody"):
            body = self.txt(p.get("jsonBody")) if p.get("jsonBody") else ""
            if body:
                data["body"] = body
            elif p.get("bodyParameters"):
                data["body"] = self._pairs(p.get("bodyParameters"))
        gid = self.add(n8n, "http", data)
        auth = _s(p.get("authentication"))
        if auth and auth != "none":
            self.attention(
                gid,
                _s(n8n.get("name")),
                "인증 키는 옮기지 않아요. 연결 정보에서 'HTTP 인증 정보'를 만들어 이 단계에서 골라 주세요.",
            )
        elif _as_dict(n8n.get("credentials")):
            self.attention(
                gid, _s(n8n.get("name")), "인증 정보는 옮기지 않아요. 직접 연결해 주세요."
            )
        self.done(gid, n8n, "http")


def unwrap(doc: Any) -> dict[str, Any]:
    """템플릿 API 응답({workflow:{workflow:{...}}})이나 내보낸 JSON({nodes, connections})을 같은 모양으로."""
    d = _as_dict(doc)
    for _ in range(3):
        if "nodes" in d and "connections" in d:
            return d
        inner = d.get("workflow")
        if not isinstance(inner, dict):
            break
        d = inner
    raise AppError(
        422,
        "n8n 워크플로우 파일이 아니에요.",
        "n8n에서 내보낸 JSON(nodes와 connections가 있는 파일)을 올려 주세요.",
    )


def convert(doc: Any, *, name: str = "", description: str = "", source: str = "") -> Converted:
    wf = unwrap(doc)
    raw_nodes = [_as_dict(n) for n in _as_list(wf.get("nodes"))]
    if not raw_nodes:
        raise AppError(
            422, "흐름에 단계가 없어요.", "단계가 하나 이상 있는 워크플로우를 골라 주세요."
        )
    if len(raw_nodes) > MAX_NODES:
        raise AppError(422, "단계가 너무 많아요(최대 300개).", "더 작은 템플릿을 골라 주세요.")
    cv = _Converter()
    skipped: set[str] = set()
    work: list[dict[str, Any]] = []
    for n in raw_nodes:
        if _short_type(_s(n.get("type"))) == "stickyNote":
            pos = _as_list(n.get("position"))
            cv.notes.append(
                {
                    "id": f"note{len(cv.notes) + 1}",
                    "text": _s(_as_dict(n.get("parameters")).get("content"))[:5000],
                    "position": {
                        "x": float(pos[0])
                        if len(pos) > 0 and isinstance(pos[0], int | float)
                        else 0,
                        "y": float(pos[1])
                        if len(pos) > 1 and isinstance(pos[1], int | float)
                        else 0,
                    },
                    "color": "yellow",
                }
            )
            skipped.add(_s(n.get("name")))
        else:
            work.append(n)
    # 시작(트리거)을 먼저 바꿔 두면 n1이 입력 단계가 된다
    work.sort(key=lambda n: 0 if _is_trigger(_s(n.get("type"))) else 1)
    for n in work:
        cv.convert(n)
    if not cv.has_input:
        cv.nodes.insert(
            0,
            {
                "id": "n1",
                "type": "input",
                "position": {"x": 0, "y": 0},
                "data": {
                    "label": "시작",
                    "fields": [
                        {"key": "message", "label": "입력", "type": "text", "required": False}
                    ],
                },
            },
        )
        cv.warn("시작(트리거) 단계가 없어 입력 단계를 새로 만들었어요. 연결은 직접 이어 주세요.")
    edges: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for src_name, outs in _as_dict(wf.get("connections")).items():
        gs = cv.ids.get(_s(src_name))
        for branch in _as_list(_as_dict(outs).get("main")):
            for link in _as_list(branch):
                gt = cv.ids.get(_s(_as_dict(link).get("node")))
                if not gs or not gt or gs == gt or (gs, gt) in seen:
                    continue
                seen.add((gs, gt))
                edges.append({"id": f"e{len(edges) + 1}", "source": gs, "target": gt})
    if cv.nodes:
        mx = min(n["position"]["x"] for n in cv.nodes)
        my = min(n["position"]["y"] for n in cv.nodes)
        for n in cv.nodes:
            n["position"] = {
                "x": round(n["position"]["x"] - mx),
                "y": round(n["position"]["y"] - my),
            }
        for note in cv.notes:
            note["position"] = {
                "x": round(note["position"]["x"] - mx),
                "y": round(note["position"]["y"] - my),
            }
    if cv.expr_count:
        cv.warn(
            f"n8n 식 {cv.expr_count}곳은 제니오 값 참조로 바꿀 수 없어 비웠어요. 각 단계에서 '값 끌어오기'로 다시 지정해 주세요."
        )
    if source:
        cv.warn(f"출처: {source}. 사용 조건은 원본 템플릿 페이지에서 확인하세요.")
    graph: dict[str, Any] = {"version": 1, "nodes": cv.nodes, "edges": edges, "variables": {}}
    if cv.notes:
        graph["notes"] = cv.notes
    title = (name or _s(wf.get("name")) or "n8n에서 가져온 앱").strip()
    return Converted(
        name=title[:100],
        description=(description or "")[:2000],
        icon="",
        app_type="workflow",
        graph=graph,
        features={},
        env_vars=[],
        report=cv.report,
    )
