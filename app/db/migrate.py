"""Schema migrations.

* Migrations are numbered ``NNNN_name.sql`` files in ``app/db/migrations``; the applied
  version is stored in ``PRAGMA user_version``.
* Each migration runs in ONE transaction together with the ``user_version`` bump, so a
  failure leaves the database exactly as it was.
* Before upgrading a database that already holds data, a consistent snapshot is written to
  ``backups/pre-migration`` using SQLite's online backup API (never a raw file copy).
  Documents are not touched by migrations, so the database snapshot is sufficient here;
  full ZIP backups arrive in Phase E.
* A database newer than this program is refused rather than modified.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from app.db.connection import Database

log = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
_NAME_RE = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")


class SchemaTooNewError(RuntimeError):
    def __init__(self, db_version: int, app_version: int):
        super().__init__(f"database schema v{db_version} is newer than this program (v{app_version})")
        self.db_version = db_version
        self.app_version = app_version


class MigrationError(RuntimeError):
    pass


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    path: Path

    def statements(self) -> list[str]:
        return split_sql(self.path.read_text(encoding="utf-8"))


def discover(migrations_dir: Path = MIGRATIONS_DIR) -> list[Migration]:
    found = []
    for path in sorted(migrations_dir.glob("*.sql")):
        match = _NAME_RE.match(path.name)
        if not match:
            raise MigrationError(f"badly named migration file: {path.name}")
        found.append(Migration(int(match.group(1)), path.stem, path))
    versions = [m.version for m in found]
    if versions != list(range(1, len(found) + 1)):
        raise MigrationError(f"migrations must be numbered 0001.. without gaps, found {versions}")
    return found


def split_sql(script: str) -> list[str]:
    """Split a script into complete statements (trigger bodies containing ';' stay intact)."""
    statements, buffer = [], ""
    for line in script.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            stmt = buffer.strip()
            if _strip_comments(stmt):
                statements.append(stmt)
            buffer = ""
    if _strip_comments(buffer).strip():
        raise MigrationError("migration ends with an incomplete statement")
    return statements


def _strip_comments(sql: str) -> str:
    return "\n".join(l for l in sql.splitlines() if not l.strip().startswith("--")).strip().rstrip(";").strip()


def current_version(conn: sqlite3.Connection) -> int:
    return conn.execute("PRAGMA user_version").fetchone()[0]


def snapshot_database(source: sqlite3.Connection, target_path: Path) -> Path:
    """Consistent copy of a live database via the online backup API, then verified."""
    target_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = target_path.with_suffix(target_path.suffix + ".tmp")
    if tmp.exists():
        tmp.unlink()
    dest = sqlite3.connect(str(tmp))
    try:
        source.backup(dest)
        result = dest.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            raise MigrationError(f"pre-migration snapshot failed integrity check: {result}")
    finally:
        dest.close()
    tmp.replace(target_path)
    return target_path


def migrate(db: Database, backup_dir: Path | None = None, now_label: str | None = None,
            migrations_dir: Path = MIGRATIONS_DIR) -> dict:
    """Bring the database up to date. Returns {'from': v, 'to': v, 'backup': path|None}."""
    migrations = discover(migrations_dir)
    latest = migrations[-1].version if migrations else 0

    with db.connection() as conn:
        version = current_version(conn)
        if version > latest:
            raise SchemaTooNewError(version, latest)
        pending = [m for m in migrations if m.version > version]
        if not pending:
            return {"from": version, "to": version, "backup": None}

        backup_path = None
        if version > 0 and backup_dir is not None:
            label = now_label or "snapshot"
            backup_path = snapshot_database(
                conn, backup_dir / f"pre-migration-v{version}-to-v{latest}-{label}.sqlite3")
            log.info("Pre-migration snapshot written: %s", backup_path)

        for migration in pending:
            log.info("Applying migration %s", migration.name)
            conn.execute("BEGIN IMMEDIATE")
            try:
                for statement in migration.statements():
                    conn.execute(statement)
                conn.execute(f"PRAGMA user_version = {migration.version:d}")
                conn.execute("COMMIT")
            except Exception as exc:
                conn.execute("ROLLBACK")
                raise MigrationError(f"migration {migration.name} failed: {exc}") from exc

        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise MigrationError(f"foreign key violations after migration: {len(violations)}")
        return {"from": version, "to": current_version(conn), "backup": backup_path}


def latest_version(migrations_dir: Path = MIGRATIONS_DIR) -> int:
    migrations = discover(migrations_dir)
    return migrations[-1].version if migrations else 0
