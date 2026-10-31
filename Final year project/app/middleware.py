from urllib.parse import urlparse

from starlette.responses import PlainTextResponse

from app.reports import MAX_UPLOAD


def mutation_origin_allowed(request, settings):
    origin = request.headers.get("origin")
    if origin is None or origin.rstrip("/") == settings.app_origin.rstrip("/"):
        return True
    if (
        settings.transport_mode != "private_tunnel"
        or request.headers.get("sec-fetch-site") != "same-origin"
    ):
        return False
    try:
        rewritten = urlparse(origin)
        server = request.scope.get("server")
        # Dev Tunnels can rewrite Origin to the loopback HTTP target after TLS termination.
        return bool(
            server
            and rewritten.scheme == "http"
            and rewritten.hostname in {"localhost", "127.0.0.1", "::1"}
            and (rewritten.port or 80) == server[1]
            and rewritten.path in {"", "/"}
            and not rewritten.username
            and not rewritten.password
            and not rewritten.query
            and not rewritten.fragment
        )
    except ValueError:
        return False


class BodyLimitMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in {"POST", "PUT", "PATCH", "DELETE"}:
            return await self.app(scope, receive, send)
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > MAX_UPLOAD + 65536:
                response = PlainTextResponse("Request too large", status_code=413)
                return await response(scope, receive, send)
            if not message.get("more_body", False):
                break
        replayed = False

        async def replay():
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        return await self.app(scope, replay, send)
