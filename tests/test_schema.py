"""Schema v1: migrations, constraints, immutability, payment guards, change tracking."""

import shutil
import sqlite3

import pytest

from app.db.connection import Database, transaction
from app.db.errors import error_code, hebrew_message
from app.db.migrate import (MIGRATIONS_DIR, MigrationError, SchemaTooNewError, current_version,
                            latest_version, migrate, split_sql)
from tests import factories as f

TRACKED_TABLES = {
    "currencies", "properties", "suppliers", "categories", "invoices", "obligations", "postponements",
    "payment_entries", "recurring_templates", "recurring_pauses", "recurring_skipped_periods", "reminders",
    "attachments", "audit_events", "settings",
}
UNTRACKED_TABLES = {"backup_log", "backup_settings", "system_state", "change_counter"}


def raises_code(code):
    """Context manager asserting an IntegrityError whose message carries pm:<code>."""
    return pytest.raises(sqlite3.IntegrityError, match=f"pm:{code}")


# ====================================================================== migrations

def test_fresh_migration(db, conn):
    assert current_version(conn) == latest_version() == 3
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert TRACKED_TABLES | UNTRACKED_TABLES <= tables


def test_migration_is_idempotent(db):
    latest = latest_version()
    assert migrate(db) == {"from": latest, "to": latest, "backup": None}


def test_real_upgrade_v1_to_v2_keeps_data_and_snapshots(tmp_path):
    """The path an existing installation takes: a v1 database with data → current schema."""
    mdir = _migrations_copy(tmp_path)  # only 0001
    db = Database(tmp_path / "live" / "pm.sqlite3")
    migrate(db, migrations_dir=mdir)
    with db.connection() as c:
        ob = f.obligation(c, amount_minor=40000)
        f.pay(c, ob, 15000)
    result = migrate(db, backup_dir=tmp_path / "pre-migration", now_label="t")  # real migrations dir
    assert (result["from"], result["to"]) == (1, latest_version())
    assert result["backup"].is_file()
    with db.connection() as c:
        assert f.balance(c, ob)["outstanding_minor"] == 25000
        assert c.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='trg_obligation_missing_amount_insert'"
                         ).fetchone()[0] == 1


def test_seed_is_system_data_only(conn):
    assert {r[0] for r in conn.execute("SELECT code FROM currencies")} == {"ILS", "EUR", "USD"}
    assert conn.execute("SELECT name FROM properties").fetchall()[0][0] == "הוצאה כללית"
    assert conn.execute("SELECT COUNT(*) FROM suppliers").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM invoices").fetchone()[0] == 0
    assert conn.execute("SELECT value FROM settings WHERE key='default_reminder_lead_days'").fetchone()[0] == "7"


def test_schema_too_new_is_refused_and_untouched(tmp_path):
    db = Database(tmp_path / "x.sqlite3")
    with db.connection() as c:
        c.execute("PRAGMA user_version = 99")
    with pytest.raises(SchemaTooNewError):
        migrate(db)
    with db.connection() as c:
        assert current_version(c) == 99
        assert c.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0] == 0


def _migrations_copy(tmp_path):
    mdir = tmp_path / "migrations"
    mdir.mkdir()
    shutil.copy(MIGRATIONS_DIR / "0001_initial.sql", mdir / "0001_initial.sql")
    return mdir


def test_upgrade_takes_snapshot_and_preserves_data(tmp_path):
    mdir = _migrations_copy(tmp_path)
    db = Database(tmp_path / "live" / "pm.sqlite3")
    migrate(db, backup_dir=tmp_path / "pre-migration", migrations_dir=mdir)
    with db.connection() as c:
        f.supplier(c, "Keep Me Ltd")
    (mdir / "0002_add_column.sql").write_text(
        "ALTER TABLE suppliers ADD COLUMN vat_number TEXT;\n", encoding="utf-8")

    result = migrate(db, backup_dir=tmp_path / "pre-migration", now_label="t", migrations_dir=mdir)
    assert result["from"] == 1 and result["to"] == 2
    assert result["backup"].exists()
    snap = sqlite3.connect(result["backup"])
    assert snap.execute("SELECT name FROM suppliers").fetchone()[0] == "Keep Me Ltd"
    assert snap.execute("PRAGMA user_version").fetchone()[0] == 1
    snap.close()
    with db.connection() as c:
        assert tuple(c.execute("SELECT name, vat_number FROM suppliers").fetchone()) == ("Keep Me Ltd", None)


