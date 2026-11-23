"""SQLite connections: mandatory PRAGMAs, explicit transactions, open-connection registry.

* Connections run in autocommit mode (``isolation_level=None``); every multi-statement
  change must use :func:`transaction`, which issues ``BEGIN IMMEDIATE`` so a write lock is
  taken up-front and the whole unit commits or rolls back together.
* ``foreign_keys`` is per-connection in SQLite, so it is enabled on every connection.
* The registry lets a future restore (Phase E) verify that every connection is closed
  before swapping the data folder.
"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._open: set[int] = set()

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(
            str(self.path),
            isolation_level=None,       # explicit transactions only
            timeout=5.0,
            check_same_thread=False,    # FastAPI may run a request's dependency and endpoint on different threads
            detect_types=0,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = FULL")
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA recursive_triggers = OFF")
        if conn.execute("PRAGMA foreign_keys").fetchone()[0] != 1:  # pragma: no cover
            conn.close()
            raise RuntimeError("SQLite foreign keys could not be enabled")
        with self._lock:
            self._open.add(id(conn))
        return conn

    def close(self, conn: sqlite3.Connection) -> None:
        with self._lock:
            self._open.discard(id(conn))
        conn.close()

    @property
    def open_connections(self) -> int:
        with self._lock:
            return len(self._open)

    @contextmanager
    def connection(self):
        conn = self.connect()
        try:
            yield conn
        finally:
            self.close(conn)


@contextmanager
def transaction(conn: sqlite3.Connection):
    """All-or-nothing unit of work (BEGIN IMMEDIATE … COMMIT / ROLLBACK)."""
    if conn.in_transaction:
        raise RuntimeError("nested transactions are not supported")
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")
