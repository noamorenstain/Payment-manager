"""Application configuration: data root location and port.

The data root defaults to ``%USERPROFILE%\\PaymentManagerData`` (deliberately outside
OneDrive-synced folders). It can be overridden by:

1. The ``PM_DATA_ROOT`` / ``PM_PORT`` environment variables (used by tests).
2. ``%LOCALAPPDATA%\\PaymentManager\\config.json`` with keys ``data_root`` and ``port``.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_PORT = 8000
HOST = "127.0.0.1"  # Never bind to 0.0.0.0: the app must not be reachable from the network.

log = logging.getLogger(__name__)


def app_settings_dir() -> Path:
    """Folder for machine-level launcher config (not user financial data)."""
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "PaymentManager"


def default_data_root() -> Path:
    return Path.home() / "PaymentManagerData"


@dataclass(frozen=True)
class AppConfig:
    data_root: Path
    port: int = DEFAULT_PORT
    host: str = HOST

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"


def _read_config_file() -> dict:
    path = app_settings_dir() / "config.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError) as exc:
        log.warning("Ignoring unreadable config file %s: %s", path, exc)
        return {}


def _parse_port(value) -> int:
    port = int(value)
    if not 1024 <= port <= 65535:
        raise ValueError(f"port out of range: {port}")
    return port


def load_config() -> AppConfig:
    file_cfg = _read_config_file()

    data_root_raw = os.environ.get("PM_DATA_ROOT") or file_cfg.get("data_root")
    data_root = Path(data_root_raw).expanduser() if data_root_raw else default_data_root()

    port_raw = os.environ.get("PM_PORT") or file_cfg.get("port") or DEFAULT_PORT
    try:
        port = _parse_port(port_raw)
    except (TypeError, ValueError):
        log.warning("Invalid port %r, falling back to %s", port_raw, DEFAULT_PORT)
        port = DEFAULT_PORT

    return AppConfig(data_root=data_root.resolve(), port=port)


def onedrive_roots() -> list[Path]:
    """All OneDrive folders known from the environment (personal and business)."""
    roots = []
    for var in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        value = os.environ.get(var)
        if value:
            roots.append(Path(value).resolve())
    return roots


def is_inside_onedrive(path: Path) -> bool:
    path = path.resolve()
    return any(path == root or root in path.parents for root in onedrive_roots())
