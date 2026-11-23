"""Launcher: ``python -m app``.

1. If Payment Manager is already running on the configured port, just open the browser.
2. If the port is taken by a different program, show a Hebrew error and exit.
3. Otherwise take the single-instance lock, start the server on 127.0.0.1 only,
   and open the default browser once the server answers.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser

from app import APP_NAME, __version__
from app.config import AppConfig, app_settings_dir, is_inside_onedrive, load_config
from app.i18n import he
from app.logging_setup import setup_logging
from app.paths import DataPaths
from app.single_instance import InstanceLock

log = logging.getLogger("app.launcher")

EXIT_OK, EXIT_PORT_IN_USE, EXIT_START_FAILED = 0, 2, 3


def message_box(text: str, error: bool = True) -> None:
    """Show a right-to-left Windows message box (falls back to stderr elsewhere)."""
    if os.name == "nt":
        try:
            import ctypes

            MB_ICONERROR, MB_ICONWARNING = 0x10, 0x30
            MB_RIGHT, MB_RTLREADING = 0x80000, 0x100000
            flags = (MB_ICONERROR if error else MB_ICONWARNING) | MB_RIGHT | MB_RTLREADING
            ctypes.windll.user32.MessageBoxW(None, text, he.APP_TITLE, flags)
            return
        except Exception:  # pragma: no cover
            pass
    print(text, file=sys.stderr)


def set_console_title(title: str) -> None:
    if os.name == "nt":
        try:
            import ctypes

            ctypes.windll.kernel32.SetConsoleTitleW(title)
        except Exception:  # pragma: no cover
            pass


def probe(config: AppConfig) -> str:
    """Return 'ours' if our app answers on the port, 'other' if something else does, 'free' if nothing."""
    try:
        with urllib.request.urlopen(config.base_url + "/health", timeout=1.5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return "ours" if data.get("app") == APP_NAME else "other"
    except (urllib.error.URLError, OSError, ValueError):
        pass
    # Nothing speaking our protocol; is the port bound at all?
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return "other" if s.connect_ex((config.host, config.port)) == 0 else "free"


def wait_until_ready(config: AppConfig, timeout: float = 20.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if probe(config) == "ours":
            return True
        time.sleep(0.25)
    return False


def open_browser(config: AppConfig) -> None:
    webbrowser.open(config.base_url + "/")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app", description="Payment Manager local server")
    parser.add_argument("--no-browser", action="store_true", help="do not open the browser")
    parser.add_argument("--init-only", action="store_true", help="create the data folders and exit")
    args = parser.parse_args(argv)

    config = load_config()
    paths = DataPaths(config.data_root)

    if args.init_only:
        paths.ensure_layout()
        print(f"Data folder ready: {paths.root}")
        return EXIT_OK

    state = probe(config)
    if state == "ours":
        if not args.no_browser:
            open_browser(config)
        return EXIT_OK
    if state == "other":
        message_box(he.LAUNCH_PORT_IN_USE.format(port=config.port,
                                                 config_path=app_settings_dir() / "config.json"))
        return EXIT_PORT_IN_USE

    paths.ensure_layout()
    lock = InstanceLock(paths.lock_file)
    if not lock.acquire():
        # Another launcher is starting the server right now; wait for it instead.
        if wait_until_ready(config) and not args.no_browser:
            open_browser(config)
        return EXIT_OK

    try:
        setup_logging(paths.logs)
        set_console_title(he.CONSOLE_TITLE)
        log.info("Starting Payment Manager %s on %s", __version__, config.base_url)
        if is_inside_onedrive(paths.root):
            log.warning("Data root is inside OneDrive: %s", paths.root)
            message_box(he.LAUNCH_ONEDRIVE_WARNING.format(path=paths.root), error=False)

        import uvicorn

        from app.main import create_app

        from app.db.migrate import SchemaTooNewError

        try:
            app = create_app(config)
        except SchemaTooNewError:
            log.exception("Database schema is newer than this program")
            message_box(he.LAUNCH_SCHEMA_TOO_NEW)
            return EXIT_START_FAILED
        server = uvicorn.Server(uvicorn.Config(
            app, host=config.host, port=config.port, log_config=None, access_log=False,
        ))

        if not args.no_browser:
            def _open_when_started():
                deadline = time.monotonic() + 30
                while not server.started and time.monotonic() < deadline:
                    time.sleep(0.1)
                if server.started:
                    open_browser(config)

            threading.Thread(target=_open_when_started, daemon=True).start()

        print(f"Payment Manager is running at {config.base_url}  (close this window to stop)")
        server.run()
        if not server.started:
            raise RuntimeError("server failed to start")
        log.info("Payment Manager stopped")
        return EXIT_OK
    except Exception:
        log.exception("Payment Manager failed to start")
        message_box(he.LAUNCH_START_FAILED.format(log_path=paths.logs / "app.log"))
        return EXIT_START_FAILED
    finally:
        lock.release()


if __name__ == "__main__":
    sys.exit(main())
