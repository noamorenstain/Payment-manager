"""FastAPI dependencies shared by routes."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator

from fastapi import Request


def get_conn(request: Request) -> Iterator[sqlite3.Connection]:
    """One database connection per request, always closed afterwards."""
    db = request.app.state.db
    conn = db.connect()
    try:
        yield conn
    finally:
        db.close(conn)
