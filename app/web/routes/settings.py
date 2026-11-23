"""Settings: properties, suppliers and categories (add / edit / archive / restore)."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from app.db.connection import transaction
from app.domain.errors import ValidationError
from app.i18n import he
from app.services import lookups
from app.services.common import NotFound
from app.web.deps import get_conn
from app.web.forms import FormReader
from app.web.routes.common import flash, redirect

router = APIRouter()
KINDS = tuple(lookups.SPECS)

FIELD_LABELS = {
    "name": "שם", "country": "מדינה", "notes": "הערות", "contact": "פרטי קשר", "customer_number": "מספר לקוח",
}


def _items(conn):
    return {kind: [dict(r, usage=lookups.usage_count(conn, kind, r["id"])) for r in lookups.list_all(conn, kind)]
            for kind in KINDS}


def _render(request: Request, conn, status=200, errors=None, values=None, open_kind=None):
    return request.app.state.render(
        request, "settings.html", status_code=status, page_title=he.PAGE_TITLES["/settings"],
        items=_items(conn), kinds=KINDS, specs=lookups.SPECS, labels=FIELD_LABELS,
        errors=errors or {}, values=values or {}, open_kind=open_kind, flash=flash(request))


@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    return _render(request, conn)


@router.post("/settings/{kind}")
async def create_item(kind: str, request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    if kind not in KINDS:
        raise NotFound(kind)
    reader = FormReader(await request.form())
    fields = {f: reader.text(f) for f in lookups.SPECS[kind].fields}
    try:
        with transaction(conn):
            lookups.create(conn, request.app.state.clock, kind, reader.text("name"), **fields)
    except ValidationError as exc:
        reader.add(exc)
        return _render(request, conn, 422, errors={kind: reader.errors}, values={kind: reader.values},
                       open_kind=kind)
    return redirect("/settings", "lookup_created", kind)


@router.get("/settings/{kind}/{item_id}/edit", response_class=HTMLResponse)
def edit_page(kind: str, item_id: int, request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    item = lookups.get(conn, kind, item_id)
    return request.app.state.render(
        request, "lookup_edit.html", page_title=f"עריכת {he.LOOKUP_SINGULAR[kind]}", kind=kind, item=item,
        spec=lookups.SPECS[kind], labels=FIELD_LABELS, values=dict(item), errors={},
        usage=lookups.usage_count(conn, kind, item_id))


@router.post("/settings/{kind}/{item_id}/edit")
async def edit_item(kind: str, item_id: int, request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    item = lookups.get(conn, kind, item_id)
    reader = FormReader(await request.form())
    fields = {f: reader.text(f) for f in lookups.SPECS[kind].fields}
    try:
        with transaction(conn):
            lookups.update(conn, request.app.state.clock, kind, item_id, reader.text("name"), **fields)
    except ValidationError as exc:
        reader.add(exc)
        return request.app.state.render(
            request, "lookup_edit.html", status_code=422, page_title=f"עריכת {he.LOOKUP_SINGULAR[kind]}",
            kind=kind, item=item, spec=lookups.SPECS[kind], labels=FIELD_LABELS, values=reader.values,
            errors=reader.errors, usage=lookups.usage_count(conn, kind, item_id))
    return redirect("/settings", "lookup_updated", kind)


@router.post("/settings/{kind}/{item_id}/{action}")
async def archive_item(kind: str, item_id: int, action: str, request: Request,
                       conn: sqlite3.Connection = Depends(get_conn)):
    if action not in ("archive", "unarchive"):
        raise NotFound(action)
    try:
        with transaction(conn):
            lookups.set_archived(conn, request.app.state.clock, kind, item_id, action == "archive")
    except ValidationError as exc:
        return _render(request, conn, 422, errors={kind: {"_form": exc.message}}, open_kind=kind)
    return redirect("/settings", "lookup_archived" if action == "archive" else "lookup_unarchived", kind)
