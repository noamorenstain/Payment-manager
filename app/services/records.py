"""Read-only list queries: All Payments tabs (Open / Paid / All) and History.

There is no date limit anywhere: paid and canceled records from any year stay listed.
Filters, search and sorting are added in Phase C.
"""

from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass

PAGE_SIZE = 100
TABS = ("open", "paid", "all")

_BASE = """
    SELECT o.id AS obligation_id, o.invoice_id, o.currency, o.amount_minor, o.current_due_date,
           o.original_due_date, o.lifecycle, o.installment_no, o.installment_count,
           b.paid_minor, b.outstanding_minor, b.canceled_minor, b.transferred_minor, b.primary_state,
           s.name AS supplier_name, p.name AS property_name, p.is_general AS property_is_general,
           c.name AS category_name, i.invoice_number,
           (SELECT MAX(pe.paid_on) FROM payment_entries pe
             WHERE pe.obligation_id = o.id AND pe.voided_at IS NULL) AS last_paid_on,
           (SELECT COUNT(*) FROM attachments a
             WHERE a.superseded_by IS NULL AND (a.invoice_id = o.invoice_id OR a.obligation_id = o.id)) AS doc_count
    FROM obligations o
    JOIN v_obligation_balance b ON b.obligation_id = o.id
    JOIN suppliers s ON s.id = o.supplier_id
    JOIN properties p ON p.id = o.property_id
    LEFT JOIN categories c ON c.id = o.category_id
    LEFT JOIN invoices i ON i.id = o.invoice_id
"""

_TAB_SQL = {
    "open": ("WHERE o.lifecycle = 'active' AND (o.amount_minor IS NULL OR b.outstanding_minor > 0)",
             "ORDER BY o.current_due_date, o.id"),
    # "paid" = paid in full: active, amount known, nothing outstanding. Canceled never counts as paid.
    "paid": ("WHERE b.primary_state = 'paid'", "ORDER BY last_paid_on DESC, o.id DESC"),
    "all": ("", "ORDER BY o.current_due_date DESC, o.id DESC"),
}


@dataclass
class Page:
    rows: list
    page: int
    pages: int
    total: int


def _paginate(conn: sqlite3.Connection, sql: str, count_sql: str, params, page: int) -> Page:
    total = conn.execute(count_sql, params).fetchone()[0]
    pages = max(1, math.ceil(total / PAGE_SIZE))
    page = min(max(1, page), pages)
    rows = conn.execute(f"{sql} LIMIT ? OFFSET ?", (*params, PAGE_SIZE, (page - 1) * PAGE_SIZE)).fetchall()
    return Page(rows, page, pages, total)


def obligations_tab(conn: sqlite3.Connection, tab: str, page: int = 1) -> Page:
    where, order = _TAB_SQL[tab if tab in TABS else "open"]
    return _paginate(conn, f"{_BASE} {where} {order}",
                     f"SELECT COUNT(*) FROM obligations o JOIN v_obligation_balance b ON b.obligation_id = o.id {where}",
                     (), page)


def tab_counts(conn: sqlite3.Connection) -> dict[str, int]:
    return {tab: conn.execute(f"SELECT COUNT(*) FROM obligations o JOIN v_obligation_balance b "
                              f"ON b.obligation_id = o.id {_TAB_SQL[tab][0]}").fetchone()[0] for tab in TABS}


def payment_ledger(conn: sqlite3.Connection, page: int = 1) -> Page:
    """Every payment entry ever recorded, including voided ones (shown struck through)."""
    sql = """
        SELECT pe.*, o.invoice_id, o.currency, o.lifecycle AS obligation_lifecycle,
               s.name AS supplier_name, p.name AS property_name, i.invoice_number,
               (SELECT COUNT(*) FROM attachments a WHERE a.payment_entry_id = pe.id AND a.superseded_by IS NULL)
                   AS receipt_count
        FROM payment_entries pe
        JOIN obligations o ON o.id = pe.obligation_id
        JOIN suppliers s ON s.id = o.supplier_id
        JOIN properties p ON p.id = o.property_id
        LEFT JOIN invoices i ON i.id = o.invoice_id
        ORDER BY pe.paid_on DESC, pe.id DESC"""
    return _paginate(conn, sql, "SELECT COUNT(*) FROM payment_entries", (), page)


def change_log(conn: sqlite3.Connection, page: int = 1) -> Page:
    """Audit events with the invoice they belong to (when there is one), newest first."""
    sql = """
        SELECT e.*,
               CASE e.entity_type
                 WHEN 'invoice' THEN e.entity_id
                 WHEN 'obligation' THEN (SELECT invoice_id FROM obligations WHERE id = e.entity_id)
                 WHEN 'payment' THEN (SELECT o.invoice_id FROM payment_entries pe
                                      JOIN obligations o ON o.id = pe.obligation_id WHERE pe.id = e.entity_id)
                 WHEN 'attachment' THEN (SELECT COALESCE(a.invoice_id, o.invoice_id, po.invoice_id)
                                         FROM attachments a
                                         LEFT JOIN obligations o ON o.id = a.obligation_id
                                         LEFT JOIN payment_entries pe ON pe.id = a.payment_entry_id
                                         LEFT JOIN obligations po ON po.id = pe.obligation_id
                                         WHERE a.id = e.entity_id)
               END AS invoice_id
        FROM audit_events e
        ORDER BY e.occurred_at DESC, e.id DESC"""
    return _paginate(conn, sql, "SELECT COUNT(*) FROM audit_events", (), page)
