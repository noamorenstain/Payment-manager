"""Local-only web security.

The server listens on 127.0.0.1 only, but any web page open in the browser could still try
to talk to it. These layers stop that:

1. **Host check** (every request): only ``127.0.0.1:<port>`` / ``localhost:<port>`` —
   defeats DNS-rebinding attacks.
2. **Origin check** (every state-changing request): the ``Origin`` (or, failing that, the
   ``Referer``) must be this app; ``Sec-Fetch-Site`` must be same-origin when present.
3. **CSRF token** (every state-changing request): a per-process secret that other sites
   cannot read, sent as the ``csrf_token`` form field or ``X-CSRF-Token`` header.
4. **Response headers**: nosniff, no framing, strict same-origin CSP on HTML pages, and
   ``Cache-Control: no-store`` so financial pages are not cached.
"""

from __future__ import annotations

import secrets
from urllib.parse import urlsplit

from fastapi import HTTPException, Request

from app.i18n import he

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
       "font-src 'self'; connect-src 'self'; form-action 'self'; frame-ancestors 'none'; "
       "base-uri 'none'; object-src 'none'")

_COMMON_HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"same-origin"),
    (b"cross-origin-opener-policy", b"same-origin"),
    (b"cross-origin-resource-policy", b"same-origin"),
]


def allowed_hosts(port: int) -> set[str]:
    return {f"127.0.0.1:{port}", f"localhost:{port}"}


def allowed_origins(port: int) -> set[str]:
    return {f"http://{h}" for h in allowed_hosts(port)}


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def _reject_page(status: int, message: str) -> tuple[int, bytes]:
    body = (f'<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8">'
            f"<title>{he.APP_TITLE}</title></head>"
            f'<body style="font-family:Segoe UI,Arial,sans-serif;padding:40px">'
            f"<h1>{he.SECURITY_BLOCKED_TITLE}</h1><p>{message}</p></body></html>")
    return status, body.encode("utf-8")


class SecurityMiddleware:
    """Pure ASGI middleware (does not consume the request body)."""

    def __init__(self, app, port: int):
        self.app = app
        self.hosts = allowed_hosts(port)
        self.origins = allowed_origins(port)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        problem = self._check(scope["method"], headers)
        if problem:
            status, body = _reject_page(*problem)
            await send({"type": "http.response.start", "status": status, "headers": [
                (b"content-type", b"text/html; charset=utf-8"),
                (b"content-length", str(len(body)).encode()),
                (b"cache-control", b"no-store"),
                *_COMMON_HEADERS,
            ]})
            await send({"type": "http.response.body", "body": body})
            return

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                existing = {k.lower() for k, _ in message.get("headers", [])}
                extra = [h for h in _COMMON_HEADERS if h[0] not in existing]
                content_type = dict(message.get("headers", [])).get(b"content-type", b"")
                if content_type.startswith(b"text/html"):
                    extra.append((b"content-security-policy", CSP.encode()))
                    if b"cache-control" not in existing:
                        extra.append((b"cache-control", b"no-store"))
                message = {**message, "headers": [*message.get("headers", []), *extra]}
            await send(message)

        await self.app(scope, receive, send_with_headers)

    def _check(self, method: str, headers: dict[str, str]) -> tuple[int, str] | None:
        if headers.get("host") not in self.hosts:
            return 400, he.SECURITY_BAD_HOST
        if method in SAFE_METHODS:
            return None
        fetch_site = headers.get("sec-fetch-site")
        if fetch_site is not None and fetch_site not in ("same-origin", "none"):
            return 403, he.SECURITY_CROSS_SITE
        origin = headers.get("origin")
        if origin is None:
            referer = headers.get("referer")
            if referer:
                parts = urlsplit(referer)
                origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self.origins:
            return 403, he.SECURITY_CROSS_SITE
        return None


async def csrf_protect(request: Request) -> None:
    """Global dependency: every state-changing request must carry the CSRF token."""
    if request.method in SAFE_METHODS:
        return
    expected = request.app.state.csrf_token
    token = request.headers.get("x-csrf-token")
    if not token:
        content_type = request.headers.get("content-type", "")
        if content_type.startswith(("application/x-www-form-urlencoded", "multipart/form-data")):
            form = await request.form()
            value = form.get("csrf_token")
            token = value if isinstance(value, str) else None
    if not token or not secrets.compare_digest(token, expected):
        raise HTTPException(status_code=403, detail=he.CSRF_FAILED)
