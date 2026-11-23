"""Phase B service layer: lookups, attachments, invoices, payments, postpone, cancel, records."""

import datetime as dt
import io
import sqlite3

import pytest

from app.db.connection import transaction
from app.domain.errors import ValidationError
from app.services import attachments, invoices, lookups, obligations, payments, records
from app.services.common import NeedsConfirmation
from tests.conftest import JPG_BYTES, PDF_BYTES, PNG_BYTES
from tests.factories import seq

D = dt.date


def make_invoice(svc, amount=40000, supplier="Electric Co", due=D(2026, 12, 1), currency="EUR", file=None,
                 token=None, **extra):
    data = invoices.InvoiceInput(supplier_name=supplier, property_id=1, category_id=None, currency=currency,
                                 amount_minor=amount, due_date=due, **extra)
    with transaction(svc.conn):
        return invoices.create(svc.conn, svc.clock, svc.paths, data, staged_file=file, request_token=token)


def ob_of(svc, invoice_id):
    return invoices.obligations_of(svc.conn, invoice_id)[0]


def pay(svc, ob_id, amount, on=D(2026, 11, 10), method="bank_transfer", token=None, receipt=None, ref=None):
    with transaction(svc.conn):
        return payments.record(svc.conn, svc.clock, svc.paths, ob_id,
                               payments.PaymentInput(amount, on, method, ref), request_token=token, receipt=receipt)


# ====================================================================== lookups

def test_lookup_create_update_archive_restore(svc):
    c, clk = svc.conn, svc.clock
    pid = lookups.create(c, clk, "properties", "דירה בתל אביב", country="ישראל")
    lookups.update(c, clk, "properties", pid, "דירה – תל אביב", country="ישראל", notes="קומה 3")
    assert lookups.get(c, "properties", pid)["notes"] == "קומה 3"
    lookups.set_archived(c, clk, "properties", pid, True)
    assert pid not in [r["id"] for r in lookups.active(c, "properties")]
    assert pid in [r["id"] for r in lookups.list_all(c, "properties")]  # still listed, never deleted
    lookups.set_archived(c, clk, "properties", pid, False)
    assert pid in [r["id"] for r in lookups.active(c, "properties")]
    actions = [r["action"] for r in c.execute("SELECT action FROM audit_events WHERE entity_type='property'")]
    assert actions == ["create", "update", "archive", "unarchive"]


@pytest.mark.parametrize("dup", ["ACME Ltd", "acme ltd", "  ACME   Ltd "])
def test_lookup_duplicate_names_rejected(svc, dup):
    lookups.create(svc.conn, svc.clock, "suppliers", "ACME Ltd")
    with pytest.raises(ValidationError) as exc:
        lookups.create(svc.conn, svc.clock, "suppliers", dup)
    assert "כבר קיים" in exc.value.message


def test_archived_name_offers_restore(svc):
    sid = lookups.create(svc.conn, svc.clock, "categories", "חשמל")
    lookups.set_archived(svc.conn, svc.clock, "categories", sid, True)
    with pytest.raises(ValidationError) as exc:
        lookups.create(svc.conn, svc.clock, "categories", "חשמל")
    assert "בארכיון" in exc.value.message


def test_general_property_cannot_be_archived(svc):
    with pytest.raises(ValidationError):
        lookups.set_archived(svc.conn, svc.clock, "properties", 1, True)


def test_blank_name_rejected(svc):
    with pytest.raises(ValidationError):
        lookups.create(svc.conn, svc.clock, "suppliers", "   ")


def test_noop_update_does_not_touch_data(svc):
    sid = lookups.create(svc.conn, svc.clock, "suppliers", "Water Co", contact="03-1234567")
    before = seq(svc.conn)
    lookups.update(svc.conn, svc.clock, "suppliers", sid, "Water Co", contact="03-1234567")
    assert seq(svc.conn) == before


