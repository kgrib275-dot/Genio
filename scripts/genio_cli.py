#!/usr/bin/env python3
"""제니오 명령줄 도구(표준 라이브러리만 사용). 앱 API 키(gk-…)로 앱을 터미널·스크립트·CI에서 부른다.

키 하나는 앱 하나에 묶여 있다(앱의 'API' 화면에서 만든다). 그래서 '앱 목록'은 없고, 그 앱을
실행하거나 대화하고 결과를 읽는 명령만 있다.

사용 예
  export GENIO_URL=https://genio.example.com     # 기본값 http://127.0.0.1:5190
  export GENIO_API_KEY=gk-xxxxxxxx
  python scripts/genio_cli.py info
  python scripts/genio_cli.py run -i city=도쿄 -i days:=3         # 흐름 실행(끝날 때까지 기다림)
  python scripts/genio_cli.py chat "휴가 규정 알려줘"
  python scripts/genio_cli.py runs --limit 5
  python scripts/genio_cli.py run gk-xxxxxxxx -i name=김     # 키를 첫 인자로 줘도 돼요

입력값: `이름=글`은 글로, `이름:=JSON`은 JSON 값(숫자·참거짓·목록)으로 보냅니다.
옵션: --url, --key, --json(결과를 JSON 그대로 출력). 종료 코드: 0 성공, 1 API 오류, 2 사용법 오류.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from typing import Any, TextIO

DEFAULT_URL = "http://127.0.0.1:5190"
LONG_TIMEOUT = 150  # 흐름 실행·대화는 서버가 결과를 기다려 주므로 넉넉히


class CliError(Exception):
    """사용자에게 두 줄로 보여 줄 오류(무엇이 문제 + 어떻게 하면 되는지)."""

    def __init__(self, message: str, hint: str = "", code: int = 1) -> None:
        super().__init__(message)
        self.message, self.hint, self.code = message, hint, code


def parse_inputs(pairs: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for raw in pairs:
        if ":=" in raw:
            key, _, val = raw.partition(":=")
            try:
                out[key.strip()] = json.loads(val)
            except ValueError:
                raise CliError(
                    f"'{raw}'의 JSON 값이 올바르지 않아요.",
                    '예: -i days:=3, -i vip:=true, -i tags:=\'["a","b"]\'',
                    2,
                ) from None
        elif "=" in raw:
            key, _, val = raw.partition("=")
            out[key.strip()] = val
        else:
            raise CliError(f"'{raw}'은(는) 입력 형식이 아니에요.", "이름=값 처럼 적어 주세요.", 2)
        if not key.strip():
            raise CliError(f"'{raw}'에 이름이 없어요.", "이름=값 처럼 적어 주세요.", 2)
    return out


Opener = Callable[..., Any]


def call(
    base: str,
    key: str,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    *,
    opener: Opener = urllib.request.urlopen,
) -> Any:
    if not base.lower().startswith(("http://", "https://")):
        raise CliError(
            f"주소 '{base}'가 올바르지 않아요.",
            "http:// 또는 https://로 시작하는 주소를 넣으세요.",
            2,
        )
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(  # noqa: S310 - 위에서 http(s)만 허용
        base.rstrip("/") + "/api/v1/service" + path,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json",
        },
    )
    try:
        with opener(req, timeout=LONG_TIMEOUT) as res:
            return json.loads(res.read().decode("utf-8") or "null")
    except urllib.error.HTTPError as exc:
        message, hint = f"서버가 오류로 답했어요(코드 {exc.code}).", ""
        try:
            detail = json.loads(exc.read().decode("utf-8")).get("detail") or {}
            if isinstance(detail, dict):
                message = str(detail.get("message") or message)
                hint = str(detail.get("hint") or "")
        except (ValueError, OSError):
            pass
        raise CliError(message, hint) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise CliError(
            f"{base}에 접속하지 못했어요.",
            "주소(--url 또는 GENIO_URL)와 네트워크를 확인하세요.",
        ) from None


def _split_key(args: argparse.Namespace, env: Mapping[str, str]) -> str:
    """첫 위치 인자가 gk-로 시작하면 키로 본다. 없으면 --key, 그다음 GENIO_API_KEY."""
    pos: list[str] = args.rest
    if pos and pos[0].startswith("gk-"):
        args.key = pos.pop(0)
    key = args.key or env.get("GENIO_API_KEY", "")
    if not key:
        raise CliError(
            "앱 API 키가 없어요.",
            "--key gk-… 로 주거나 환경 변수 GENIO_API_KEY에 넣으세요(앱의 API 화면에서 만들어요).",
            2,
        )
    return key


def _print(out: TextIO, text: str = "") -> None:
    out.write(text + "\n")


def main(
    argv: list[str],
    *,
    opener: Opener = urllib.request.urlopen,
    out: TextIO = sys.stdout,
    err: TextIO = sys.stderr,
    env: Mapping[str, str] | None = None,
) -> int:
    env = os.environ if env is None else env
    p = argparse.ArgumentParser(prog="genio_cli.py", description="제니오 앱 API 명령줄 도구")
    p.add_argument("command", choices=["info", "run", "chat", "runs", "run-status"])
    p.add_argument(
        "rest", nargs="*", help="[키] 와 명령에 필요한 값(chat은 메시지, run-status는 run_id)"
    )
    p.add_argument("--url", default=env.get("GENIO_URL", DEFAULT_URL))
    p.add_argument("--key", default="")
    p.add_argument("-i", "--input", action="append", default=[], metavar="이름=값")
    p.add_argument("-c", "--conversation", default=None, help="chat: 이어서 말할 대화 id")
    p.add_argument("--limit", type=int, default=20, help="runs: 가져올 개수(최대 100)")
    p.add_argument("--status", default=None, help="runs: succeeded|failed|running …")
    p.add_argument("--json", action="store_true", help="결과를 JSON 그대로 출력")
    try:
        args = p.parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code else 0
    try:
        key = _split_key(args, env)
        base: str = args.url
        inputs = parse_inputs(args.input)
        data: Any
        if args.command == "info":
            data = call(base, key, "GET", "/parameters", opener=opener)
            lines = [f"앱: {data['app']['name']} ({data['app']['type']}) · 버전 {data['version']}"]
            for f in data.get("input_fields") or []:
                lines.append(
                    f"  입력 {f.get('key')}: {f.get('label') or ''} [{f.get('type')}]"
                    + (" (필수)" if f.get("required") else "")
                )
        elif args.command == "run":
            data = call(base, key, "POST", "/workflows/run", {"inputs": inputs}, opener=opener)
            lines = [f"상태: {data['status']} · 실행 {data['run_id']} · {data['elapsed_ms']}ms"]
            if data.get("error"):
                lines.append(f"오류: {data['error']}")
            text = (data.get("outputs") or {}).get("text")
            if text:
                lines += ["", str(text)]
        elif args.command == "chat":
            if not args.rest:
                raise CliError("보낼 메시지가 없어요.", '예: genio_cli.py chat "안녕하세요"', 2)
            msg = " ".join(args.rest)
            body: dict[str, Any] = {"query": msg, "inputs": inputs}
            if args.conversation:
                body["conversation_id"] = args.conversation
            data = call(base, key, "POST", "/chat-messages", body, opener=opener)
            lines = [str(data.get("answer", "")), "", f"(대화 id: {data.get('conversation_id')})"]
        elif args.command == "runs":
            q = f"?limit={max(1, min(args.limit, 100))}" + (
                f"&status={args.status}" if args.status else ""
            )
            data = call(base, key, "GET", "/runs" + q, opener=opener)
            lines = [
                f"{r['created_at']}  {r['status']:<10} {r['run_id']}  {r.get('error') or ''}".rstrip()
                for r in data
            ]
            lines = lines or ["실행 기록이 없어요."]
        else:  # run-status
            if not args.rest:
                raise CliError("run_id가 없어요.", "예: genio_cli.py run-status <run_id>", 2)
            data = call(base, key, "GET", f"/runs/{args.rest[0]}", opener=opener)
            lines = [f"상태: {data['status']} · {data.get('trigger')}"]
            if data.get("error"):
                lines.append(f"오류: {data['error']}")
            text = (data.get("outputs") or {}).get("text")
            if text:
                lines += ["", str(text)]
    except CliError as exc:
        _print(err, exc.message)
        if exc.hint:
            _print(err, exc.hint)
        return exc.code
    if args.json:
        _print(out, json.dumps(data, ensure_ascii=False, indent=2))
    else:
        _print(out, "\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
