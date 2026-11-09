"""Request-ID and access-log middleware.

Every request gets an id (the client's X-Request-ID if it is safe, otherwise a
new one). The id is returned in the X-Request-ID header and written to one log
line per request with the method, path, status and duration.

This is plain ASGI middleware rather than @app.middleware("http"), so streamed
responses such as the SSE stream pass straight through.
"""

import json
import logging
import re
import time
import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger("leavedesk.api")

SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def _incoming_request_id(scope: Scope) -> str | None:
    for name, value in scope.get("headers", []):
        if name == b"x-request-id":
            candidate = value.decode("latin-1")
            # Reject odd values so nobody can inject text into our logs.
            return candidate if SAFE_REQUEST_ID.match(candidate) else None
    return None


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = _incoming_request_id(scope) or uuid.uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id
        start = time.perf_counter()
        status = 500
        response_started = False

        async def send_with_request_id(message: Message) -> None:
            nonlocal status, response_started
            if message["type"] == "http.response.start":
                response_started = True
                status = message["status"]
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode()))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        except Exception:
            logger.exception("Unhandled error [request_id=%s]", request_id)
            if response_started:
                raise
            status = 500
            await self._send_internal_error(send, request_id)
        finally:
            logger.info(
                "%s %s -> %s in %.1f ms [request_id=%s]",
                scope["method"],
                scope["path"],
                status,
                (time.perf_counter() - start) * 1000,
                request_id,
            )

    @staticmethod
    async def _send_internal_error(send: Send, request_id: str) -> None:
        # A generic message only: the stack trace goes to the log, never the client.
        body = json.dumps(
            {
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "something went wrong",
                    "request_id": request_id,
                    "details": [],
                }
            }
        ).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 500,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                    (b"x-request-id", request_id.encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
