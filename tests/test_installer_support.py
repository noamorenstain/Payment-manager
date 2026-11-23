"""Installer support: the requirement check that lets install.bat re-run safely and offline."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("check_requirements", ROOT / "scripts" / "check_requirements.py")
check_requirements = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_requirements)


def test_project_requirements_are_fully_pinned():
    req = check_requirements.pinned(ROOT / "requirements-dev.txt")
    for name in ("fastapi", "uvicorn", "jinja2", "python-multipart", "openpyxl", "pytest"):
        assert name in req
    assert all(req.values())


def test_current_environment_satisfies_lock():
    # The environment the tests run in must match the pinned lock exactly.
    assert check_requirements.missing(check_requirements.pinned(ROOT / "requirements-dev.txt")) == []


def test_include_and_name_normalisation(tmp_path):
    (tmp_path / "base.txt").write_text("Jinja2==3.1.6  # comment\n\ntyping_extensions==4.16.0\n", encoding="utf-8")
    (tmp_path / "dev.txt").write_text("-r base.txt\npytest==9.2.0\n", encoding="utf-8")
    req = check_requirements.pinned(tmp_path / "dev.txt")
    assert req == {"jinja2": "3.1.6", "typing-extensions": "4.16.0", "pytest": "9.2.0"}


def test_detects_missing_and_wrong_versions():
    problems = check_requirements.missing({"pytest": "0.0.1", "surely-not-installed-pkg": "1.0"})
    assert any(p.startswith("pytest") for p in problems)
    assert any("not installed" in p for p in problems)


def test_unpinned_requirement_rejected(tmp_path):
    (tmp_path / "r.txt").write_text("fastapi>=0.1\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        check_requirements.pinned(tmp_path / "r.txt")


def test_installer_script_is_ascii_only():
    # Windows PowerShell 5.1 reads BOM-less scripts in the ANSI code page; Hebrew must be
    # built from code points, never typed literally into the file.
    for name in ("scripts/install.ps1", "install.bat", "start.bat"):
        (ROOT / name).read_bytes().decode("ascii")