def test_failed_migration_rolls_back_completely(tmp_path):
    mdir = _migrations_copy(tmp_path)
    db = Database(tmp_path / "pm.sqlite3")
    migrate(db, migrations_dir=mdir)
    (mdir / "0002_broken.sql").write_text(
        "CREATE TABLE new_table (id INTEGER PRIMARY KEY);\nINSERT INTO no_such_table VALUES (1);\n", encoding="utf-8")
    with pytest.raises(MigrationError):
        migrate(db, migrations_dir=mdir)
    with db.connection() as c:
        assert current_version(c) == 1
        assert c.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='new_table'").fetchone()[0] == 0


def test_migration_numbering_enforced(tmp_path):
    mdir = _migrations_copy(tmp_path)
    (mdir / "0003_gap.sql").write_text("SELECT 1;\n", encoding="utf-8")
    with pytest.raises(MigrationError):
        migrate(Database(tmp_path / "pm.sqlite3"), migrations_dir=mdir)


def test_split_sql_keeps_trigger_bodies_intact():
    stmts = split_sql("CREATE TABLE a (x);\n-- note; with semicolon\nCREATE TRIGGER t AFTER INSERT ON a BEGIN\n"
                      "  SELECT 1; SELECT 2;\nEND;\n")
    assert len(stmts) == 2
    assert stmts[1].count("SELECT") == 2


# ====================================================================== change tracking

def _tracked_tables(conn):
    rows = conn.execute("SELECT tbl_name FROM sqlite_master WHERE type='trigger' AND sql LIKE "
                        "'%UPDATE change_counter SET seq = seq + 1%'").fetchall()
    return {r[0] for r in rows}


def test_tracked_tables_exactly_the_approved_list(conn):
    assert _tracked_tables(conn) == TRACKED_TABLES
    assert not (_tracked_tables(conn) & UNTRACKED_TABLES)
    # every user table is either tracked or explicitly untracked: a new table must be classified
    all_tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
    assert all_tables == TRACKED_TABLES | UNTRACKED_TABLES


def test_user_data_writes_bump_counter(conn):
    start = f.seq(conn)
    sid = f.supplier(conn)
    assert f.seq(conn) == start + 1
    conn.execute("UPDATE suppliers SET notes = 'x' WHERE id = ?", (sid,))
    conn.execute("UPDATE settings SET value = '5' WHERE key = 'default_reminder_lead_days'")
    assert f.seq(conn) == start + 3


def test_bookkeeping_writes_do_not_bump_counter(conn):
    start = f.seq(conn)
    conn.execute("INSERT INTO backup_log (kind, status, change_seq) VALUES ('daily', 'created', ?)", (start,))
    conn.execute("UPDATE backup_log SET status = 'verified'")
    conn.execute("INSERT INTO backup_settings (key, value) VALUES ('folder', 'D:\\Backups')")
    conn.execute("UPDATE backup_settings SET value = 'E:\\Backups'")
    conn.execute("INSERT INTO system_state (key, value) VALUES ('last_backup_seq', ?)", (str(start),))
    conn.execute("UPDATE system_state SET value = '999'")
    conn.execute("UPDATE change_counter SET seq = seq WHERE id = 1")
    assert f.seq(conn) == start


def test_insert_that_inserts_nothing_does_not_bump_counter(conn):
    tid = f.template(conn)
    f.obligation(conn, amount_minor=10000, template_id=tid, period_key="2026-11", supplier_id=None)
    before = f.seq(conn)
    conn.execute("""INSERT INTO obligations (recurring_template_id, period_key, supplier_id, property_id, currency,
                        amount_minor, original_due_date, current_due_date)
                    SELECT ?, '2026-11', supplier_id, property_id, 'ILS', 10000, '2026-11-15', '2026-11-15'
                    FROM recurring_templates WHERE id = ?
                    ON CONFLICT (recurring_template_id, period_key) DO NOTHING""", (tid, tid))
    assert f.seq(conn) == before


