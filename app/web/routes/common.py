"""Helpers shared by route modules."""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import RedirectResponse

from app.i18n import he


def redirect(url: str, msg: str | None = None, anchor: str | None = None) -> RedirectResponse:
    """Post/Redirect/Get: 303 so a browser refresh never re-submits a form."""
    if msg:
        url += ("&" if "?" in url else "?") + f"msg={msg}"
    if anchor:
        url += f"#{anchor}"
    return RedirectResponse(url, status_code=303)


def flash(request: Request) -> str | None:
    """Only predefined messages can be shown (the query value is a key, never text)."""
    return he.FLASH.get(request.query_params.get("msg", ""))


def page_number(request: Request) -> int:
    raw = request.query_params.get("page", "1")
    return int(raw) if raw.isdigit() and 0 < len(raw) < 7 else 1
