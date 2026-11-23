"""Phase B through HTTP: forms, uploads, dialogs, lists, Hebrew errors, PRG redirects."""

import html
import re

import pytest

from tests.conftest import PDF_BYTES, PNG_BYTES


def new_invoice(web, follow=False, file=None, **overrides):
    form = web.get("/invoices/new").text
    token = re.search(r'name="request_token" value="([0-9a-f]+)"', form).group(1)
    data = {"supplier": "חברת החשמל", "property_id": "1", "currency": "ILS", "amount": "1,250.40",
            "due_date": "01/12/2026", "invoice_number": "INV-2026-11", "request_token": token}
    data.update(overrides)
    files = {"file": file} if file else None
    return web.post("/invoices/new", data, files=files, follow=follow)


def created_id(response) -> int:
    assert response.status_code == 303, response.text[:500]
    return int(re.search(r"/invoices/(\d+)", response.headers["location"]).group(1))


def ob_id(web, invoice_id) -> int:
    return int(re.search(r'id="ob-(\d+)"', web.get(f"/invoices/{invoice_id}").text).group(1))


def pay_token(html, ob):
    return re.search(rf'action="/obligations/{ob}/payments".*?name="request_token" value="([0-9a-f]+)"',
                     html, re.S).group(1)


# ====================================================================== settings

def test_settings_add_edit_archive(web):
    r = web.post("/settings/properties", {"name": "Villa Nice", "country": "צרפת"})
    assert r.status_code == 303 and r.headers["location"].startswith("/settings?msg=lookup_created")
    page = web.get("/settings").text
    assert "Villa Nice" in page and "צרפת" in page
    pid = int(re.search(r"/settings/properties/(\d+)/edit", page).group(1))
    assert web.post(f"/settings/properties/{pid}/edit", {"name": "Villa Nice 2", "country": "צרפת"}).status_code == 303
    assert web.post(f"/settings/properties/{pid}/archive").status_code == 303
    page = web.get("/settings").text
    assert "Villa Nice 2" in page and "שחזור" in page


def test_settings_duplicate_is_hebrew_422(web):
    web.post("/settings/categories", {"name": "ארנונה"})
    r = web.post("/settings/categories", {"name": "ארנונה"})
    assert r.status_code == 422 and "כבר קיים" in r.text


def test_settings_unknown_kind_404(web):
    assert web.post("/settings/users", {"name": "x"}).status_code == 404


# ====================================================================== invoice creation

def test_new_invoice_form_renders(web):
    html = web.get("/invoices/new").text
    for field in ("supplier", "property_id", "currency", "amount", "due_date", "invoice_number", "file"):
        assert f'name="{field}"' in html
    assert 'type="date"' not in html  # custom DD/MM/YYYY input, never the locale-dependent native one
    assert "הוצאה כללית" in html


def test_create_invoice_with_pdf_and_view_document(web):
    inv = created_id(new_invoice(web, file=("חשבונית.pdf", PDF_BYTES, "application/pdf")))
    page = web.get(f"/invoices/{inv}?msg=invoice_created").text
    assert "החשבונית נשמרה." in page
    assert "₪1,250.40" in page and "INV-2026-11" in page and "חברת החשמל" in page
    att = int(re.search(r'href="/attachments/(\d+)"', page).group(1))
    doc = web.get(f"/attachments/{att}")
    assert doc.status_code == 200 and doc.content == PDF_BYTES
    assert doc.headers["content-type"] == "application/pdf"
    assert doc.headers["content-disposition"].startswith("inline;")
    assert doc.headers["x-content-type-options"] == "nosniff"


@pytest.mark.parametrize("field, value, message", [
    ("due_date", "31/02/2026", "תאריך לא קיים: 31/02/2026"),
    ("due_date", "2026-12-01", "DD/MM/YYYY"),
    ("amount", "12.345", "שתי ספרות"),
    ("amount", "0", "גדול מאפס"),
    ("amount", "-5", "חיובי"),
    ("supplier", "", "ספק"),
    ("issue_date", "13/11/2026", "עתידי"),
])
def test_invalid_input_shows_hebrew_error_and_saves_nothing(web, field, value, message):
    r = new_invoice(web, **{field: value})
    assert r.status_code == 422
    assert message in r.text
    with web.conn() as c:
        assert c.execute("SELECT COUNT(*) FROM invoices").fetchone()[0] == 0