# ====================================================================== no hard deletes

def _populate_every_table(conn):
    """One row in every user-data table (delete triggers only fire for existing rows)."""
    conn.execute("INSERT INTO categories (name) VALUES ('חשמל')")
    inv = f.invoice(conn)
    ob = f.obligation(conn, invoice_id=inv)
    conn.execute("INSERT INTO postponements (obligation_id, old_due_date, new_due_date) "
                 "VALUES (?, '2026-12-01', '2026-12-10')", (ob,))
    entry = f.pay(conn, ob, 100)
    tid = f.template(conn)
    pid = conn.execute("INSERT INTO recurring_pauses (template_id, paused_on, resumed_on) "
                       "VALUES (?, '2026-03-10', '2026-07-05')", (tid,)).lastrowid
    conn.execute("INSERT INTO recurring_skipped_periods (template_id, period_key, pause_id, nominal_due_date) "
                 "VALUES (?, '2026-03', ?, '2026-03-15')", (tid, pid))
    conn.execute("INSERT INTO reminders (obligation_id, remind_on) VALUES (?, '2026-11-20')", (ob,))
    conn.execute("INSERT INTO attachments (payment_entry_id, kind, original_name, stored_path, mime, size_bytes, "
                 "sha256) VALUES (?, 'receipt', 'r.pdf', 'receipts/2026/r.pdf', 'application/pdf', 10, ?)",
                 (entry, "d" * 64))
    conn.execute("INSERT INTO audit_events (entity_type, entity_id, action, occurred_at) "
                 "VALUES ('invoice', ?, 'create', '2026-11-12 09:00:00')", (inv,))


@pytest.mark.parametrize("table", sorted(TRACKED_TABLES - {"settings"}) + ["change_counter"])
def test_delete_forbidden(conn, table):
    _populate_every_table(conn)
    assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] > 0
    with raises_code("delete_forbidden"):
        conn.execute(f"DELETE FROM {table}")


def test_delete_message_is_hebrew(conn):
    with pytest.raises(sqlite3.IntegrityError) as exc:
        conn.execute("DELETE FROM currencies")
    assert error_code(exc.value) == "delete_forbidden"
    assert "מחיקה" in hebrew_message(exc.value)


# ====================================================================== strict dates in the DB

@pytest.mark.parametrize("bad", ["2026-02-30", "2027-02-29", "2026-13-01", "2026-2-3", "1999-12-31",
                                 "2101-01-01", "12/11/2026", "", "2026-11-12 10:00:00"])
def test_db_rejects_invalid_dates(conn, bad):
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        f.obligation(conn, due=bad)


def test_db_accepts_leap_day(conn):
    f.obligation(conn, due="2028-02-29")


@pytest.mark.parametrize("bad", ["2026-02-30", "2026-11-13x"])
def test_db_rejects_invalid_payment_date(conn, bad):
    ob = f.obligation(conn)
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        f.pay(conn, ob, 100, paid_on=bad)


# ====================================================================== money constraints

@pytest.mark.parametrize("bad", [0, -100, 400.5, 0.01, "abc"])
def test_obligation_amount_must_be_positive_integer(conn, bad):
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        f.obligation(conn, amount_minor=bad)


def test_fractional_minor_units_never_stored(conn):
    # SQLite stores an exact whole number (400.0 or '400') as INTEGER 400 — harmless;
    # anything with a fraction stays REAL and is rejected above.
    ob = f.obligation(conn, amount_minor=400.0)
    assert conn.execute("SELECT typeof(amount_minor) FROM obligations WHERE id = ?", (ob,)).fetchone()[0] == "integer"


@pytest.mark.parametrize("bad", [0, -1, 10.5])
def test_payment_amount_must_be_positive_integer(conn, bad):
    ob = f.obligation(conn)
    with pytest.raises(sqlite3.IntegrityError):
        f.pay(conn, ob, bad)


