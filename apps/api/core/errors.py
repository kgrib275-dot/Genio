"""사용자에게 보이는 오류. 항상 '무엇이 문제인지(message) + 어떻게 하면 되는지(hint)' 두 줄."""

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class AppError(Exception):
    def __init__(
        self,
        status: int,
        message: str,
        hint: str,
        *,
        errors: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.hint = hint
        self.errors = errors


def not_found(what: str) -> AppError:
    return AppError(
        404, f"{what}을(를) 찾을 수 없어요.", "주소가 맞는지 확인하거나 목록에서 다시 선택하세요."
    )


def forbidden() -> AppError:
    return AppError(
        403, "이 작업을 할 권한이 없어요.", "워크스페이스 관리자에게 역할 변경을 요청하세요."
    )


def bad_request(message: str, hint: str) -> AppError:
    return AppError(400, message, hint)


def _body(message: str, hint: str, errors: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    detail: dict[str, Any] = {"message": message, "hint": hint}
    if errors is not None:
        detail["errors"] = errors
    return {"detail": detail}


_FIELD_NAMES = {
    "email": "이메일",
    "password": "비밀번호",
    "name": "이름",
    "role": "역할",
    "graph": "흐름",
}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status, content=_body(exc.message, exc.hint, exc.errors)
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        fields = []
        for err in exc.errors():
            loc = [str(p) for p in err.get("loc", []) if p not in ("body", "query", "path")]
            if loc:
                fields.append(_FIELD_NAMES.get(loc[-1], loc[-1]))
        names = ", ".join(dict.fromkeys(fields)) or "요청"
        return JSONResponse(
            status_code=422,
            content=_body(
                f"입력값이 올바르지 않아요: {names}",
                "빠진 칸이 없는지, 형식이 맞는지 확인한 뒤 다시 시도하세요.",
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        if exc.status_code == 401:
            msg, hint = "로그인이 필요해요.", "다시 로그인한 뒤 시도하세요."
        elif exc.status_code == 404:
            msg, hint = "요청한 주소를 찾을 수 없어요.", "주소를 확인하세요."
        elif exc.status_code == 405:
            msg, hint = "지원하지 않는 요청 방식이에요.", "화면을 새로고침한 뒤 다시 시도하세요."
        else:
            msg, hint = "요청을 처리하지 못했어요.", "잠시 후 다시 시도하세요."
        return JSONResponse(status_code=exc.status_code, content=_body(msg, hint))

    @app.exception_handler(Exception)
    async def _unknown(_: Request, exc: Exception) -> JSONResponse:
        import logging

        logging.getLogger("genio").exception("처리되지 않은 오류: %s", type(exc).__name__)
        return JSONResponse(
            status_code=500,
            content=_body(
                "서버에서 문제가 생겼어요.",
                "잠시 후 다시 시도하고, 계속되면 관리자에게 알려 주세요.",
            ),
        )