def test_uploaded_file_is_kept_across_a_validation_error(web):
    r = new_invoice(web, due_date="31/02/2026", file=("bill.pdf", PDF_BYTES, "application/pdf"))
    assert r.status_code == 422 and "bill.pdf" in r.text
    token = re.search(r'name="file_token" value="([0-9a-f]{32})"', r.text).group(1)
    req = re.search(r'name="request_token" value="([0-9a-f]+)"', r.text).group(1)
    r2 = web.post("/invoices/new", {"supplier": "חברת החשמל", "property_id": "1", "currency": "ILS",
                                    "amount": "100", "due_date": "28/02/2026", "request_token": req,
                                    "file_token": token})
    inv = created_id(r2)
    assert "bill.pdf" in web.get(f"/invoices/{inv}").text


def test_bad_file_rejected_with_hebrew_message(web):
    r = new_invoice(web, file=("fake.pdf", b"MZ\x90\x00", "application/pdf"))
    assert r.status_code == 422 and "תוכן הקובץ" in r.text


def test_double_submitted_invoice_form_creates_one(web):
    form = web.get("/invoices/new").text
    token = re.search(r'name="request_token" value="([0-9a-f]+)"', form).group(1)
    data = {"supplier": "X", "property_id": "1", "currency": "EUR", "amount": "5", "due_date": "01/12/2026",
            "request_token": token}
    a, b = web.post("/invoices/new", data), web.post("/invoices/new", data)
    assert created_id(a) == created_id(b)


def test_warning_requires_confirmation(web):
    r = new_invoice(web, issue_date="05/11/2026", received_date="01/11/2026")
    assert r.status_code == 422 and "תאריך הקבלה מוקדם" in r.text and 'name="confirm_warnings"' in r.text
    inv = created_id(new_invoice(web, issue_date="05/11/2026", received_date="01/11/2026", confirm_warnings="1"))
    assert inv


def test_edit_invoice(web):
    inv = created_id(new_invoice(web))
    assert "1250.40" in web.get(f"/invoices/{inv}/edit").text
    r = web.post(f"/invoices/{inv}/edit", {"supplier": "חברת החשמל", "property_id": "1", "amount": "1300",
                                          "due_date": "15/12/2026", "invoice_number": "INV-X",
                                          "due_change_reason": "תיקון מועד"})
    assert r.status_code == 303
    page = web.get(f"/invoices/{inv}").text
    assert "₪1,300.00" in page and "INV-X" in page and "15/12/2026" in page and "תיקון מועד" in page


# ====================================================================== payments & dialogs

def test_partial_payment_then_full(web):
    inv = created_id(new_invoice(web, amount="400"))
    ob = ob_id(web, inv)
    html = web.get(f"/invoices/{inv}").text
    r = web.post(f"/obligations/{ob}/payments", {"amount": "150", "paid_on": "10/11/2026", "method": "bank_transfer",
                                                "request_token": pay_token(html, ob)})
    assert r.status_code == 303 and "payment_recorded" in r.headers["location"]
    page = web.get(f"/invoices/{inv}").text
    assert "שולם חלקית" in page and "₪250.00" in page
    html = page
    r = web.post(f"/obligations/{ob}/payments", {"amount": "250", "paid_on": "12/11/2026", "method": "card",
                                                "reference": "AUTH-77", "request_token": pay_token(html, ob)},
                 files={"file": ("receipt.png", PNG_BYTES, "image/png")})
    assert "payment_recorded_full" in r.headers["location"]
    page = web.get(f"/invoices/{inv}").text
    assert "שולמה במלואה" in page and "AUTH-77" in page and "receipt.png" in page


