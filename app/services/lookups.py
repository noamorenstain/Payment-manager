"""Properties, suppliers and categories.

* Names must be unique among records (case/space-insensitive) so a name always identifies
  one record; an archived record with the same name is offered for restore instead.
* Archive hides a record from new-entry choices only. It never touches invoices,
  obligations, payments or documents that refer to it, and archived records stay visible
  in lists, filters and history. There is no deletion.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from app.clock import Clock
from app.i18n import he
from app.services import audit
from app.services.common import NotFound, clean_text, require, same_name, ts


@dataclass(frozen=True)
class LookupSpec:
    kind: str           # URL / audit entity name
    table: str
    fields: tuple       # editable text fields besides name


SPECS = {
    "properties": LookupSpec("property", "properties", ("country", "notes")),
    "suppliers": LookupSpec("supplier", "suppliers", ("contact", "customer_number", "notes")),
    "categories": LookupSpec("category", "categories", ()),
}


def spec(kind: str) -> LookupSpec:
    if kind not in SPECS:
        raise NotFound(kind)
    return SPECS[kind]


def list_all(conn: sqlite3.Connection, kind: str, include_archived: bool = True) -> list[sqlite3.Row]:
    s = spec(kind)
    where = "" if include_archived else "WHERE archived_at IS NULL"
    order = "is_general DESC, " if kind == "properties" else ""
    return conn.execute(f"SELECT * FROM {s.table} {where} ORDER BY {order}archived_at IS NOT NULL, name COLLATE NOCASE"
                        ).fetchall()


def active(conn: sqlite3.Connection, kind: str) -> list[sqlite3.Row]:
    return list_all(conn, kind, include_archived=False)


def get(conn: sqlite3.Connection, kind: str, item_id: int) -> sqlite3.Row:
    row = conn.execute(f"SELECT * FROM {spec(kind).table} WHERE id = ?", (item_id,)).fetchone()
    if row is None:
        raise NotFound(f"{kind} {item_id}")
    return row


def _find_same_name(conn, kind: str, name: str, exclude_id: int | None = None) -> sqlite3.Row | None:
    for row in conn.execute(f"SELECT * FROM {spec(kind).table}").fetchall():
        if row["id"] != exclude_id and same_name(row["name"], name):
            return row
    return None


def _validate_name(conn, kind: str, name: str | None, exclude_id: int | None = None) -> str:
    name = clean_text(name, 120)
    require(bool(name), he.LOOKUP_NAME_REQUIRED, "name")
    existing = _find_same_name(conn, kind, name, exclude_id)
    if existing is not None:
        message = he.LOOKUP_NAME_ARCHIVED if existing["archived_at"] else he.LOOKUP_NAME_EXISTS
        require(False, message.format(name=existing["name"]), "name")
    return name


def create(conn: sqlite3.Connection, clock: Clock, kind: str, name: str, **fields) -> int:
    s = spec(kind)
    name = _validate_name(conn, kind, name)
    values = {f: clean_text(fields.get(f), 500) for f in s.fields}
    cols = ["name", *values.keys(), "created_at", "updated_at"]
    now = ts(clock)
    new_id = conn.execute(
        f"INSERT INTO {s.table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
        (name, *values.values(), now, now)).lastrowid
    audit.record(conn, clock, s.kind, new_id, "create", new={"name": name, **values})
    return new_id


def update(conn: sqlite3.Connection, clock: Clock, kind: str, item_id: int, name: str, **fields) -> None:
    s = spec(kind)
    old = get(conn, kind, item_id)
    name = _validate_name(conn, kind, name, exclude_id=item_id)
    new = {"name": name, **{f: clean_text(fields.get(f), 500) for f in s.fields}}
    old_values = {k: old[k] for k in new}
    if old_values == new:
        return  # no-op updates are skipped (they would only bump the change counter)
    sets = ", ".join(f"{k} = ?" for k in new)
    conn.execute(f"UPDATE {s.table} SET {sets}, updated_at = ? WHERE id = ?", (*new.values(), ts(clock), item_id))
    old_c, new_c = audit.changed_fields(old_values, new)
    audit.record(conn, clock, s.kind, item_id, "update", old=old_c, new=new_c)


def set_archived(conn: sqlite3.Connection, clock: Clock, kind: str, item_id: int, archived: bool) -> None:
    s = spec(kind)
    row = get(conn, kind, item_id)
    if kind == "properties" and row["is_general"]:
        require(False, he.LOOKUP_GENERAL_CANNOT_ARCHIVE)
    if bool(row["archived_at"]) == archived:
        return
    if not archived:
        # restoring must not create a name clash with an active record
        clash = _find_same_name(conn, kind, row["name"], exclude_id=item_id)
        require(clash is None, he.LOOKUP_NAME_EXISTS.format(name=row["name"]))
    now = ts(clock)
    conn.execute(f"UPDATE {s.table} SET archived_at = ?, updated_at = ? WHERE id = ?",
                 (now if archived else None, now, item_id))
    audit.record(conn, clock, s.kind, item_id, "archive" if archived else "unarchive", details=row["name"])


def usage_count(conn: sqlite3.Connection, kind: str, item_id: int) -> int:
    column = {"properties": "property_id", "suppliers": "supplier_id", "categories": "category_id"}[kind]
    return conn.execute(f"SELECT COUNT(*) FROM obligations WHERE {column} = ?", (item_id,)).fetchone()[0]


def find_active_supplier(conn: sqlite3.Connection, name: str) -> sqlite3.Row | None:
    for row in active(conn, "suppliers"):
        if same_name(row["name"], name):
            return row
    return None


def resolve_or_create_supplier(conn: sqlite3.Connection, clock: Clock, name: str | None) -> int:
    """Supplier chosen from the searchable list, or created on the fly from a new name."""
    name = clean_text(name, 120)
    require(bool(name), he.SUPPLIER_REQUIRED, "supplier")
    existing = find_active_supplier(conn, name)
    if existing is not None:
        return existing["id"]
    archived = _find_same_name(conn, "suppliers", name)
    require(archived is None, he.LOOKUP_NAME_ARCHIVED.format(name=name), "supplier")
    return create(conn, clock, "suppliers", name)


def is_onboarding_needed(conn: sqlite3.Connection) -> bool:
    return (conn.execute("SELECT COUNT(*) FROM suppliers").fetchone()[0] == 0
            and conn.execute("SELECT COUNT(*) FROM properties WHERE is_general = 0").fetchone()[0] == 0
            and conn.execute("SELECT COUNT(*) FROM invoices").fetchone()[0] == 0)