def test_missing_amount_only_for_variable_recurring(conn):
    # one-off / installment obligation: amount required
    with pytest.raises(sqlite3.IntegrityError):
        f.obligation(conn, amount_minor=None)
    # FIXED recurring occurrence: amount required
    fixed = f.template(conn, amount_mode="fixed", fixed=10000)
    with raises_code("missing_amount_not_variable"):
        f.obligation(conn, amount_minor=None, template_id=fixed, period_key="2026-11")
    # VARIABLE recurring occurrence: unknown amount allowed until the invoice arrives
    var = f.template(conn, amount_mode="variable", fixed=None)
    ob = f.obligation(conn, amount_minor=None, template_id=var, period_key="2026-11")
    assert f.balance(conn, ob)["primary_state"] == "missing_amount"
    assert f.balance(conn, ob)["outstanding_minor"] is None  # unknown, never zero
    # …and once known it must be a positive amount, never zero
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        conn.execute("UPDATE obligations SET amount_minor = 0 WHERE id = ?", (ob,))
    conn.execute("UPDATE obligations SET amount_minor = 31250 WHERE id = ?", (ob,))
    assert f.balance(conn, ob)["primary_state"] == "open"


@pytest.mark.parametrize("sql", [
    "INSERT INTO invoices (supplier_id, property_id, currency, total_minor) VALUES ({s}, 1, 'EUR', 0)",
    "INSERT INTO recurring_templates (supplier_id, property_id, currency, frequency, due_day, start_date, "
    "generate_from_date, amount_mode, fixed_amount_minor) VALUES ({s}, 1, 'ILS', 'monthly', 1, '2026-01-01', "
    "'2026-01-01', 'fixed', 0)",
    "INSERT INTO obligations (supplier_id, property_id, currency, amount_minor, original_due_date, "
    "current_due_date) VALUES ({s}, 1, 'EUR', 0, '2026-12-01', '2026-12-01')",
])
def test_zero_amounts_rejected_everywhere(conn, sql):
    sid = f.supplier(conn)
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        conn.execute(sql.format(s=sid))


def test_payment_of_zero_rejected(conn):
    ob = f.obligation(conn)
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        f.pay(conn, ob, 0)


def test_null_invoice_total_only_for_missing_amount_occurrences(conn):
    var = f.template(conn, amount_mode="variable", fixed=None)
    inv = f.invoice(conn, total_minor=None)
    # a known-amount obligation cannot hang off an invoice without a total
    with raises_code("invoice_total_required"):
        f.obligation(conn, invoice_id=inv, amount_minor=40000)
    # a variable occurrence still missing its amount can
    f.obligation(conn, invoice_id=inv, amount_minor=None, template_id=var, period_key="2026-11")
    # re-linking a known-amount obligation to it is blocked too
    other = f.obligation(conn, amount_minor=5000)
    with raises_code("invoice_total_required"):
        conn.execute("UPDATE obligations SET invoice_id = ? WHERE id = ?", (inv, other))


def test_recurring_occurrence_unique(conn):
    tid = f.template(conn)
    f.obligation(conn, template_id=tid, period_key="2026-11")
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        f.obligation(conn, template_id=tid, period_key="2026-11")


def test_template_amount_mode_rules(conn):
    with pytest.raises(sqlite3.IntegrityError):
        f.template(conn, amount_mode="fixed", fixed=None)
    with pytest.raises(sqlite3.IntegrityError):
        f.template(conn, amount_mode="variable", fixed=5000)
    f.template(conn, amount_mode="variable", fixed=None)


def test_foreign_keys_enforced(conn):
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        f.obligation(conn, supplier_id=999999)
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        f.invoice(conn, currency="GBP")


# ====================================================================== payment guards

def test_overpayment_rejected_by_one_cent(conn):
    ob = f.obligation(conn, amount_minor=40000)
    f.pay(conn, ob, 15000)
    with raises_code("overpayment"):
        f.pay(conn, ob, 25001)
    f.pay(conn, ob, 25000)
    assert f.balance(conn, ob)["primary_state"] == "paid"
    with raises_code("overpayment"):
        f.pay(conn, ob, 1)


