"""Form parsing: collects every field error at once (Hebrew) instead of failing on the first."""

from __future__ import annotations

import datetime as dt
import re
import uuid

from starlette.datastructures import FormData, UploadFile

from app.domain import dates as d
from app.domain import money as m
from app.domain.errors import ValidationError
from app.i18n import he
from app.paths import DataPaths
from app.services import attachments
from app.services.attachments import StagedFile

_INT_RE = re.compile(r"^[0-9]{1,9}$")


def new_token() -> str:
    return uuid.uuid4().hex


class FormReader:
    def __init__(self, form: FormData):
        self.form = form
        self.errors: dict[str, str] = {}

    @property
    def values(self) -> dict[str, str]:
        """Raw text values to re-fill the form after an error."""
        return {k: v for k, v in self.form.items() if isinstance(v, str)}

    def text(self, name: str) -> str | None:
        value = self.form.get(name)
        if not isinstance(value, str):
            return None
        value = value.strip()
        return value or None

    def checkbox(self, name: str) -> bool:
        return self.form.get(name) in ("1", "on", "true", "yes")

    def _capture(self, name: str, fn):
        try:
            return fn()
        except ValidationError as exc:
            self.errors.setdefault(name, exc.message)
            return None

    def date(self, name: str, required: bool = True) -> dt.date | None:
        return self._capture(name, lambda: d.parse_he_date(self.form.get(name), name, required=required))

    def amount(self, name: str, required: bool = True) -> int | None:
        return self._capture(name, lambda: m.parse_amount(self.form.get(name), name, required=required))

    def int_id(self, name: str, required: bool = False, message: str | None = None) -> int | None:
        raw = self.text(name)
        if raw is None:
            if required:
                self.errors.setdefault(name, message or he.DB_ERRORS["not_null"])
            return None
        if not _INT_RE.match(raw):
            self.errors.setdefault(name, message or he.DB_ERRORS["check"])
            return None
        return int(raw)

    def int_range(self, name: str, lo: int, hi: int, message: str) -> int | None:
        raw = self.text(name)
        if raw is None:
            return None
        if not _INT_RE.match(raw) or not lo <= int(raw) <= hi:
            self.errors.setdefault(name, message)
            return None
        return int(raw)

    def choice(self, name: str, options, message: str) -> str | None:
        value = self.text(name)
        if value not in options:
            self.errors.setdefault(name, message)
            return None
        return value

    def add(self, exc: ValidationError, default_field: str = "_form") -> None:
        self.errors.setdefault(exc.field or default_field, exc.message)


def stage_file(reader: FormReader, paths: DataPaths, max_bytes: int, field: str = "file",
               token_field: str = "file_token") -> StagedFile | None:
    """A newly uploaded file, or one kept from a previous attempt of the same form."""
    upload = reader.form.get(field)
    if isinstance(upload, UploadFile) and upload.filename:
        try:
            return attachments.stage_upload(paths, upload.file, upload.filename, max_bytes, field)
        except ValidationError as exc:
            reader.add(exc, field)
            return None
    return attachments.load_staged(paths, reader.text(token_field))
