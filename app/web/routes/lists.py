"""All Payments (Open / Paid / All), History (payments ledger, change log) and document viewing."""

from __future__ import annotations

import sqlite3
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, HTMLResponse

from app.i18n import he
from app.services import attachments, records
from app.web.deps import get_conn
from app.web.routes.common import page_number

router = APIRouter()


@router.get("/payments", response_class=HTMLResponse)
def payments_page(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    tab = request.query_params.get("tab", "open")
    tab = tab if tab in records.TABS else "open"
    return request.app.state.render(
        request, "payments_list.html", page_title=he.PAGE_TITLES["/payments"], tab=tab,
        page=records.obligations_tab(conn, tab, page_number(request)), counts=records.tab_counts(conn))


@router.get("/history", response_class=HTMLResponse)
def history_page(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    view = request.query_params.get("view", "payments")
    view = view if view in ("payments", "changes") else "payments"
    page = (records.payment_ledger if view == "payments" else records.change_log)(conn, page_number(request))
    return request.app.state.render(request, "history.html", page_title=he.PAGE_TITLES["/history"],
                                    view=view, page=page)


@router.get("/attachments/{att_id}")
def view_attachment(att_id: int, request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    """Serve a stored document by its database id only — never by a path from the request."""
    row = attachments.get(conn, att_id)
    path = attachments.file_path(request.app.state.paths, row)
    name = row["original_name"]
    ascii_name = name.encode("ascii", "ignore").decode() or f"document.{row['stored_path'].rsplit('.', 1)[-1]}"
    ascii_name = ascii_name.replace('"', "")
    return FileResponse(path, media_type=row["mime"], headers={
        "Content-Disposition": f"inline; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}",
        "Cache-Control": "no-store",
    })