def test_overpayment_message_is_hebrew(conn):
    ob = f.obligation(conn, amount_minor=100)
    with pytest.raises(sqlite3.IntegrityError) as exc:
        f.pay(conn, ob, 101)
    assert hebrew_message(exc.value).startswith("סכום התשלום גבוה מהיתרה")


def test_no_payment_on_missing_amount(conn):
    tid = f.template(conn, amount_mode="variable", fixed=None)
    ob = f.obligation(conn, amount_minor=None, template_id=tid, period_key="2026-11")
    with raises_code("payment_on_missing_amount"):
        f.pay(conn, ob, 100)


@pytest.mark.parametrize("lifecycle", ["canceled", "restructured"])
def test_no_payment_on_closed_obligation(conn, lifecycle):
    ob = f.obligation(conn)
    f.close(conn, ob, lifecycle)
    with raises_code("payment_on_inactive_obligation"):
        f.pay(conn, ob, 100)


def test_payment_cannot_be_inserted_voided(conn):
    ob = f.obligation(conn)
    with raises_code("payment_inserted_voided"):
        conn.execute("INSERT INTO payment_entries (obligation_id, amount_minor, paid_on, method, voided_at, "
                     "void_reason) VALUES (?, 100, '2026-11-10', 'cash', '2026-11-12 09:00:00', 'x')", (ob,))


@pytest.mark.parametrize("column, value", [("amount_minor", 1), ("paid_on", "2026-11-01"),
                                           ("method", "cash"), ("reference", "X"), ("obligation_id", 2)])
def test_payment_is_immutable(conn, column, value):
    ob = f.obligation(conn)
    f.obligation(conn)
    entry = f.pay(conn, ob, 100)
    with raises_code("payment_immutable"):
        conn.execute(f"UPDATE payment_entries SET {column} = ? WHERE id = ?", (value, entry))


def test_void_once_restores_balance(conn):
    ob = f.obligation(conn, amount_minor=40000)
    entry = f.pay(conn, ob, 15000)
    f.void(conn, entry)
    assert f.balance(conn, ob)["paid_minor"] == 0
    with raises_code("payment_already_voided"):
        f.void(conn, entry, "again")


def test_void_requires_reason(conn):
    ob = f.obligation(conn)
    entry = f.pay(conn, ob, 100)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE payment_entries SET voided_at = '2026-11-12 09:00:00' WHERE id = ?", (entry,))


def test_void_on_restructured_parent_blocked(conn):
    ob = f.obligation(conn, amount_minor=40000)
    entry = f.pay(conn, ob, 15000)
    f.close(conn, ob, "restructured")
    with raises_code("void_on_restructured"):
        f.void(conn, entry)


def test_double_submit_token_unique(conn):
    ob = f.obligation(conn)
    f.pay(conn, ob, 100, token="tok-1")
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        f.pay(conn, ob, 100, token="tok-1")


# ====================================================================== obligation guards

def test_amount_cannot_drop_below_paid(conn):
    ob = f.obligation(conn, amount_minor=40000)
    f.pay(conn, ob, 15000)
    with raises_code("amount_below_paid"):
        conn.execute("UPDATE obligations SET amount_minor = 14999 WHERE id = ?", (ob,))
    conn.execute("UPDATE obligations SET amount_minor = 15000 WHERE id = ?", (ob,))
    assert f.balance(conn, ob)["primary_state"] == "paid"


@pytest.mark.parametrize("lifecycle", ["canceled", "restructured"])
@pytest.mark.parametrize("sql", [
    "UPDATE obligations SET amount_minor = 50000 WHERE id = ?",
    "UPDATE obligations SET lifecycle = 'active', closed_at = NULL WHERE id = ?",
    "UPDATE obligations SET current_due_date = '2027-01-01' WHERE id = ?",
])
def test_closed_obligation_is_frozen(conn, lifecycle, sql):
    ob = f.obligation(conn, amount_minor=40000)
    f.close(conn, ob, lifecycle)
    with raises_code("obligation_closed"):
        conn.execute(sql, (ob,))