def test_supplier_resolved_or_created(svc):
    sid = lookups.create(svc.conn, svc.clock, "suppliers", "Gas Co")
    assert lookups.resolve_or_create_supplier(svc.conn, svc.clock, " gas co ") == sid
    new_id = lookups.resolve_or_create_supplier(svc.conn, svc.clock, "חברת המים")
    assert new_id != sid and lookups.get(svc.conn, "suppliers", new_id)["name"] == "חברת המים"


def test_archiving_never_changes_financial_records(svc):
    inv = make_invoice(svc, supplier="Old Supplier")
    ob = ob_of(svc, inv)
    pay(svc, ob["id"], 40000)
    sid = ob["supplier_id"]
    lookups.set_archived(svc.conn, svc.clock, "suppliers", sid, True)
    view = invoices.view(svc.conn, inv)
    assert view["summary"].state == "paid" and len(view["payments"]) == 1
    assert view["invoice"]["supplier_name"] == "Old Supplier" and view["invoice"]["supplier_archived"]
    assert records.obligations_tab(svc.conn, "paid").total == 1


# ====================================================================== attachments

@pytest.mark.parametrize("data, name, mime", [(PDF_BYTES, "a.pdf", "application/pdf"), (PNG_BYTES, "b.PNG", "image/png"),
                                              (JPG_BYTES, "c.jpeg", "image/jpeg"), (JPG_BYTES, "d.jpg", "image/jpeg")])
def test_stage_accepts_valid_types(svc, data, name, mime):
    staged = svc.stage(data, name)
    assert staged.mime == mime and staged.size_bytes == len(data)


@pytest.mark.parametrize("data, name", [
    (b"MZ\x90\x00executable", "invoice.pdf"),   # an EXE renamed to .pdf
    (PNG_BYTES, "image.pdf"),                    # content does not match extension
    (PDF_BYTES, "invoice.exe"),
    (PDF_BYTES, "invoice"),
    (PDF_BYTES, "invoice.html"),
    (b"", "empty.pdf"),
])
def test_stage_rejects_bad_files(svc, data, name):
    with pytest.raises(ValidationError):
        svc.stage(data, name)
    leftovers = [p for p in attachments.staging_dir(svc.paths).glob("*") if p.suffix == ".part"]
    assert leftovers == []


def test_stage_rejects_oversize(svc):
    with pytest.raises(ValidationError) as exc:
        attachments.stage_upload(svc.paths, io.BytesIO(PDF_BYTES + b"x" * 2000), "big.pdf", 1000)
    assert "גדול מדי" in exc.value.message


def test_original_name_cannot_inject_paths(svc):
    staged = svc.stage(PDF_BYTES, "..\\..\\Windows\\evil.pdf")
    assert staged.original_name == "evil.pdf"


@pytest.mark.parametrize("token", ["../../etc/passwd", "a" * 31, "G" * 32, "", None, "a" * 32])
def test_load_staged_rejects_bad_tokens(svc, token):
    assert attachments.load_staged(svc.paths, token) is None


def test_commit_stores_original_bytes_safely(svc):
    inv = make_invoice(svc, file=svc.stage(PDF_BYTES, "חשבונית מרץ.pdf"))
    row = svc.conn.execute("SELECT * FROM attachments WHERE invoice_id = ?", (inv,)).fetchone()
    assert row["stored_path"].startswith("invoices/2026/") and row["stored_path"].endswith(".pdf")
    assert row["original_name"] == "חשבונית מרץ.pdf"
    path = attachments.file_path(svc.paths, row)
    assert path.read_bytes() == PDF_BYTES  # stored unmodified
    assert attachments.verify_file(svc.paths, row)
    assert list(attachments.staging_dir(svc.paths).glob("*")) == []  # staging cleaned up


def test_failed_db_insert_puts_file_back(svc):
    staged = svc.stage()
    with pytest.raises(sqlite3.IntegrityError):
        with transaction(svc.conn):
            attachments.commit_staged(svc.conn, svc.paths, svc.clock, staged)  # no owner → CHECK fails
    assert attachments.load_staged(svc.paths, staged.token) is not None
    assert list((svc.paths.invoices).rglob("*.pdf")) == []


