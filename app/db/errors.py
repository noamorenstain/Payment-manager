"""Translate database-level rule violations into Hebrew messages.

Integrity triggers raise ``RAISE(ABORT, 'pm:<code>')``. Services catch
``sqlite3.IntegrityError`` and use :func:`hebrew_message` so the user never sees raw
database text.
"""

from __future__ import annotations

import re
import sqlite3

from app.i18n import he

_CODE_RE = re.compile(r"pm:([a-z_]+)")


def error_code(exc: BaseException) -> str | None:
    match = _CODE_RE.search(str(exc))
    if match:
        return match.group(1)
    text = str(exc)
    if isinstance(exc, sqlite3.IntegrityError):
        if "FOREIGN KEY" in text:
            return "foreign_key"
        if "UNIQUE" in text:
            return "unique"
        if "CHECK" in text:
            return "check"
        if "NOT NULL" in text:
            return "not_null"
    return None


def hebrew_message(exc: BaseException) -> str:
    code = error_code(exc)
    return he.DB_ERRORS.get(code, he.DB_ERRORS["unknown"])
