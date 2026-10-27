"""Cover response streaming as well as endpoint execution without body logging."""
import logging

from starlette.datastructures import MutableHeaders
from starlette.responses import JSONResponse

logger = logging.getLogger("v6.http")


class ConfidentialityMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        started = False

        async def private_send(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                headers = MutableHeaders(scope=message)
                headers["X-Content-Type-Options"] = "nosniff"
                headers["Referrer-Policy"] = "no-referrer"
                headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self'; frame-src 'self' blob:; worker-src 'self' blob:; object-src 'none'; base-uri 'self'; frame-ancestors 'self'"
                if scope.get("path", "").startswith("/api/"):
                    headers["Cache-Control"] = "no-store"
            await send(message)

        try:
            await self.app(scope, receive, private_send)
        except Exception:
            if started:
                # Do not send a second status or terminate a partial download as
                # successful. Let the server abort it with a fixed, chain-free
                # exception, so the client observes an incomplete response.
                logger.error("error_code=GD_RESPONSE_STREAM_FAILED")
                raise RuntimeError("GD_RESPONSE_STREAM_FAILED") from None
            logger.error("error_code=GD_HTTP_FAILED")
            response = JSONResponse(status_code=500, content={
                "detail": "当前操作未完成，请刷新检查状态后重试；如仍失败，请联系管理员。 [GD_HTTP_FAILED]"
            })
            try:
                await response(scope, receive, private_send)
            except Exception:
                raise RuntimeError("GD_RESPONSE_STREAM_FAILED") from None