def test_replace_keeps_old_version(svc):
    inv = make_invoice(svc, file=svc.stage(PDF_BYTES, "v1.pdf"))
    old = svc.conn.execute("SELECT id FROM attachments WHERE invoice_id = ?", (inv,)).fetchone()[0]
    with transaction(svc.conn):
        new = invoices.add_document(svc.conn, svc.clock, svc.paths, inv, svc.stage(PDF_BYTES + b"v2", "v2.pdf"), old)
    rows = {r["id"]: r for r in svc.conn.execute("SELECT * FROM attachments WHERE invoice_id = ?", (inv,))}
    assert rows[old]["superseded_by"] == new and rows[new]["superseded_by"] is None
    assert attachments.verify_file(svc.paths, rows[old]) and attachments.verify_file(svc.paths, rows[new])
    with pytest.raises(ValidationError):
        with transaction(svc.conn):
            invoices.add_document(svc.conn, svc.clock, svc.paths, inv, svc.stage(), old)  # already replaced


def test_file_path_guard(svc):
    fake = {"stored_path": "invoices/../../outside.pdf"}
    with pytest.raises(Exception):
        attachments.file_path(svc.paths, fake)


# ====================================================================== invoices

def test_create_invoice_creates_one_obligation(svc):
    inv = make_invoice(svc, amount=120000, invoice_number="A-1", issue_date=D(2026, 11, 1))
    row = invoices.get_row(svc.conn, inv)
    obs = invoices.obligations_of(svc.conn, inv)
    assert row["total_minor"] == 120000 and len(obs) == 1
    assert obs[0]["amount_minor"] == 120000 and obs[0]["original_due_date"] == obs[0]["current_due_date"] == "2026-12-01"
    assert obs[0]["primary_state"] == "open" and obs[0]["outstanding_minor"] == 120000
    assert svc.conn.execute("SELECT action FROM audit_events WHERE entity_type='invoice'").fetchone()[0] == "create"


def test_create_without_attachment_then_add_later(svc):
    inv = make_invoice(svc)
    assert invoices.view(svc.conn, inv)["invoice_documents"] == []
    with transaction(svc.conn):
        invoices.add_document(svc.conn, svc.clock, svc.paths, inv, svc.stage())
    assert len(invoices.view(svc.conn, inv)["invoice_documents"]) == 1


def test_double_submit_token_creates_one_invoice(svc):
    a = make_invoice(svc, token="tok-1")
    b = make_invoice(svc, token="tok-1")
    assert a == b
    assert svc.conn.execute("SELECT COUNT(*) FROM invoices").fetchone()[0] == 1


@pytest.mark.parametrize("override, field", [
    ({"property_id": None}, "property_id"),
    ({"property_id": 999}, "property_id"),
    ({"currency": "GBP"}, "currency"),
    ({"currency": None}, "currency"),
    ({"amount_minor": None}, "amount"),
    ({"due_date": None}, "due_date"),
    ({"supplier_name": "  "}, "supplier"),
    ({"issue_date": D(2026, 11, 13)}, "issue_date"),       # future
    ({"received_date": D(2027, 1, 1)}, "received_date"),   # future
    ({"reminder_lead_days": 400}, "reminder_lead_days"),
])
def test_create_validation(svc, override, field):
    base = dict(supplier_name="X", property_id=1, category_id=None, currency="EUR", amount_minor=100, due_date=D(2026, 12, 1))
    base.update(override)
    with pytest.raises(ValidationError) as exc:
        with transaction(svc.conn):
            invoices.create(svc.conn, svc.clock, svc.paths, invoices.InvoiceInput(**base))
    assert exc.value.field == field
    assert svc.conn.execute("SELECT COUNT(*) FROM invoices").fetchone()[0] == 0


