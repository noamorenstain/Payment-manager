"""Read-only integrity checks run at startup (and before backups in Phase E).

Never modifies data. Problems are reported to the UI as a Hebrew banner.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from app.i18n import he


@dataclass(frozen=True)
class IntegrityIssue:
    code: str
    message: str
    detail: str = ""


def run_integrity_checks(conn: sqlite3.Connection, full: bool = False) -> list[IntegrityIssue]:
    issues: list[IntegrityIssue] = []

    pragma = "integrity_check" if full else "quick_check"
    result = [r[0] for r in conn.execute(f"PRAGMA {pragma}").fetchall()]
    if result != ["ok"]:
        issues.append(IntegrityIssue("sqlite_corrupt", he.INTEGRITY_SQLITE, "; ".join(result[:5])))
        return issues  # further checks are meaningless on a damaged file

    fk = conn.execute("PRAGMA foreign_key_check").fetchall()
    if fk:
        issues.append(IntegrityIssue("foreign_keys", he.INTEGRITY_FOREIGN_KEYS, f"{len(fk)} rows"))

    if conn.execute("SELECT COUNT(*) FROM change_counter WHERE id = 1").fetchone()[0] != 1:
        issues.append(IntegrityIssue("change_counter", he.INTEGRITY_CHANGE_COUNTER))

    # invoice invariant: total = paid + canceled + outstanding (skip while an amount is missing)
    bad_invoices = conn.execute("""
        SELECT i.id, i.total_minor,
               SUM(b.paid_minor) + SUM(b.canceled_minor) + SUM(b.outstanding_minor) AS accounted
        FROM invoices i
        JOIN v_obligation_balance b ON b.invoice_id = i.id
        WHERE i.total_minor IS NOT NULL
        GROUP BY i.id
        HAVING SUM(b.amount_minor IS NULL) = 0 AND accounted <> i.total_minor
    """).fetchall()
    for row in bad_invoices:
        issues.append(IntegrityIssue("invoice_invariant", he.INTEGRITY_INVOICE_SUM,
                                     f"invoice {row['id']}: total {row['total_minor']} != {row['accounted']}"))

    # restructured parents: transferred amount == sum of child amounts
    bad_splits = conn.execute("""
        SELECT b.obligation_id, b.transferred_minor, COALESCE(SUM(c.amount_minor), 0) AS children
        FROM v_obligation_balance b
        LEFT JOIN obligations c ON c.parent_obligation_id = b.obligation_id
        WHERE b.lifecycle = 'restructured'
        GROUP BY b.obligation_id
        HAVING children <> b.transferred_minor
    """).fetchall()
    for row in bad_splits:
        issues.append(IntegrityIssue("restructure_sum", he.INTEGRITY_RESTRUCTURE_SUM,
                                     f"obligation {row['obligation_id']}: {row['transferred_minor']} != {row['children']}"))

    # unknown amounts only on variable recurring occurrences; a NULL invoice total only
    # when every linked obligation is such an occurrence still missing its amount
    bad_missing = conn.execute("""
        SELECT o.id FROM obligations o
        LEFT JOIN recurring_templates t ON t.id = o.recurring_template_id
        WHERE o.amount_minor IS NULL AND t.amount_mode IS NOT 'variable'
        UNION
        SELECT o.id FROM obligations o
        JOIN invoices i ON i.id = o.invoice_id
        WHERE i.total_minor IS NULL AND o.amount_minor IS NOT NULL
    """).fetchall()
    for row in bad_missing:
        issues.append(IntegrityIssue("missing_amount_rule", he.INTEGRITY_MISSING_AMOUNT, f"obligation {row['id']}"))

    # recurring templates: 'paused' exactly when an open pause row exists
    bad_pauses = conn.execute("""
        SELECT t.id FROM recurring_templates t
        WHERE (t.status = 'paused') <> EXISTS (
            SELECT 1 FROM recurring_pauses p WHERE p.template_id = t.id AND p.resumed_on IS NULL)
    """).fetchall()
    for row in bad_pauses:
        issues.append(IntegrityIssue("pause_state", he.INTEGRITY_PAUSE_STATE, f"template {row['id']}"))

    return issues
