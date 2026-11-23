"""Exit 0 if every pinned requirement (name==version) is already installed, else 1.

Used by install.ps1 so that re-running the installer works offline and does not touch
an environment that is already complete. Follows "-r other.txt" includes.
Usage: python scripts/check_requirements.py requirements.txt
"""

from __future__ import annotations

import re
import sys
from importlib import metadata
from pathlib import Path


def _normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def pinned(path: Path, seen: set[Path] | None = None) -> dict[str, str]:
    seen = seen or set()
    path = path.resolve()
    if path in seen:
        return {}
    seen.add(path)
    result: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("-r "):
            result.update(pinned(path.parent / line[3:].strip(), seen))
            continue
        name, sep, version = line.partition("==")
        if not sep:
            raise SystemExit(f"unpinned requirement: {line}")
        result[_normalize(name)] = version.strip()
    return result


def missing(requirements: dict[str, str]) -> list[str]:
    problems = []
    for name, version in requirements.items():
        try:
            installed = metadata.version(name)
        except metadata.PackageNotFoundError:
            problems.append(f"{name} (not installed)")
            continue
        if installed != version:
            problems.append(f"{name} {installed} != {version}")
    return problems


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    problems = missing(pinned(Path(argv[1])))
    for p in problems:
        print(p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