def test_archived_property_not_selectable_for_new_invoice(svc):
    pid = lookups.create(svc.conn, svc.clock, "properties", "Old flat")
    lookups.set_archived(svc.conn, svc.clock, "properties", pid, True)
    data = invoices.InvoiceInput("X", pid, None, "EUR", 100, D(2026, 12, 1))
    with pytest.raises(ValidationError):
        invoices.create(svc.conn, svc.clock, svc.paths, data)


def test_received_before_issue_needs_confirmation(svc):
    kw = dict(issue_date=D(2026, 11, 5), received_date=D(2026, 11, 1))
    with pytest.raises(NeedsConfirmation):
        make_invoice(svc, **kw)
    data = invoices.InvoiceInput("X", 1, None, "EUR", 100, D(2026, 12, 1), **kw)
    with transaction(svc.conn):
        assert invoices.create(svc.conn, svc.clock, svc.paths, data, confirmed=True)


def test_edit_invoice_amount_and_due_date(svc):
    inv = make_invoice(svc, amount=40000)
    ob = ob_of(svc, inv)
    pay(svc, ob["id"], 15000)
    data = invoices.InvoiceInput("Electric Co", 1, None, None, 45000, D(2026, 12, 20), invoice_number="N-9")
    with transaction(svc.conn):
        invoices.update(svc.conn, svc.clock, inv, data)
    ob = ob_of(svc, inv)
    assert invoices.get_row(svc.conn, inv)["total_minor"] == ob["amount_minor"] == 45000
    assert ob["outstanding_minor"] == 30000 and ob["original_due_date"] == "2026-12-01"
    assert ob["current_due_date"] == "2026-12-20"
    assert len(obligations.postponements(svc.conn, ob["id"])) == 1  # due-date change kept in history


def test_edit_amount_below_paid_rejected(svc):
    inv = make_invoice(svc, amount=40000)
    pay(svc, ob_of(svc, inv)["id"], 15000)
    data = invoices.InvoiceInput("Electric Co", 1, None, None, 14999, D(2026, 12, 1))
    with pytest.raises(ValidationError):
        with transaction(svc.conn):
            invoices.update(svc.conn, svc.clock, inv, data)
    assert invoices.get_row(svc.conn, inv)["total_minor"] == 40000


def test_edit_supplier_propagates_to_obligation(svc):
    inv = make_invoice(svc, supplier="Old Name Co")
    data = invoices.InvoiceInput("New Name Co", 1, None, None, 40000, D(2026, 12, 1))
    with transaction(svc.conn):
        invoices.update(svc.conn, svc.clock, inv, data)
    assert invoices.get_row(svc.conn, inv)["supplier_name"] == "New Name Co"
    assert ob_of(svc, inv)["supplier_id"] == invoices.get_row(svc.conn, inv)["supplier_id"]


# ====================================================================== payments

def test_partial_then_full_payment(svc):
    inv = make_invoice(svc, amount=40000)
    ob = ob_of(svc, inv)["id"]
    r1 = pay(svc, ob, 15000)
    assert not r1.now_paid_in_full
    assert ob_of(svc, inv)["outstanding_minor"] == 25000 and ob_of(svc, inv)["primary_state"] == "partial"
    r2 = pay(svc, ob, 25000, method="card", ref="TX-1")
    assert r2.now_paid_in_full and ob_of(svc, inv)["primary_state"] == "paid"
    assert invoices.view(svc.conn, inv)["summary"].state == "paid"


def test_payment_without_receipt_or_reference_is_fine(svc):
    inv = make_invoice(svc)
    r = pay(svc, ob_of(svc, inv)["id"], 100, method="cash")
    entry = payments.get(svc.conn, r.entry_id)
    assert entry["reference"] is None and entry["method"] == "cash"


def test_overpayment_message_shows_outstanding(svc):
    inv = make_invoice(svc, amount=40000)
    with pytest.raises(ValidationError) as exc:
        pay(svc, ob_of(svc, inv)["id"], 40001)
    assert "€400.00" in exc.value.message and exc.value.field == "amount"


