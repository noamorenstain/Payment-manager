"""Invoices: create, view (details page with dialogs), edit, cancel, documents."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from app.db.connection import transaction
from app.db.errors import hebrew_message
from app.domain import dates as d
from app.domain import money as m
from app.domain.errors import ValidationError
from app.i18n import he
from app.services import attachments, invoices, lookups
from app.services.common import NeedsConfirmation
from app.web.deps import get_conn
from app.web.forms import FormReader, new_token, stage_file
from app.web.routes.common import flash, redirect

router = APIRouter()


# ------------------------------------------------------------------ shared rendering

def _choices(conn, keep_property=None, keep_category=None):
    props = [p for p in lookups.list_all(conn, "properties") if p["archived_at"] is None or p["id"] == keep_property]
    cats = [c for c in lookups.list_all(conn, "categories") if c["archived_at"] is None or c["id"] == keep_category]
    return {
        "properties": props,
        "categories": cats,
        "suppliers": lookups.active(conn, "suppliers"),
        "currencies": conn.execute("SELECT * FROM currencies WHERE active = 1 ORDER BY code = 'ILS' DESC, code"
                                   ).fetchall(),
    }


def render_form(request: Request, conn, *, mode: str, values: dict, errors: dict | None = None,
                warnings: list | None = None, staged=None, invoice=None, status: int = 200,
                single_obligation=None):
    title = he.PAGE_TITLES["/invoices/new"] if mode == "new" else "עריכת חשבונית"
    return request.app.state.render(
        request, "invoice_form.html", status_code=status, page_title=title, mode=mode, values=values,
        errors=errors or {}, warnings=warnings or [], staged=staged, invoice=invoice,
        single_obligation=single_obligation, accept=attachments.ACCEPT_ATTR,
        **_choices(conn, invoice["property_id"] if invoice else None, invoice["category_id"] if invoice else None))


def render_invoice(request: Request, conn, invoice_id: int, *, dialog: dict | None = None, status: int = 200):
    data = invoices.view(conn, invoice_id)
    any_open = any(o["lifecycle"] == "active" and (o["amount_minor"] is None or o["outstanding_minor"] > 0)
                   for o in data["obligations"])
    return request.app.state.render(
        request, "invoice_detail.html", status_code=status, any_open=any_open,
        page_title=f"חשבונית – {data['invoice']['supplier_name']}",
        flash=flash(request), dialog=dialog or {}, accept=attachments.ACCEPT_ATTR,
        today_he=d.format_he(request.app.state.clock.today()), new_token=new_token, to_input=m.to_input, **data)


def _read_invoice(reader: FormReader, *, editing: bool) -> invoices.InvoiceInput:
    return invoices.InvoiceInput(
        supplier_name=reader.text("supplier"),
        property_id=reader.int_id("property_id", required=True, message=he.PROPERTY_REQUIRED),
        category_id=reader.int_id("category_id", message=he.CATEGORY_INVALID),
        currency=None if editing else reader.text("currency"),
        amount_minor=reader.amount("amount", required=not editing),
        due_date=reader.date("due_date", required=not editing),
        invoice_number=reader.text("invoice_number"),
        issue_date=reader.date("issue_date", required=False),
        received_date=reader.date("received_date", required=False),
        notes=reader.text("notes"),
        reminder_lead_days=reader.int_range("reminder_lead_days", 0, 365, he.LEAD_DAYS_RANGE),
    )


# ------------------------------------------------------------------ new

@router.get("/invoices/new", response_class=HTMLResponse)
def new_invoice(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    default_currency = "ILS"
    return render_form(request, conn, mode="new",
                       values={"request_token": new_token(), "currency": default_currency,
                               "property_id": str(conn.execute(
                                   "SELECT id FROM properties WHERE is_general = 1").fetchone()[0])})


@router.post("/invoices/new")
async def create_invoice(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    state = request.app.state
    reader = FormReader(await request.form())
    data = _read_invoice(reader, editing=False)
    if not reader.text("supplier"):
        reader.errors.setdefault("supplier", he.SUPPLIER_REQUIRED)
    staged = stage_file(reader, state.paths, attachments.max_upload_bytes(conn))
    values = {**reader.values, "file_token": staged.token if staged else ""}
    if reader.errors:
        return render_form(request, conn, mode="new", values=values, errors=reader.errors, staged=staged, status=422)
    try:
        with transaction(conn):
            invoice_id = invoices.create(conn, state.clock, state.paths, data, staged_file=staged,
                                         request_token=reader.text("request_token"),
                                         confirmed=reader.checkbox("confirm_warnings"))
    except NeedsConfirmation as exc:
        return render_form(request, conn, mode="new", values=values, warnings=exc.warnings, staged=staged, status=422)
    except ValidationError as exc:
        reader.add(exc)
        return render_form(request, conn, mode="new", values=values, errors=reader.errors, staged=staged, status=422)
    except sqlite3.IntegrityError as exc:
        reader.errors["_form"] = hebrew_message(exc)
        return render_form(request, conn, mode="new", values=values, errors=reader.errors, staged=staged, status=422)
    return redirect(f"/invoices/{invoice_id}", "invoice_created")


# ------------------------------------------------------------------ view

@router.get("/invoices/{invoice_id}", response_class=HTMLResponse)
def invoice_page(invoice_id: int, request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    return render_invoice(request, conn, invoice_id)


# ------------------------------------------------------------------ edit

def _edit_values(inv, single) -> dict:
    values = {
        "supplier": inv["supplier_name"], "property_id": str(inv["property_id"]),
        "category_id": str(inv["category_id"] or ""), "invoice_number": inv["invoice_number"] or "",
        "issue_date": d.format_he(d.from_iso(inv["issue_date"])),
        "received_date": d.format_he(d.from_iso(inv["received_date"])), "notes": inv["notes"] or "",
    }
    if single is not None:
        values.update(amount=m.to_input(single["amount_minor"]),
                      due_date=d.format_he(d.from_iso(single["current_due_date"])),
                      reminder_lead_days="" if single["reminder_lead_days"] is None else str(single["reminder_lead_days"]))
    return values


def _single(conn, invoice_id):
    obs = invoices.obligations_of(conn, invoice_id)
    return obs[0] if len(obs) == 1 and obs[0]["lifecycle"] == "active" else None


@router.get("/invoices/{invoice_id}/edit", response_class=HTMLResponse)
def edit_invoice_page(invoice_id: int, request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    inv = invoices.get_row(conn, invoice_id)
    single = _single(conn, invoice_id)
    return render_form(request, conn, mode="edit", values=_edit_values(inv, single), invoice=inv,
                       single_obligation=single)


@router.post("/invoices/{invoice_id}/edit")
async def edit_invoice(invoice_id: int, request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    state = request.app.state
    inv = invoices.get_row(conn, invoice_id)
    single = _single(conn, invoice_id)
    reader = FormReader(await request.form())
    data = _read_invoice(reader, editing=True)
    if not reader.text("supplier"):
        reader.errors.setdefault("supplier", he.SUPPLIER_REQUIRED)
    if single is None:
        data.amount_minor, data.due_date = None, None
        data.reminder_lead_days = None
    else:
        if data.amount_minor is None and "amount" not in reader.errors:
            reader.errors["amount"] = he.AMOUNT_REQUIRED
        if data.due_date is None and "due_date" not in reader.errors:
            reader.errors["due_date"] = he.DATE_REQUIRED
    kwargs = dict(mode="edit", values=reader.values, invoice=inv, single_obligation=single, status=422)
    if reader.errors:
        return render_form(request, conn, errors=reader.errors, **kwargs)
    try:
        with transaction(conn):
            invoices.update(conn, state.clock, invoice_id, data, confirmed=reader.checkbox("confirm_warnings"),
                            due_change_reason=reader.text("due_change_reason"))
    except NeedsConfirmation as exc:
        return render_form(request, conn, warnings=exc.warnings, **kwargs)
    except ValidationError as exc:
        reader.add(exc)
        return render_form(request, conn, errors=reader.errors, **kwargs)
    except sqlite3.IntegrityError as exc:
        reader.errors["_form"] = hebrew_message(exc)
        return render_form(request, conn, errors=reader.errors, **kwargs)
    return redirect(f"/invoices/{invoice_id}", "invoice_updated")


# ------------------------------------------------------------------ cancel & documents

@router.post("/invoices/{invoice_id}/cancel")
async def cancel_invoice(invoice_id: int, request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    reader = FormReader(await request.form())
    try:
        with transaction(conn):
            invoices.cancel(conn, request.app.state.clock, invoice_id, reader.text("reason"))
    except ValidationError as exc:
        reader.add(exc, "reason")
        return render_invoice(request, conn, invoice_id, status=422,
                              dialog={"name": "cancel-invoice", "errors": reader.errors, "values": reader.values})
    return redirect(f"/invoices/{invoice_id}", "invoice_canceled")


@router.post("/invoices/{invoice_id}/documents")
async def add_document(invoice_id: int, request: Request, conn: sqlite3.Connection = Depends(get_conn)):
    state = request.app.state
    invoices.get_row(conn, invoice_id)
    reader = FormReader(await request.form())
    replaces = reader.int_id("replaces_id")
    staged = stage_file(reader, state.paths, attachments.max_upload_bytes(conn))
    if staged is None and "file" not in reader.errors:
        reader.errors["file"] = he.FILE_REQUIRED
    if not reader.errors:
        try:
            with transaction(conn):
                invoices.add_document(conn, state.clock, state.paths, invoice_id, staged, replaces)
        except ValidationError as exc:
            reader.add(exc, "file")
    if reader.errors:
        return render_invoice(request, conn, invoice_id, status=422,
                              dialog={"name": "document", "errors": reader.errors, "values": reader.values})
    return redirect(f"/invoices/{invoice_id}", "document_replaced" if replaces else "document_added", "documents")
