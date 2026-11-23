"""Hebrew RTL foundation: startup DB init, integrity banner, template helpers, Hebrew messages."""

import sqlite3

from fastapi.testclient import TestClient

from app.db.errors import hebrew_message
from app.db.migrate import latest_version
from app.i18n import he
from app.main import create_app
from tests.conftest import ORIGIN


def test_startup_creates_database_in_live_folder(app, data_root):
    db_file = data_root / "live" / "payment_manager.sqlite3"
    assert db_file.is_file()
    c = sqlite3.connect(db_file)
    assert c.execute("PRAGMA user_version").fetchone()[0] == latest_version()
    c.close()
    assert app.state.integrity_issues == []


def test_restart_reuses_database_without_snapshot(config, clock, data_root):
    create_app(config, clock)
    create_app(config, clock)
    assert list((data_root / "backups" / "pre-migration").iterdir()) == []


def test_integrity_banner_shown_when_problem(config, clock, data_root):
    create_app(config, clock)
    c = sqlite3.connect(data_root / "live" / "payment_manager.sqlite3")
    c.execute("PRAGMA foreign_keys = ON")
    sid = c.execute("INSERT INTO suppliers (name) VALUES ('X')").lastrowid
    inv = c.execute("INSERT INTO invoices (supplier_id, property_id, currency, total_minor) "
                    "VALUES (?, 1, 'EUR', 100000)", (sid,)).lastrowid
    c.execute("INSERT INTO obligations (invoice_id, supplier_id, property_id, currency, amount_minor, "
              "original_due_date, current_due_date) VALUES (?, ?, 1, 'EUR', 40000, '2026-12-01', '2026-12-01')",
              (inv, sid))
    c.commit()
    c.close()
    app = create_app(config, clock)
    with TestClient(app, base_url=ORIGIN) as client:
        html = client.get("/").text
    assert he.INTEGRITY_BANNER_TITLE in html
    assert he.INTEGRITY_INVOICE_SUM in html


def test_no_banner_when_healthy(client):
    assert he.INTEGRITY_BANNER_TITLE not in client.get("/").text


def test_macros_render_money_dates_and_badges(app):
    env = app.state.templates.env
    tpl = env.from_string(
        '{% import "_macros.html" as ui %}'
        "{{ ui.money(120000, 'EUR') }}|{{ ui.money(None, 'EUR') }}|{{ ui.date('2026-03-05') }}|"
        "{{ ui.state_badge('partial') }}|{{ ui.urgency_badge('overdue') }}|{{ ui.text('ACME Ltd') }}|"
        "{{ ui.csrf_field() }}")
    out = tpl.render()  # no context passed: macros must work from template globals alone
    assert '<bdi dir="ltr" class="num">€1,200.00</bdi>' in out
    assert "חסר סכום" in out
    assert '<bdi dir="ltr" class="num">05/03/2026</bdi>' in out
    assert "שולם חלקית" in out and "באיחור" in out
    assert "<bdi>ACME Ltd</bdi>" in out
    assert f'name="csrf_token" value="{app.state.csrf_token}"' in out


def test_field_macro_shows_hebrew_error(app):
    env = app.state.templates.env
    tpl = env.from_string(
        '{% import "_macros.html" as ui %}'
        "{% call ui.field('due_date', 'מועד תשלום', errors=errors, required=True) %}<input id=\"f-due_date\">"
        "{% endcall %}{{ ui.error_summary(errors) }}")
    out = tpl.render(he=he, errors={"due_date": he.DATE_NOT_EXISTS.format(value="31/02/2026")})
    assert "has-error" in out and "תאריך לא קיים: 31/02/2026" in out
    assert "לא ניתן לשמור" in out


def test_labels_are_complete():
    assert set(he.OBLIGATION_STATES) == {"open", "partial", "paid", "missing_amount", "canceled", "restructured"}
    assert set(he.PAYMENT_METHODS) == {"bank_transfer", "card", "cash", "check", "other"}
    assert set(he.FREQUENCIES) == {"monthly", "bimonthly", "quarterly", "annual"}


def test_every_trigger_error_has_hebrew_text():
    import re
    from app.db.migrate import MIGRATIONS_DIR
    sql = "".join(p.read_text(encoding="utf-8") for p in MIGRATIONS_DIR.glob("*.sql"))
    codes = set(re.findall(r"'pm:([a-z_]+)'", sql))
    assert codes and codes <= set(he.DB_ERRORS)
    for code in codes:
        assert hebrew_message(sqlite3.IntegrityError(f"pm:{code}")) == he.DB_ERRORS[code]