def test_payment_date_in_future_rejected(svc):
    inv = make_invoice(svc)
    with pytest.raises(ValidationError) as exc:
        pay(svc, ob_of(svc, inv)["id"], 100, on=D(2026, 11, 13))
    assert exc.value.field == "paid_on"
    pay(svc, ob_of(svc, inv)["id"], 100, on=D(2026, 11, 12))  # today is fine


def test_invalid_method_rejected(svc):
    inv = make_invoice(svc)
    with pytest.raises(ValidationError):
        pay(svc, ob_of(svc, inv)["id"], 100, method="crypto")


def test_payment_replay_records_once(svc):
    inv = make_invoice(svc)
    ob = ob_of(svc, inv)["id"]
    first = pay(svc, ob, 100, token="pay-1")
    again = pay(svc, ob, 100, token="pay-1")
    assert again.already_recorded and again.entry_id == first.entry_id
    assert svc.conn.execute("SELECT COUNT(*) FROM payment_entries").fetchone()[0] == 1


def test_payment_with_receipt(svc):
    inv = make_invoice(svc)
    r = pay(svc, ob_of(svc, inv)["id"], 100, receipt=svc.stage(PNG_BYTES, "receipt.png"))
    row = svc.conn.execute("SELECT * FROM attachments WHERE payment_entry_id = ?", (r.entry_id,)).fetchone()
    assert row["kind"] == "receipt" and row["stored_path"].startswith("receipts/2026/")


def test_full_payment_resolves_manual_reminders(svc):
    inv = make_invoice(svc, amount=1000)
    ob = ob_of(svc, inv)["id"]
    svc.conn.execute("INSERT INTO reminders (obligation_id, remind_on) VALUES (?, '2026-11-12')", (ob,))
    pay(svc, ob, 500)
    assert svc.conn.execute("SELECT status FROM reminders").fetchone()[0] == "pending"  # partial: unchanged (D7)
    pay(svc, ob, 500)
    assert svc.conn.execute("SELECT status FROM reminders").fetchone()[0] == "handled"


def test_void_restores_balance_and_keeps_entry(svc):
    inv = make_invoice(svc, amount=40000)
    ob = ob_of(svc, inv)["id"]
    entry = pay(svc, ob, 40000).entry_id
    with transaction(svc.conn):
        payments.void(svc.conn, svc.clock, entry, "נרשם בטעות")
    assert ob_of(svc, inv)["outstanding_minor"] == 40000
    row = payments.get(svc.conn, entry)
    assert row["voided_at"] and row["void_reason"] == "נרשם בטעות" and row["amount_minor"] == 40000
    with pytest.raises(ValidationError):
        with transaction(svc.conn):
            payments.void(svc.conn, svc.clock, entry, "again")


def test_void_requires_reason(svc):
    inv = make_invoice(svc)
    entry = pay(svc, ob_of(svc, inv)["id"], 100).entry_id
    with pytest.raises(ValidationError):
        payments.void(svc.conn, svc.clock, entry, "  ")


def test_correction_replaces_wrong_amount(svc):
    inv = make_invoice(svc, amount=40000)
    ob = ob_of(svc, inv)["id"]
    wrong = pay(svc, ob, 4000).entry_id   # typed 40.00 instead of 400.00
    with transaction(svc.conn):
        new = payments.void(svc.conn, svc.clock, wrong, "סכום שגוי",
                            correction=payments.PaymentInput(40000, D(2026, 11, 10), "bank_transfer"))
    assert payments.get(svc.conn, new)["corrects_entry_id"] == wrong
    assert ob_of(svc, inv)["primary_state"] == "paid"


def test_failed_correction_rolls_back_the_void(svc):
    inv = make_invoice(svc, amount=40000)
    entry = pay(svc, ob_of(svc, inv)["id"], 10000).entry_id
    with pytest.raises(ValidationError):
        with transaction(svc.conn):
            payments.void(svc.conn, svc.clock, entry, "x",
                          correction=payments.PaymentInput(50000, D(2026, 11, 10), "cash"))  # overpay
    assert payments.get(svc.conn, entry)["voided_at"] is None


