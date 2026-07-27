from __future__ import annotations

import argparse
import json
from pathlib import Path

from .auditor import audit_repository


TEXT_FILE_NAMES = {
    "readme.md",
    "readme.rst",
    "data_dictionary.md",
    "data-dictionary.md",
    "codebook.md",
}


def scan_directory(root: Path) -> dict[str, str | None]:
    files: dict[str, str | None] = {}
    for path in root.rglob("*"):
        if not path.is_file() or ".git" in path.parts or ".venv" in path.parts:
            continue
        relative = path.relative_to(root).as_posix()
        content = None
        if path.name.lower() in TEXT_FILE_NAMES:
            content = path.read_text(encoding="utf-8", errors="replace")
        files[relative] = content
    return files


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Audit a public-health research repository."
    )
    parser.add_argument("path", nargs="?", default=".")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    root = Path(args.path).resolve()
    report = audit_repository(root.name, scan_directory(root))
    if args.as_json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(report.to_markdown())
