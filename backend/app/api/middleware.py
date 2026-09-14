"""Request middleware: correlation IDs, structured access logs, body size limit."""

from __future__ import annotations

import time
import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp

from app.core.logging import get_logger

logger = get_logger("app.request")

#: Ceiling on request bodies. Chat messages are capped far lower in the schema; this
#: protects the JSON parser from an oversized payload before validation runs.
MAX_BODY_BYTES = 1_000_000


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Bind a request id and emit one structured event per completed request."""

    async def dispatch(self, request: Request, call_next):  # noqa: ANN001, ANN201
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        structlog.contextvars.bind_contextvars(request_id=request_id, path=request.url.path, method=request.method)
        request.state.request_id = request_id

        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            # Exception handlers produce the response; this only records the failure.
            logger.exception("request_failed", duration_ms=int((time.perf_counter() - started) * 1000))
            structlog.contextvars.clear_contextvars()
            raise

        duration_ms = int((time.perf_counter() - started) * 1000)
        # Health polling every few seconds would drown the useful events.
        if request.url.path != "/health":
            logger.info("request_completed", status_code=response.status_code, duration_ms=duration_ms)
        response.headers["x-request-id"] = request_id
        structlog.contextvars.clear_contextvars()
        return response


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, max_bytes: int = MAX_BODY_BYTES) -> None:
        super().__init__(app)
        self._max_bytes = max_bytes

    async def dispatch(self, request: Request, call_next):  # noqa: ANN001, ANN201
        content_length = request.headers.get("content-length")
        if content_length and content_length.isdigit() and int(content_length) > self._max_bytes:
            logger.warning("request_body_too_large", content_length=int(content_length))
            return JSONResponse(
                status_code=413,
                content={
                    "error": {
                        "code": "payload_too_large",
                        "message": f"Request body exceeds the {self._max_bytes:,} byte limit.",
                    }
                },
            )
        return await call_next(request)
