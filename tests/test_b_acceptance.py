"""Specification §9 acceptance tests delivered in Phase B (10, 11, 15, 16 partial, 18).

16 is completed in Phase C (search + dashboard rules); 15's "overdue stays visible" part too.
"""

import re

from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import ORIGIN, PDF_BYTES, PNG_BYTES, Web
from tests.test_b_web import created_id, new_invoice, ob_id


def test_acceptance_10_invoice_without_attachment_then_pdf_added_later(web):
    inv = created_id(new_invoice(web))
    assert "לא צורף מסמך" in web.get(f"/invoices/{inv}").text
    web.post(f"/invoices/{inv}/documents", {}, files={"file": ("late.pdf", PDF_BYTES, "application/pdf")})
    page = web.get(f"/invoices/{inv}").text
    att = int(re.search(r'href="/attachments/(\d+)"', page).group(1))
    assert web.get(f"/attachments/{att}").content == PDF_BYTES


def test_acceptance_11_payment_without_receipt_or_reference_and_overpayment_rejected(web):
    inv = created_id(new_invoice(web, amount="400"))
    ob = ob_id(web, inv)
    ok = web.post(f"/obligations/{ob}/payments", {"amount": "400", "paid_on": "11/11/2026", "method": "cash",
                                                 "request_token": "1" * 32})
    assert ok.status_code == 303
    inv2 = created_id(new_invoice(web, amount="400", supplier="Other"))
    over = web.post(f"/obligations/{ob_id(web, inv2)}/payments",
                    {"amount": "500", "paid_on": "11/11/2026", "method": "cash", "request_token": "2" * 32})
    assert over.status_code == 422 and "גבוה מהיתרה" in over.text


def test_acceptance_15_restart_keeps_everything(config, clock):
    app1 = create_app(config, clock)
    with TestClient(app1, base_url=ORIGIN) as c1:
        w1 = Web(c1, app1)
        inv = created_id(new_invoice(w1, amount="400", file=("a.pdf", PDF_BYTES, "application/pdf")))
        ob = ob_id(w1, inv)
        w1.post(f"/obligations/{ob}/payments", {"amount": "150", "paid_on": "01/11/2026", "method": "card",
                                               "request_token": "3" * 32})
        w1.post(f"/obligations/{ob}/postpone", {"new_due_date": "10/01/2027"})
    app2 = create_app(config, clock)   # a brand-new server process on the same data
    with TestClient(app2, base_url=ORIGIN) as c2:
        page = c2.get(f"/invoices/{inv}").text
        assert "₪150.00" in page and "₪250.00" in page and "10/01/2027" in page and "a.pdf" in page
        assert app2.state.integrity_issues == []


def test_acceptance_16_paid_invoice_fully_viewable_everywhere(web):
    inv = created_id(new_invoice(web, amount="400", supplier="Paid Forever Ltd", invoice_number="PF-1",
                                 file=("original.pdf", PDF_BYTES, "application/pdf")))
    ob = ob_id(web, inv)
    web.post(f"/obligations/{ob}/payments", {"amount": "400", "paid_on": "05/01/2025", "method": "bank_transfer",
                                            "reference": "BANK-REF-9", "request_token": "4" * 32},
             files={"file": ("receipt.png", PNG_BYTES, "image/png")})
    # Paid tab, All tab, History ledger
    assert "Paid Forever Ltd" in web.get("/payments?tab=paid").text
    assert "Paid Forever Ltd" in web.get("/payments?tab=all").text
    ledger = web.get("/history?view=payments").text
    assert "BANK-REF-9" in ledger and "05/01/2025" in ledger
    # Not in Open (the action list)
    assert "Paid Forever Ltd" not in web.get("/payments?tab=open").text
    # Details: original invoice, receipt, reference, original and payment dates
    page = web.get(f"/invoices/{inv}").text
    for text in ("original.pdf", "receipt.png", "BANK-REF-9", "05/01/2025", "01/12/2026", "PF-1", "שולמה במלואה"):
        assert text in page
    for att in re.findall(r'href="/attachments/(\d+)"', page):
        assert web.get(f"/attachments/{att}").status_code == 200


def test_acceptance_18_archive_does_not_destroy_paid_history(web):
    inv = created_id(new_invoice(web, amount="400", supplier="Archived Supplier",
                                 file=("doc.pdf", PDF_BYTES, "application/pdf")))
    ob = ob_id(web, inv)
    web.post(f"/obligations/{ob}/payments", {"amount": "400", "paid_on": "01/11/2026", "method": "cash",
                                            "request_token": "5" * 32})
    with web.conn() as c:
        sid = c.execute("SELECT supplier_id FROM invoices WHERE id = ?", (inv,)).fetchone()[0]
    web.post("/settings/properties", {"name": "Flat to archive"})
    with web.conn() as c:
        pid = c.execute("SELECT id FROM properties WHERE name = 'Flat to archive'").fetchone()[0]
    assert web.post(f"/settings/suppliers/{sid}/archive").status_code == 303
    assert web.post(f"/settings/properties/{pid}/archive").status_code == 303
    page = web.get(f"/invoices/{inv}").text
    assert "Archived Supplier" in page and "בארכיון" in page and "doc.pdf" in page and "שולמה במלואה" in page
    assert "Archived Supplier" in web.get("/payments?tab=paid").text
    with web.conn() as c:
        assert c.execute("SELECT COUNT(*) FROM payment_entries WHERE voided_at IS NULL").fetchone()[0] == 1
    # an archived supplier is no longer offered for new invoices, but its name cannot be silently reused
    assert "Archived Supplier" not in web.get("/invoices/new").text
