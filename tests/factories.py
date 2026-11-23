"""Minimal direct-SQL helpers for schema tests (services arrive in Phase B)."""

from __future__ import annotations

import sqlite3

NOW = "2026-11-12 09:00:00"


def general_property(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT id FROM properties WHERE is_general = 1").fetchone()[0]


def supplier(conn: sqlite3.Connection, name: str = "Electric Co") -> int:
    return conn.execute("INSERT INTO suppliers (name) VALUES (?)", (name,)).lastrowid


def invoice(conn, total_minor: int | None = 120000, currency: str = "EUR", supplier_id=None,
            invoice_number: str = "INV-1") -> int:
    supplier_id = supplier_id or supplier(conn)
    return conn.execute(
        "INSERT INTO invoices (supplier_id, property_id, currency, total_minor, invoice_number) VALUES (?,?,?,?,?)",
        (supplier_id, general_property(conn), currency, total_minor, invoice_number)).lastrowid


def obligation(conn, amount_minor: int | None = 40000, invoice_id=None, due: str = "2026-12-01",
               currency: str = "EUR", supplier_id=None, template_id=None, period_key=None,
               parent_id=None, installment=None) -> int:
    if supplier_id is None:
        supplier_id = (conn.execute("SELECT supplier_id FROM invoices WHERE id = ?", (invoice_id,)).fetchone()[0]
                       if invoice_id else supplier(conn))
    inst_no, inst_count = installment if installment else (None, None)
    return conn.execute(
        """INSERT INTO obligations (invoice_id, recurring_template_id, period_key, supplier_id, property_id,
               currency, amount_minor, original_due_date, current_due_date, parent_obligation_id,
               installment_no, installment_count)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (invoice_id, template_id, period_key, supplier_id, general_property(conn), currency, amount_minor,
         due, due, parent_id, inst_no, inst_count)).lastrowid


def pay(conn, obligation_id: int, amount_minor: int, paid_on: str = "2026-11-10", method: str = "bank_transfer",
        token: str | None = None) -> int:
    return conn.execute(
        "INSERT INTO payment_entries (obligation_id, amount_minor, paid_on, method, request_token) VALUES (?,?,?,?,?)",
        (obligation_id, amount_minor, paid_on, method, token)).lastrowid


def void(conn, entry_id: int, reason: str = "entered by mistake") -> None:
    conn.execute("UPDATE payment_entries SET voided_at = ?, void_reason = ? WHERE id = ?", (NOW, reason, entry_id))


def close(conn, obligation_id: int, lifecycle: str, reason: str = "test") -> None:
    paid = conn.execute("SELECT paid_minor FROM v_obligation_balance WHERE obligation_id = ?",
                        (obligation_id,)).fetchone()[0]
    conn.execute("UPDATE obligations SET lifecycle = ?, closed_at = ?, close_reason = ?, closed_paid_minor = ? "
                 "WHERE id = ?", (lifecycle, NOW, reason, paid, obligation_id))


def template(conn, amount_mode: str = "fixed", fixed: int | None = 10000, status: str = "active",
             start: str = "2026-01-01") -> int:
    return conn.execute(
        """INSERT INTO recurring_templates (supplier_id, property_id, currency, frequency, due_day, start_date,
               generate_from_date, amount_mode, fixed_amount_minor, status)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (supplier(conn, "Water Co"), general_property(conn), "ILS", "monthly", 15, start, start, amount_mode,
         fixed, status)).lastrowid


def balance(conn, obligation_id: int) -> sqlite3.Row:
    return conn.execute("SELECT * FROM v_obligation_balance WHERE obligation_id = ?", (obligation_id,)).fetchone()


def seq(conn) -> int:
    return conn.execute("SELECT seq FROM change_counter WHERE id = 1").fetchone()[0]