def test_overpayment_reopens_dialog_with_hebrew_error(web):
    inv = created_id(new_invoice(web, amount="400"))
    ob = ob_id(web, inv)
    r = web.post(f"/obligations/{ob}/payments", {"amount": "400.01", "paid_on": "10/11/2026",
                                                "method": "cash", "request_token": "a" * 32})
    assert r.status_code == 422
    assert "גבוה מהיתרה" in r.text and "₪400.00" in r.text
    assert f'id="dlg-pay-{ob}" data-auto-open' in r.text
    with web.conn() as c:
        assert c.execute("SELECT COUNT(*) FROM payment_entries").fetchone()[0] == 0


def test_payment_double_submit_records_once(web):
    inv = created_id(new_invoice(web, amount="400"))
    ob = ob_id(web, inv)
    data = {"amount": "100", "paid_on": "10/11/2026", "method": "cash", "request_token": "b" * 32}
    web.post(f"/obligations/{ob}/payments", data)
    second = web.post(f"/obligations/{ob}/payments", data)
    assert "payment_already_recorded" in second.headers["location"]
    with web.conn() as c:
        assert c.execute("SELECT COUNT(*) FROM payment_entries").fetchone()[0] == 1


def test_postpone_dialog(web):
    inv = created_id(new_invoice(web))
    ob = ob_id(web, inv)
    assert web.post(f"/obligations/{ob}/postpone", {"new_due_date": "15/01/2027", "reason": "בקשת הספק"}).status_code == 303
    page = web.get(f"/invoices/{inv}").text
    assert "היסטוריית מועדים" in page and "15/01/2027" in page and "01/12/2026" in page and "בקשת הספק" in page
    bad = web.post(f"/obligations/{ob}/postpone", {"new_due_date": "01/01/2027"})
    assert bad.status_code == 422 and "מאוחר" in bad.text


def test_postpone_checkbox_absent_without_reminders_and_unchecked_with_them(web):
    inv = created_id(new_invoice(web))
    ob = ob_id(web, inv)
    assert 'name="move_reminders"' not in web.get(f"/invoices/{inv}").text
    with web.conn() as c:
        c.execute("INSERT INTO reminders (obligation_id, remind_on) VALUES (?, '2026-11-20')", (ob,))
    html = web.get(f"/invoices/{inv}").text
    box = re.search(r'<input type="checkbox" name="move_reminders"[^>]*>', html).group(0)
    assert "checked" not in box


def test_cancel_and_void_flows(web):
    inv = created_id(new_invoice(web, amount="400"))
    ob = ob_id(web, inv)
    web.post(f"/obligations/{ob}/payments", {"amount": "150", "paid_on": "10/11/2026", "method": "cash",
                                            "request_token": "c" * 32})
    assert web.post(f"/obligations/{ob}/cancel", {"reason": ""}).status_code == 422
    assert web.post(f"/obligations/{ob}/cancel", {"reason": "הסכם פשרה"}).status_code == 303
    page = web.get(f"/invoices/{inv}").text
    assert "נסגרה – חלקה בוטל" in page and "שולם חלקית לפני ביטול" in page and "₪250.00" in page
    entry = int(re.search(r"/payment-entries/(\d+)/void", page).group(1))
    assert web.post(f"/payment-entries/{entry}/void", {"void_reason": "החזר"}).status_code == 303
    page = web.get(f"/invoices/{inv}").text
    assert "row-voided" in page and "החזר" in page


def test_void_with_correction(web):
    inv = created_id(new_invoice(web, amount="400"))
    ob = ob_id(web, inv)
    web.post(f"/obligations/{ob}/payments", {"amount": "40", "paid_on": "10/11/2026", "method": "cash",
                                            "request_token": "d" * 32})
    with web.conn() as c:
        entry = c.execute("SELECT id FROM payment_entries").fetchone()[0]
    r = web.post(f"/payment-entries/{entry}/void", {"void_reason": "סכום שגוי", "correct": "1", "amount": "400",
                                                   "paid_on": "10/11/2026", "method": "bank_transfer",
                                                   "request_token": "e" * 32})
    assert "payment_corrected" in r.headers["location"]
    assert "שולמה במלואה" in web.get(f"/invoices/{inv}").text