def test_closed_obligation_notes_still_editable(conn):
    ob = f.obligation(conn)
    f.close(conn, ob, "canceled")
    conn.execute("UPDATE obligations SET notes = 'context' WHERE id = ?", (ob,))


def test_original_due_date_immutable(conn):
    ob = f.obligation(conn)
    with raises_code("obligation_identity_immutable"):
        conn.execute("UPDATE obligations SET original_due_date = '2026-12-05' WHERE id = ?", (ob,))


def test_amount_cannot_be_removed(conn):
    tid = f.template(conn, amount_mode="variable", fixed=None)
    ob = f.obligation(conn, amount_minor=None, template_id=tid, period_key="2026-11")
    conn.execute("UPDATE obligations SET amount_minor = 5000 WHERE id = ?", (ob,))
    with raises_code("amount_cannot_be_removed"):
        conn.execute("UPDATE obligations SET amount_minor = NULL WHERE id = ?", (ob,))


def test_closed_requires_closed_at(conn):
    ob = f.obligation(conn)
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        conn.execute("UPDATE obligations SET lifecycle = 'canceled' WHERE id = ?", (ob,))


# ====================================================================== attachments

def _attach(conn, **overrides):
    values = dict(invoice_id=None, obligation_id=None, payment_entry_id=None, kind="invoice",
                  original_name="bill.pdf", stored_path="invoices/2026/a1.pdf", mime="application/pdf",
                  size_bytes=1000, sha256="a" * 64)
    values.update(overrides)
    return conn.execute(
        "INSERT INTO attachments (invoice_id, obligation_id, payment_entry_id, kind, original_name, stored_path, "
        "mime, size_bytes, sha256) VALUES (:invoice_id, :obligation_id, :payment_entry_id, :kind, :original_name, "
        ":stored_path, :mime, :size_bytes, :sha256)", values).lastrowid


def test_attachment_needs_exactly_one_owner(conn):
    inv = f.invoice(conn)
    ob = f.obligation(conn, invoice_id=inv)
    with pytest.raises(sqlite3.IntegrityError):
        _attach(conn)
    with pytest.raises(sqlite3.IntegrityError):
        _attach(conn, invoice_id=inv, obligation_id=ob)
    _attach(conn, invoice_id=inv)


@pytest.mark.parametrize("path", ["invoices/../secret.pdf", "C:/Windows/x.pdf", "c:\\x.pdf", "/etc/passwd",
                                  "\\\\server\\share\\x.pdf", "backups/x.pdf", "x.pdf", ""])
def test_attachment_path_must_be_safe(conn, path):
    inv = f.invoice(conn)
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        _attach(conn, invoice_id=inv, stored_path=path)


@pytest.mark.parametrize("override", [{"sha256": "A" * 64}, {"sha256": "abc"}, {"mime": "text/html"},
                                      {"size_bytes": 0}, {"kind": "contract"}])
def test_attachment_metadata_validated(conn, override):
    inv = f.invoice(conn)
    with pytest.raises(sqlite3.IntegrityError):
        _attach(conn, invoice_id=inv, **override)


def test_attachment_immutable_and_superseded_once(conn):
    inv = f.invoice(conn)
    a1 = _attach(conn, invoice_id=inv)
    a2 = _attach(conn, invoice_id=inv, stored_path="invoices/2026/a2.pdf", sha256="b" * 64)
    a3 = _attach(conn, invoice_id=inv, stored_path="invoices/2026/a3.pdf", sha256="c" * 64)
    with raises_code("attachment_immutable"):
        conn.execute("UPDATE attachments SET stored_path = 'invoices/2026/other.pdf' WHERE id = ?", (a1,))
    conn.execute("UPDATE attachments SET superseded_by = ? WHERE id = ?", (a2, a1))
    with raises_code("attachment_already_superseded"):
        conn.execute("UPDATE attachments SET superseded_by = ? WHERE id = ?", (a3, a1))


# ====================================================================== history & pauses