# ====================================================================== postpone

def test_postpone_changes_only_current_due_date(svc):
    inv = make_invoice(svc, amount=40000)
    ob = ob_of(svc, inv)
    pay(svc, ob["id"], 15000)
    payments_before = [dict(r) for r in svc.conn.execute("SELECT * FROM payment_entries")]
    with transaction(svc.conn):
        obligations.change_due_date(svc.conn, svc.clock, ob["id"], D(2027, 1, 15), "בקשת הספק")
    after = ob_of(svc, inv)
    assert after["current_due_date"] == "2027-01-15" and after["original_due_date"] == "2026-12-01"
    assert after["paid_minor"] == 15000 and after["outstanding_minor"] == 25000
    assert [dict(r) for r in svc.conn.execute("SELECT * FROM payment_entries")] == payments_before
    pp = obligations.postponements(svc.conn, ob["id"])
    assert (pp[0]["old_due_date"], pp[0]["new_due_date"], pp[0]["reason"]) == ("2026-12-01", "2027-01-15", "בקשת הספק")


@pytest.mark.parametrize("new", [D(2026, 12, 1), D(2026, 11, 30)])
def test_postpone_must_be_later(svc, new):
    inv = make_invoice(svc)
    with pytest.raises(ValidationError):
        obligations.change_due_date(svc.conn, svc.clock, ob_of(svc, inv)["id"], new)


def test_cannot_postpone_paid_obligation(svc):
    inv = make_invoice(svc, amount=100)
    pay(svc, ob_of(svc, inv)["id"], 100)
    with pytest.raises(ValidationError):
        obligations.change_due_date(svc.conn, svc.clock, ob_of(svc, inv)["id"], D(2027, 1, 1))


def test_postpone_leaves_manual_reminders_by_default(svc):
    inv = make_invoice(svc)
    ob = ob_of(svc, inv)["id"]
    svc.conn.execute("INSERT INTO reminders (obligation_id, remind_on) VALUES (?, '2026-11-25')", (ob,))
    with transaction(svc.conn):
        obligations.change_due_date(svc.conn, svc.clock, ob, D(2026, 12, 11))
    assert svc.conn.execute("SELECT remind_on FROM reminders").fetchone()[0] == "2026-11-25"
    assert obligations.postponements(svc.conn, ob)[0]["moved_manual_reminders"] == 0


def test_postpone_moves_pending_reminders_only_when_asked(svc):
    inv = make_invoice(svc)
    ob = ob_of(svc, inv)["id"]
    svc.conn.execute("INSERT INTO reminders (obligation_id, remind_on) VALUES (?, '2026-11-25')", (ob,))
    svc.conn.execute("INSERT INTO reminders (obligation_id, remind_on, status, resolved_at) "
                     "VALUES (?, '2026-11-20', 'handled', '2026-11-12 09:00:00')", (ob,))
    with transaction(svc.conn):
        obligations.change_due_date(svc.conn, svc.clock, ob, D(2026, 12, 11), move_manual_reminders=True)
    rows = svc.conn.execute("SELECT status, remind_on FROM reminders ORDER BY id").fetchall()
    assert [tuple(r) for r in rows] == [("pending", "2026-12-05"), ("handled", "2026-11-20")]


# ====================================================================== cancel