def test_add_and_replace_document(web):
    inv = created_id(new_invoice(web))
    assert web.post(f"/invoices/{inv}/documents", {}).status_code == 422  # no file chosen
    assert web.post(f"/invoices/{inv}/documents", {}, files={"file": ("a.pdf", PDF_BYTES, "application/pdf")}
                    ).status_code == 303
    with web.conn() as c:
        old = c.execute("SELECT id FROM attachments").fetchone()[0]
    r = web.post(f"/invoices/{inv}/documents", {"replaces_id": str(old)},
                 files={"file": ("b.pdf", PDF_BYTES + b"2", "application/pdf")})
    assert "document_replaced" in r.headers["location"]
    page = web.get(f"/invoices/{inv}").text
    assert "גרסאות קודמות (1)" in page and web.get(f"/attachments/{old}").status_code == 200


# ====================================================================== lists, history, errors

def test_payments_tabs_and_history(web):
    inv = created_id(new_invoice(web, amount="100", supplier="Paid Supplier Ltd"))
    ob = ob_id(web, inv)
    web.post(f"/obligations/{ob}/payments", {"amount": "100", "paid_on": "01/03/2025", "method": "check",
                                            "reference": "CHK-1", "request_token": "f" * 32})
    created_id(new_invoice(web, amount="50", supplier="Open Supplier"))
    assert "Open Supplier" in web.get("/payments").text and "Paid Supplier Ltd" not in web.get("/payments").text
    paid = web.get("/payments?tab=paid").text
    assert "Paid Supplier Ltd" in paid and "01/03/2025" in paid and "Open Supplier" not in paid
    all_ = web.get("/payments?tab=all").text
    assert "Paid Supplier Ltd" in all_ and "Open Supplier" in all_
    ledger = html.unescape(web.get("/history?view=payments").text)  # "צ'ק" is HTML-escaped as צ&#39;ק
    assert "CHK-1" in ledger and "צ'ק" in ledger
    changes = web.get("/history?view=changes").text
    assert "תשלום נרשם" in changes and "נוצר" in changes


@pytest.mark.parametrize("url", ["/invoices/999", "/invoices/abc", "/attachments/999", "/obligations/999",
                                 "/settings/suppliers/999/edit"])
def test_missing_records_are_hebrew_404(web, url):
    r = web.get(url)
    assert r.status_code == 404 and "הדף לא נמצא" in r.text


@pytest.mark.parametrize("url", ["/invoices/new", "/settings/suppliers", "/obligations/1/payments",
                                 "/obligations/1/postpone", "/obligations/1/cancel", "/invoices/1/cancel"])
def test_all_forms_require_csrf(web, client, url):
    created_id(new_invoice(web))
    r = client.post(url, data={"name": "x", "reason": "x"}, headers={"origin": "http://127.0.0.1:8765"})
    assert r.status_code == 403


def test_onboarding_shown_only_when_empty(web):
    assert "ברוכים הבאים" in web.get("/").text
    created_id(new_invoice(web))
    assert "ברוכים הבאים" not in web.get("/").text


def test_client_script_does_not_use_shadowable_form_properties():
    """Regression: a field named "method" shadows form.method in the DOM, which crashed the submit
    handler on payment forms (skipping the double-submit guard and the void confirmation)."""
    from pathlib import Path
    js = (Path(__file__).resolve().parent.parent / "app" / "static" / "js" / "app.js").read_text(encoding="utf-8")
    code = "\n".join(line.split("//")[0] for line in js.splitlines())  # ignore comments
    for prop in ("form.method", "form.action", "form.submit(", "form.elements.method"):
        assert prop not in code, prop


def test_pages_have_no_inline_script_or_style(web):
    inv = created_id(new_invoice(web, file=("a.pdf", PDF_BYTES, "application/pdf")))
    for url in ("/", "/settings", "/invoices/new", f"/invoices/{inv}", f"/invoices/{inv}/edit", "/payments",
                "/history", "/history?view=changes"):
        html = web.get(url).text
        assert " style=" not in html, url          # strict CSP: no inline style attributes
        assert "<script>" not in html, url         # and no inline scripts
        assert re.search(r"\son[a-z]+=", html) is None, url
