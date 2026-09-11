from __future__ import annotations

import argparse
import json
from pathlib import Path

from .auditor import audit_repository
from .policy import parse_policy


# Suffixes whose content packs might actually need to read (README prose,
# policy YAML, and now FHIR's sushi-config.yaml/*.fsh/conformance JSON).
# Everything else is tracked by path only, which is all the hygiene checks need.
TEXT_SUFFIXES = {".md", ".rst", ".txt", ".yml", ".yaml", ".json", ".fsh", ".cff"}
MAX_TEXT_BYTES = 1_000_000  # skip content for anything unusually large
EXCLUDED_DIR_NAMES = {
    ".git",
    ".venv",
    "node_modules",
    ".next",
    ".open-next",
    ".wrangler",
    "dist",
    "build",
    "__pycache__",
    ".pytest_cache",
}


def scan_directory(root: Path) -> dict[str, str | None]:
    files: dict[str, str | None] = {}
    for path in root.rglob("*"):
        if not path.is_file() or EXCLUDED_DIR_NAMES & set(path.parts):
            continue
        relative = path.relative_to(root).as_posix()
        content = None
        if path.suffix.lower() in TEXT_SUFFIXES:
            try:
                if path.stat().st_size <= MAX_TEXT_BYTES:
                    content = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                content = None
        files[relative] = content
    return files


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Audit a public-health research repository."
    )
    parser.add_argument("path", nargs="?", default=".")
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Deprecated alias for --format json.",
    )
    parser.add_argument(
        "--format",
        choices=["md", "json", "sarif"],
        default=None,
        help="Output format for stdout (default: md, or json if --json is set).",
    )
    parser.add_argument(
        "--sarif",
        metavar="PATH",
        help="Also write a SARIF 2.1.0 report to PATH, for GitHub code scanning.",
    )
    parser.add_argument(
        "--pack",
        action="append",
        dest="packs",
        metavar="PACK_ID",
        help="Limit the audit to this pack id (repeatable). Default: every "
        "pack that detects itself on the repository.",
    )
    args = parser.parse_args(argv)

    root = Path(args.path).resolve()
    files = scan_directory(root)
    policy_content = files.get(".ph-repo-auditor.yml")
    if policy_content is None:
        policy_content = files.get(".ph-repo-auditor.yaml")
    policy, warnings = parse_policy(policy_content)
    packs = tuple(args.packs) if args.packs else None
    report = audit_repository(root.name, files, policy, warnings, packs=packs)

    if args.sarif:
        Path(args.sarif).write_text(json.dumps(report.to_sarif(), indent=2))

    output_format = args.format or ("json" if args.as_json else "md")
    if output_format == "json":
        print(json.dumps(report.to_dict(), indent=2))
    elif output_format == "sarif":
        print(json.dumps(report.to_sarif(), indent=2))
    else:
        print(report.to_markdown())