def test_cancel_after_partial_payment(svc):
    inv = make_invoice(svc, amount=40000)
    ob = ob_of(svc, inv)["id"]
    pay(svc, ob, 15000)
    svc.conn.execute("INSERT INTO reminders (obligation_id, remind_on) VALUES (?, '2026-11-25')", (ob,))
    with transaction(svc.conn):
        invoices.cancel(svc.conn, svc.clock, inv, "הספק ויתר על היתרה")
    after = ob_of(svc, inv)
    assert (after["paid_minor"], after["canceled_minor"], after["outstanding_minor"]) == (15000, 25000, 0)
    assert after["primary_state"] == "canceled" and after["closed_paid_minor"] == 15000
    summary = invoices.view(svc.conn, inv)["summary"]
    assert summary.state == "closed_partly_canceled" and not summary.is_paid_in_full
    assert svc.conn.execute("SELECT status FROM reminders").fetchone()[0] == "cleared"
    assert records.obligations_tab(svc.conn, "paid").total == 0
    assert records.obligations_tab(svc.conn, "open").total == 0
    assert records.obligations_tab(svc.conn, "all").total == 1


def test_cancel_requires_reason_and_open_balance(svc):
    inv = make_invoice(svc, amount=100)
    with pytest.raises(ValidationError):
        invoices.cancel(svc.conn, svc.clock, inv, "")
    pay(svc, ob_of(svc, inv)["id"], 100)
    with pytest.raises(ValidationError):
        invoices.cancel(svc.conn, svc.clock, inv, "nothing to cancel")


def test_no_payment_after_cancel(svc):
    inv = make_invoice(svc)
    with transaction(svc.conn):
        invoices.cancel(svc.conn, svc.clock, inv, "x")
    with pytest.raises(ValidationError):
        pay(svc, ob_of(svc, inv)["id"], 1)


def test_void_after_cancel_increases_canceled_amount(svc):
    inv = make_invoice(svc, amount=40000)
    entry = pay(svc, ob_of(svc, inv)["id"], 15000).entry_id
    with transaction(svc.conn):
        invoices.cancel(svc.conn, svc.clock, inv, "x")
    with transaction(svc.conn):
        payments.void(svc.conn, svc.clock, entry, "refunded")
    ob = ob_of(svc, inv)
    assert (ob["paid_minor"], ob["canceled_minor"]) == (0, 40000)
    assert invoices.view(svc.conn, inv)["summary"].state == "canceled"


# ====================================================================== records

def test_tabs_and_ledger(svc):
    open_inv = make_invoice(svc, amount=100, due=D(2026, 12, 5))
    paid_inv = make_invoice(svc, amount=200, supplier="Paid Co")
    pay(svc, ob_of(svc, paid_inv)["id"], 200, on=D(2025, 3, 1))  # paid long ago
    canceled_inv = make_invoice(svc, amount=300, supplier="Canceled Co")
    with transaction(svc.conn):
        invoices.cancel(svc.conn, svc.clock, canceled_inv, "x")
    ids = lambda tab: {r["invoice_id"] for r in records.obligations_tab(svc.conn, tab).rows}
    assert ids("open") == {open_inv}
    assert ids("paid") == {paid_inv}
    assert ids("all") == {open_inv, paid_inv, canceled_inv}
    assert records.tab_counts(svc.conn) == {"open": 1, "paid": 1, "all": 3}
    ledger = records.payment_ledger(svc.conn).rows
    assert [r["paid_on"] for r in ledger] == ["2025-03-01"]


def test_change_log_links_events_to_invoice(svc):
    inv = make_invoice(svc, file=svc.stage())
    pay(svc, ob_of(svc, inv)["id"], 100)
    log = records.change_log(svc.conn).rows
    assert {r["invoice_id"] for r in log if r["entity_type"] in ("invoice", "obligation", "payment", "attachment")} == {inv}


def test_pagination(svc, monkeypatch):
    monkeypatch.setattr(records, "PAGE_SIZE", 2)
    for i in range(5):
        make_invoice(svc, amount=100 + i, supplier=f"S{i}")
    p1, p3 = records.obligations_tab(svc.conn, "all", 1), records.obligations_tab(svc.conn, "all", 3)
    assert (p1.pages, len(p1.rows), len(p3.rows), p3.total) == (3, 2, 1, 5)
    assert records.obligations_tab(svc.conn, "all", 99).page == 3
