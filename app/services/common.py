"""Helpers shared by services."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from app.clock import Clock
from app.domain.errors import ValidationError


def ts(clock: Clock) -> str:
    """Timestamp in the stored format 'YYYY-MM-DD HH:MM:SS' (local time)."""
    return clock.now().strftime("%Y-%m-%d %H:%M:%S")


class NotFound(LookupError):
    pass


@dataclass
class NeedsConfirmation(Exception):
    """Raised when the action is valid but has warnings the user must explicitly confirm."""

    warnings: list[str] = field(default_factory=list)


def one(conn: sqlite3.Connection, sql: str, params=()) -> sqlite3.Row:
    row = conn.execute(sql, params).fetchone()
    if row is None:
        raise NotFound(sql)
    return row


def require(condition: bool, message: str, field_name: str | None = None) -> None:
    if not condition:
        raise ValidationError(message, field_name)


def clean_text(value: str | None, max_len: int = 500) -> str | None:
    """Trim; empty → None; cap length."""
    if value is None:
        return None
    value = value.strip()[:max_len].strip()
    return value or None


def same_name(a: str, b: str) -> bool:
    return " ".join(a.split()).casefold() == " ".join(b.split()).casefold()
