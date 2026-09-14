"""Exception handlers producing a single error envelope.

Every failure returns ``{"error": {"code", "message", "remedy?", "details?"}}`` so the
frontend has one shape to render. Unexpected exceptions are logged with a traceback but
reported generically — internal detail must not leak to a client.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse

from app.core.errors import AppError
from app.core.logging import get_logger

logger = get_logger("app.errors")


def _envelope(payload: dict, status_code: int) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"error": payload})


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        log = logger.warning if exc.status_code < 500 else logger.error
        log("app_error", code=exc.code, status_code=exc.status_code, message=exc.message)
        return _envelope(exc.to_payload(), exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        fields = [
            {
                "field": ".".join(str(part) for part in error.get("loc", []) if part != "body") or "body",
                "message": error.get("msg", "invalid value"),
            }
            for error in exc.errors()
        ]
        logger.info("request_validation_failed", fields=[field["field"] for field in fields])
        return _envelope(
            {
                "code": "validation_failed",
                "message": "The request payload is invalid.",
                "details": {"fields": fields},
            },
            422,
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        codes = {404: "not_found", 405: "method_not_allowed", 401: "unauthorized", 403: "forbidden"}
        return _envelope(
            {"code": codes.get(exc.status_code, "http_error"), "message": str(exc.detail)}, exc.status_code
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_exception", error_type=type(exc).__name__)
        return _envelope(
            {"code": "internal_error", "message": "An unexpected internal error occurred."}, 500
        )