def test_audit_events_append_only(conn):
    eid = conn.execute("INSERT INTO audit_events (entity_type, entity_id, action, occurred_at, new_json) "
                       "VALUES ('invoice', 1, 'create', '2026-11-12 09:00:00', '{\"a\": 1}')").lastrowid
    with raises_code("history_immutable"):
        conn.execute("UPDATE audit_events SET action = 'x' WHERE id = ?", (eid,))
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        conn.execute("INSERT INTO audit_events (entity_type, action, occurred_at, new_json) "
                     "VALUES ('x', 'y', '2026-11-12 09:00:00', 'not json')")


def test_postponement_append_only(conn):
    ob = f.obligation(conn)
    pid = conn.execute("INSERT INTO postponements (obligation_id, old_due_date, new_due_date) "
                       "VALUES (?, '2026-12-01', '2026-12-15')", (ob,)).lastrowid
    with raises_code("history_immutable"):
        conn.execute("UPDATE postponements SET reason = 'x' WHERE id = ?", (pid,))
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        conn.execute("INSERT INTO postponements (obligation_id, old_due_date, new_due_date) "
                     "VALUES (?, '2026-12-01', '2026-12-01')", (ob,))


def test_pause_rules(conn):
    tid = f.template(conn)
    p1 = conn.execute("INSERT INTO recurring_pauses (template_id, paused_on) VALUES (?, '2026-03-10')",
                      (tid,)).lastrowid
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):  # second open pause
        conn.execute("INSERT INTO recurring_pauses (template_id, paused_on) VALUES (?, '2026-04-01')", (tid,))
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):   # resumed before paused
        conn.execute("UPDATE recurring_pauses SET resumed_on = '2026-03-09' WHERE id = ?", (p1,))
    conn.execute("UPDATE recurring_pauses SET resumed_on = '2026-07-05' WHERE id = ?", (p1,))
    with raises_code("pause_already_resumed"):
        conn.execute("UPDATE recurring_pauses SET resumed_on = '2026-07-06' WHERE id = ?", (p1,))
    with raises_code("pause_immutable"):
        conn.execute("UPDATE recurring_pauses SET paused_on = '2026-03-01' WHERE id = ?", (p1,))
    # a new pause is allowed once the previous one is closed
    conn.execute("INSERT INTO recurring_pauses (template_id, paused_on) VALUES (?, '2026-09-01')", (tid,))


def test_skipped_periods_unique_and_append_only(conn):
    tid = f.template(conn)
    pid = conn.execute("INSERT INTO recurring_pauses (template_id, paused_on, resumed_on) "
                       "VALUES (?, '2026-03-10', '2026-07-05')", (tid,)).lastrowid
    sid = conn.execute("INSERT INTO recurring_skipped_periods (template_id, period_key, pause_id, nominal_due_date) "
                       "VALUES (?, '2026-03', ?, '2026-03-15')", (tid, pid)).lastrowid
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        conn.execute("INSERT INTO recurring_skipped_periods (template_id, period_key, pause_id, nominal_due_date) "
                     "VALUES (?, '2026-03', ?, '2026-03-15')", (tid, pid))
    with raises_code("history_immutable"):
        conn.execute("UPDATE recurring_skipped_periods SET period_key = '2026-04' WHERE id = ?", (sid,))
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        conn.execute("INSERT INTO recurring_skipped_periods (template_id, period_key, pause_id, nominal_due_date) "
                     "VALUES (?, '2026-13', ?, '2026-03-15')", (tid, pid))


# ====================================================================== lookups

def test_single_general_property_that_cannot_be_archived(conn):
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        conn.execute("INSERT INTO properties (name, is_general) VALUES ('another', 1)")
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        conn.execute("UPDATE properties SET archived_at = '2026-11-12 09:00:00' WHERE is_general = 1")


def test_blank_names_rejected(conn):
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        conn.execute("INSERT INTO suppliers (name) VALUES ('   ')")


def test_transaction_helper_rolls_back(conn):
    with pytest.raises(sqlite3.IntegrityError):
        with transaction(conn):
            f.supplier(conn, "Will Vanish")
            conn.execute("DELETE FROM suppliers")  # blocked → whole unit rolls back
    assert conn.execute("SELECT COUNT(*) FROM suppliers WHERE name='Will Vanish'").fetchone()[0] == 0
