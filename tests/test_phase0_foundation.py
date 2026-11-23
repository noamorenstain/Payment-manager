"""Phase 0: launcher, data-root layout, single instance, Hebrew shell, offline assets."""

import re
import socket
from pathlib import Path

import pytest

from app import APP_NAME
from app.__main__ import probe
from app.config import AppConfig, default_data_root, is_inside_onedrive, load_config
from app.paths import BACKUP_KINDS, DataPaths
from app.single_instance import InstanceLock

APP_DIR = Path(__file__).resolve().parent.parent / "app"


# ---------- data root layout ----------

def test_layout_created_with_live_as_sibling(data_root):
    paths = DataPaths(data_root)
    paths.ensure_layout()
    for d in paths.all_dirs():
        assert d.is_dir(), d
    # live\ must never be the parent of backup / staging / rollback folders (restore safety)
    for other in [paths.backups, *(paths.backup_dir(k) for k in BACKUP_KINDS),
                  paths.restore_staging, paths.restore_rollback, paths.logs]:
        assert not paths.is_inside_live(other), other
        assert other.resolve().is_relative_to(paths.root.resolve())
    assert paths.db_file.parent == paths.live
    assert paths.is_inside_live(paths.invoices) and paths.is_inside_live(paths.receipts)


def test_ensure_layout_is_idempotent_and_non_destructive(data_root):
    paths = DataPaths(data_root)
    paths.ensure_layout()
    keep = paths.invoices / "2026" / "existing.pdf"
    keep.parent.mkdir(parents=True)
    keep.write_bytes(b"%PDF-1.4 test")
    paths.ensure_layout()
    assert keep.read_bytes() == b"%PDF-1.4 test"


def test_default_data_root_is_user_folder_not_onedrive(monkeypatch):
    monkeypatch.delenv("PM_DATA_ROOT", raising=False)
    root = default_data_root()
    assert root == Path.home() / "PaymentManagerData"


def test_onedrive_detection(monkeypatch, tmp_path):
    od = tmp_path / "OneDrive"
    (od / "Documents").mkdir(parents=True)
    monkeypatch.setenv("OneDrive", str(od))
    monkeypatch.delenv("OneDriveConsumer", raising=False)
    monkeypatch.delenv("OneDriveCommercial", raising=False)
    assert is_inside_onedrive(od / "Documents" / "PaymentManagerData")
    assert not is_inside_onedrive(tmp_path / "PaymentManagerData")


def test_config_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("PM_DATA_ROOT", str(tmp_path / "x"))
    monkeypatch.setenv("PM_PORT", "8123")
    cfg = load_config()
    assert cfg.data_root == (tmp_path / "x").resolve()
    assert cfg.port == 8123
    assert cfg.host == "127.0.0.1"


def test_config_invalid_port_falls_back(monkeypatch, tmp_path):
    monkeypatch.setenv("PM_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("PM_PORT", "80")
    assert load_config().port == 8000


# ---------- single instance ----------

def test_single_instance_lock(tmp_path):
    first = InstanceLock(tmp_path / "app.lock")
    second = InstanceLock(tmp_path / "app.lock")
    assert first.acquire()
    try:
        assert not second.acquire()
    finally:
        first.release()
    assert second.acquire()  # released lock can be taken again (no stale lock)
    second.release()


# ---------- launcher port probing ----------

def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_probe_free_port(tmp_path):
    assert probe(AppConfig(data_root=tmp_path, port=_free_port())) == "free"


def test_probe_detects_foreign_program(tmp_path):
    with socket.socket() as srv:
        srv.bind(("127.0.0.1", 0))
        srv.listen()
        port = srv.getsockname()[1]
        assert probe(AppConfig(data_root=tmp_path, port=port)) == "other"


# ---------- HTTP shell ----------

def test_health_signature(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["app"] == APP_NAME


def test_dashboard_is_hebrew_rtl(client):
    r = client.get("/")
    assert r.status_code == 200
    html = r.text
    assert '<html lang="he" dir="rtl">' in html
    assert "מנהל תשלומים" in html
    for label in ["לוח בקרה", "כל התשלומים", "חשבונית חדשה", "תשלומים קבועים", "היסטוריה", "הגדרות"]:
        assert label in html
    # today's date in DD/MM/YYYY from the injected clock
    assert "12/11/2026" in html
    assert "יום חמישי" in html


@pytest.mark.parametrize("path", ["/payments", "/invoices/new", "/recurring", "/history", "/settings"])
def test_nav_pages_render(client, path):
    r = client.get(path)
    assert r.status_code == 200
    assert 'aria-current="page"' in r.text


def test_404_is_hebrew(client):
    r = client.get("/no-such-page")
    assert r.status_code == 404
    assert "הדף לא נמצא" in r.text


def test_static_assets_served(client):
    assert client.get("/static/css/app.css").status_code == 200
    assert client.get("/static/img/icon.ico").status_code == 200


def test_api_docs_disabled(client):
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404


# ---------- offline guarantee ----------

def test_no_external_urls_in_ui_assets():
    pattern = re.compile(r"(?:https?:)?//[a-z0-9.-]+\.[a-z]{2,}", re.IGNORECASE)
    offenders = []
    for path in list((APP_DIR / "templates").rglob("*")) + list((APP_DIR / "static").rglob("*")):
        if path.suffix in {".html", ".css", ".js"}:
            for m in pattern.finditer(path.read_text(encoding="utf-8")):
                offenders.append(f"{path.name}: {m.group(0)}")
    assert not offenders, offenders
