"""Document storage (plan §8).

* Accepted: PDF, JPG/JPEG, PNG — checked by extension AND by the file's first bytes.
* Uploads are first written to ``live/.uploads-tmp`` ("staged"), so a form that fails
  validation can be re-shown without asking the user to pick the file again.
* On save the staged file is moved (same volume, atomic) to
  ``live/invoices|receipts/YYYY/<uuid>.<ext>`` and stored unmodified; the database keeps the
  original name, MIME type, size and SHA-256. The file is in place before the database row
  that references it is committed.
* Stored documents are never modified or deleted. "Replace" adds a new version and marks the
  old one as superseded; both stay viewable.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

from app.clock import Clock
from app.domain.errors import ValidationError
from app.i18n import he
from app.paths import DataPaths
from app.services import audit
from app.services.common import NotFound, ts

TYPES = {
    "pdf": ("application/pdf", (b"%PDF-",)),
    "png": ("image/png", (b"\x89PNG\r\n\x1a\n",)),
    "jpg": ("image/jpeg", (b"\xff\xd8\xff",)),
    "jpeg": ("image/jpeg", (b"\xff\xd8\xff",)),
}
ACCEPT_ATTR = ".pdf,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png"
_TOKEN_RE = re.compile(r"^[0-9a-f]{32}$")
_CHUNK = 1024 * 1024


@dataclass
class StagedFile:
    token: str
    original_name: str
    ext: str
    mime: str
    size_bytes: int
    sha256: str


def staging_dir(paths: DataPaths) -> Path:
    return paths.live / ".uploads-tmp"


def _staged_paths(paths: DataPaths, token: str, ext: str) -> tuple[Path, Path]:
    base = staging_dir(paths)
    return base / f"{token}.{ext}", base / f"{token}.json"


def safe_original_name(name: str | None) -> str:
    """Keep only the final path component; strip control characters."""
    name = (name or "").replace("\\", "/").split("/")[-1]
    name = "".join(ch for ch in name if ch.isprintable()).strip()
    return name[:200] or "document"


def max_upload_bytes(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT value FROM settings WHERE key = 'max_upload_mb'").fetchone()
    try:
        mb = int(row["value"]) if row else 25
    except ValueError:
        mb = 25
    return max(1, mb) * 1024 * 1024


def stage_upload(paths: DataPaths, fileobj, original_name: str, max_bytes: int,
                 field: str = "file") -> StagedFile:
    """Validate and store an uploaded file temporarily. Raises ValidationError (Hebrew)."""
    original_name = safe_original_name(original_name)
    ext = original_name.rsplit(".", 1)[-1].lower() if "." in original_name else ""
    if ext not in TYPES:
        raise ValidationError(he.FILE_BAD_TYPE, field)
    mime, signatures = TYPES[ext]

    token = uuid.uuid4().hex
    data_path, meta_path = _staged_paths(paths, token, ext)
    data_path.parent.mkdir(parents=True, exist_ok=True)
    part = data_path.with_suffix(data_path.suffix + ".part")
    digest, size, head = hashlib.sha256(), 0, b""
    try:
        with open(part, "wb") as out:
            while True:
                chunk = fileobj.read(_CHUNK)
                if not chunk:
                    break
                if not head:
                    head = chunk[:16]
                size += len(chunk)
                if size > max_bytes:
                    raise ValidationError(he.FILE_TOO_LARGE.format(mb=max_bytes // (1024 * 1024)), field)
                digest.update(chunk)
                out.write(chunk)
            out.flush()
            os.fsync(out.fileno())
        if size == 0:
            raise ValidationError(he.FILE_EMPTY, field)
        if not any(head.startswith(sig) for sig in signatures):
            raise ValidationError(he.FILE_CONTENT_MISMATCH, field)
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    part.replace(data_path)
    staged = StagedFile(token, original_name, ext, mime, size, digest.hexdigest())
    meta_path.write_text(json.dumps(asdict(staged), ensure_ascii=False), encoding="utf-8")
    return staged


def load_staged(paths: DataPaths, token: str | None) -> StagedFile | None:
    """Look up a staged upload by its token (strictly validated; never a path)."""
    if not token or not _TOKEN_RE.match(token):
        return None
    meta = staging_dir(paths) / f"{token}.json"
    if not meta.is_file():
        return None
    try:
        staged = StagedFile(**json.loads(meta.read_text(encoding="utf-8")))
    except (ValueError, TypeError):
        return None
    if staged.token != token or staged.ext not in TYPES:
        return None
    data_path, _ = _staged_paths(paths, token, staged.ext)
    return staged if data_path.is_file() else None


def duplicates_by_hash(conn: sqlite3.Connection, sha256: str) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM attachments WHERE sha256 = ? ORDER BY id", (sha256,)).fetchall()


def commit_staged(conn: sqlite3.Connection, paths: DataPaths, clock: Clock, staged: StagedFile, *,
                  invoice_id: int | None = None, obligation_id: int | None = None,
                  payment_entry_id: int | None = None, kind: str = "invoice",
                  duplicate_override: bool = False) -> int:
    """Move a staged file into permanent storage and record it. Call inside a transaction."""
    folder = "receipts" if kind == "receipt" else "invoices"
    year = clock.today().year
    relative = f"{folder}/{year}/{uuid.uuid4().hex}.{staged.ext}"
    target = paths.live / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    source, meta = _staged_paths(paths, staged.token, staged.ext)
    if not source.is_file():
        raise ValidationError(he.FILE_STAGED_MISSING, "file")
    if _sha256(source) != staged.sha256:
        raise ValidationError(he.FILE_STAGED_MISSING, "file")
    os.replace(source, target)  # same volume: atomic; the original bytes are kept unmodified
    try:
        now = ts(clock)
        att_id = conn.execute(
            "INSERT INTO attachments (invoice_id, obligation_id, payment_entry_id, kind, original_name, stored_path, "
            "mime, size_bytes, sha256, duplicate_override, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (invoice_id, obligation_id, payment_entry_id, kind, staged.original_name, relative, staged.mime,
             staged.size_bytes, staged.sha256, int(duplicate_override), now, now)).lastrowid
    except BaseException:
        os.replace(target, source)  # put the upload back so nothing is orphaned
        raise
    meta.unlink(missing_ok=True)
    audit.record(conn, clock, "attachment", att_id, "attachment_added",
                 new={"original_name": staged.original_name, "kind": kind, "sha256": staged.sha256,
                      "size_bytes": staged.size_bytes})
    return att_id


def supersede(conn: sqlite3.Connection, clock: Clock, old_id: int, new_id: int) -> None:
    old = get(conn, old_id)
    if old["superseded_by"] is not None:
        raise ValidationError(he.DB_ERRORS["attachment_already_superseded"])
    conn.execute("UPDATE attachments SET superseded_by = ?, updated_at = ? WHERE id = ?", (new_id, ts(clock), old_id))
    audit.record(conn, clock, "attachment", old_id, "attachment_replaced",
                 old={"original_name": old["original_name"]}, new={"superseded_by": new_id})


def get(conn: sqlite3.Connection, att_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM attachments WHERE id = ?", (att_id,)).fetchone()
    if row is None:
        raise NotFound(f"attachment {att_id}")
    return row


def file_path(paths: DataPaths, row: sqlite3.Row) -> Path:
    """Absolute path of a stored document, guaranteed to be inside live/invoices|receipts."""
    target = (paths.live / row["stored_path"]).resolve()
    allowed = [(paths.live / "invoices").resolve(), (paths.live / "receipts").resolve()]
    if not any(root in target.parents for root in allowed):
        raise NotFound("attachment path outside storage")
    if not target.is_file():
        raise NotFound("attachment file missing")
    return target


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_file(paths: DataPaths, row: sqlite3.Row) -> bool:
    try:
        return _sha256(file_path(paths, row)) == row["sha256"]
    except NotFound:
        return False
