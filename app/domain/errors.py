"""Validation errors carrying a user-facing Hebrew message."""

from __future__ import annotations


class ValidationError(ValueError):
    """Raised for invalid user input. ``message`` is Hebrew and safe to show to the user."""

    def __init__(self, message: str, field: str | None = None):
        super().__init__(message)
        self.message = message
        self.field = field
