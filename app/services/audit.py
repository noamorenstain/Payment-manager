"""Append-only audit trail. Always called inside the same transaction as the change."""

from __future__ import annotations

import json
import sqlite3

from app.clock import Clock
from app.services.common import ts


def _dump(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, sqlite3.Row):
        value = dict(value)
    return json.dumps(value, ensure_ascii=False, default=str, sort_keys=True)


def record(conn: sqlite3.Connection, clock: Clock, entity_type: str, entity_id: int | None, action: str,
           old=None, new=None, details: str | None = None) -> int:
    return conn.execute(
        "INSERT INTO audit_events (entity_type, entity_id, action, occurred_at, old_json, new_json, details) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (entity_type, entity_id, action, ts(clock), _dump(old), _dump(new), details)).lastrowid


def changed_fields(old: dict, new: dict) -> tuple[dict, dict]:
    """Only the keys whose values differ (for compact old/new audit records)."""
    keys = [k for k in new if old.get(k) != new.get(k)]
    return {k: old.get(k) for k in keys}, {k: new.get(k) for k in keys}


def for_invoice(conn: sqlite3.Connection, invoice_id: int) -> list[sqlite3.Row]:
    """All audit events that belong to an invoice and its obligations, payments and documents."""
    return conn.execute("""
        SELECT * FROM audit_events e
        WHERE (e.entity_type = 'invoice' AND e.entity_id = :inv)
           OR (e.entity_type = 'obligation' AND e.entity_id IN (SELECT id FROM obligations WHERE invoice_id = :inv))
           OR (e.entity_type = 'payment' AND e.entity_id IN (
                 SELECT pe.id FROM payment_entries pe JOIN obligations o ON o.id = pe.obligation_id
                 WHERE o.invoice_id = :inv))
           OR (e.entity_type = 'attachment' AND e.entity_id IN (
                 SELECT a.id FROM attachments a
                 LEFT JOIN obligations o ON o.id = a.obligation_id
                 LEFT JOIN payment_entries pe ON pe.id = a.payment_entry_id
                 LEFT JOIN obligations po ON po.id = pe.obligation_id
                 WHERE a.invoice_id = :inv OR o.invoice_id = :inv OR po.invoice_id = :inv))
        ORDER BY e.occurred_at DESC, e.id DESC
    """, {"inv": invoice_id}).fetchall()
