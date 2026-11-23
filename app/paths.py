"""Data-root folder layout.

All of these are siblings under one data root on one volume, so that restore can swap
``live\\`` using same-volume directory renames. ``live\\`` is never the parent of the
backup, staging or rollback folders.

    <data_root>\\
      live\\                      active data (DB + documents) — the only folder a restore swaps
        payment_manager.sqlite3
        invoices\\  receipts\\
      backups\\ daily\\ weekly\\ manual\\ pre-restore\\ pre-migration\\
      restore-staging\\
      restore-rollback\\
      logs\\
      app.lock
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

DB_FILENAME = "payment_manager.sqlite3"
BACKUP_KINDS = ("daily", "weekly", "manual", "pre-restore", "pre-migration")


@dataclass(frozen=True)
class DataPaths:
    root: Path

    @property
    def live(self) -> Path:
        return self.root / "live"

    @property
    def db_file(self) -> Path:
        return self.live / DB_FILENAME

    @property
    def invoices(self) -> Path:
        return self.live / "invoices"

    @property
    def receipts(self) -> Path:
        return self.live / "receipts"

    @property
    def backups(self) -> Path:
        return self.root / "backups"

    def backup_dir(self, kind: str) -> Path:
        if kind not in BACKUP_KINDS:
            raise ValueError(f"unknown backup kind: {kind}")
        return self.backups / kind

    @property
    def restore_staging(self) -> Path:
        return self.root / "restore-staging"

    @property
    def restore_rollback(self) -> Path:
        return self.root / "restore-rollback"

    @property
    def restore_journal(self) -> Path:
        return self.root / "restore-journal.json"

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    @property
    def lock_file(self) -> Path:
        return self.root / "app.lock"

    def all_dirs(self) -> list[Path]:
        return [
            self.root,
            self.live,
            self.invoices,
            self.receipts,
            self.backups,
            *(self.backup_dir(k) for k in BACKUP_KINDS),
            self.restore_staging,
            self.restore_rollback,
            self.logs,
        ]

    def ensure_layout(self) -> None:
        """Create any missing folders. Never deletes or moves anything."""
        for directory in self.all_dirs():
            directory.mkdir(parents=True, exist_ok=True)

    def is_inside_live(self, path: Path) -> bool:
        live = self.live.resolve()
        path = path.resolve()
        return path == live or live in path.parents
