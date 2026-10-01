from __future__ import annotations

import csv
import io
import re

from ..models import TOOL_URI, AuditPolicy, Finding
from .base import RepoView

# Column-name clusters that, together, look like person-level health data
# rather than aggregate/reference data. A single hit (e.g. a "name" column
# in a lookup table) is not suspicious on its own; several together are.
_IDENTITY_COLUMNS = {
    "name", "full_name", "fullname", "first_name", "last_name", "patient_name",
}
_DOB_COLUMNS = {
    "dob", "date_of_birth", "birth_date", "birthdate",
}
_HEALTH_COLUMNS = {
    "diagnosis", "condition", "icd10", "icd_10", "symptom", "symptoms",
    "treatment", "medication", "lab_result", "hiv_status", "disease",
}
_CONTACT_COLUMNS = {
    "address", "phone", "phone_number", "mobile", "email", "national_id",
    "nid", "passport", "mrn", "patient_id", "ssn",
}
_COLUMN_CLUSTERS = (_IDENTITY_COLUMNS, _DOB_COLUMNS, _HEALTH_COLUMNS, _CONTACT_COLUMNS)
# At least this many *distinct* clusters must have a hit before a file is
# flagged — keeps a single "name" column in an org-unit lookup table quiet.
_MIN_CLUSTERS_HIT = 3

# A path containing any of these is presumed deliberately synthetic/test
# data, not a real patient-data leak.
_SYNTHETIC_PATH_MARKERS = (
    "test", "fixture", "fixtures", "synthetic", "sample", "mock", "example",
    "demo", "seed_data/fake",
)

_ENV_VALUE_RE = re.compile(
    r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+?)\s*$"
)
# Values that are clearly placeholders, not real committed secrets.
_PLACEHOLDER_VALUE_RE = re.compile(
    r"^(|['\"]?(xxx+|changeme|your[-_].*|replace[-_].*|<.*>|\$\{.*\}|placeholder.*)['\"]?)$",
    re.IGNORECASE,
)

_DESTRUCTIVE_SQL_SIZE_THRESHOLD = 20_000  # bytes of raw SQL content

_MIGRATION_DIR_NAMES = {"migration", "migrations", "migrate"}


def _is_migrations_path(path: str) -> bool:
    """Whether `path` sits under a conventional migration directory —
    matches directory segments exactly, not a loose substring, so this
    pack's own `pii/db-dump-committed` rule doesn't accidentally treat an
    unrelated file (or this project's own source) as migration-adjacent
    just because "migrat" appears somewhere in its path."""
    segments = [segment.lower() for segment in path.split("/")[:-1]]
    if any(segment in _MIGRATION_DIR_NAMES for segment in segments):
        return True
    return "alembic" in segments and "versions" in segments


def _is_synthetic_path(path: str) -> bool:
    lowered = path.lower()
    return any(marker in lowered for marker in _SYNTHETIC_PATH_MARKERS)


def _is_env_path(path: str) -> bool:
    name = path.rsplit("/", 1)[-1].lower()
    if name in {".env.example", ".env.sample", ".env.template", ".env.dist"}:
        return False
    return name == ".env" or name.startswith(".env.")


def _is_pii_relevant_path(path: str) -> bool:
    """Name-only guess for callers (the GitHub App client) deciding what to
    fetch before seeing content."""
    name = path.rsplit("/", 1)[-1].lower()
    if _is_env_path(path):
        return True
    return name.endswith((".csv", ".sql", ".dump", ".bak"))


def _parse_csv_header(content: str) -> list[str] | None:
    first_line = content.splitlines()[0] if content.splitlines() else ""
    if not first_line:
        return None
    try:
        row = next(csv.reader(io.StringIO(first_line)))
    except csv.Error:
        return None
    return [cell.strip().lower() for cell in row]


class PiiPack:
    """Cross-cutting checks that apply to any repository, not just ones that
    match a specific platform. Catches the auditor's own core privacy
    concern: real or realistic person-level health data, and secrets,
    committed to source control.
    """

    id = "pii"

    def detect(self, repo: RepoView) -> float:
        return 1.0

    def run(self, repo: RepoView, policy: AuditPolicy) -> list[Finding]:
        findings: list[Finding] = []
        findings.extend(self._patient_data_findings(repo))
        findings.extend(self._env_value_findings(repo))
        findings.extend(self._db_dump_findings(repo))
        return findings

    # -- patient-data-in-repo --------------------------------------------

    def _patient_data_findings(self, repo: RepoView) -> list[Finding]:
        findings = []
        for path in repo.paths:
            if not path.lower().endswith(".csv") or _is_synthetic_path(path):
                continue
            content = repo.files.get(path)
            if not content:
                continue
            header = _parse_csv_header(content)
            if not header:
                continue
            header_set = set(header)
            clusters_hit = [
                cluster for cluster in _COLUMN_CLUSTERS if header_set & cluster
            ]
            if len(clusters_hit) < _MIN_CLUSTERS_HIT:
                continue
            matched_columns = sorted(header_set & set().union(*clusters_hit))
            findings.append(
                self._finding(
                    "patient-data-in-repo",
                    "error",
                    "pii",
                    "Likely person-level health data committed",
                    f"`{path}` has column headers ({', '.join(matched_columns)}) "
                    "that together look like real, person-level health records "
                    "rather than aggregate or reference data, and its path "
                    "doesn't mark it as test/synthetic data.",
                    fix="Remove the file from the repository and its history, "
                    "or confirm it is synthetic and move it under a path "
                    "(e.g. `fixtures/`, `test/`) that marks it as such.",
                    file=path,
                )
            )
        return findings

    # -- secrets/committed-env-values -------------------------------------

    def _env_value_findings(self, repo: RepoView) -> list[Finding]:
        findings = []
        for path in repo.paths:
            if not _is_env_path(path):
                continue
            content = repo.files.get(path)
            if not content:
                continue
            for line_number, line in enumerate(content.splitlines(), start=1):
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                match = _ENV_VALUE_RE.match(stripped)
                if not match:
                    continue
                key, value = match.group(1), match.group(2)
                if _PLACEHOLDER_VALUE_RE.match(value):
                    continue
                findings.append(
                    self._finding(
                        "committed-env-values",
                        "error",
                        "pii",
                        "Non-empty value in a committed .env file",
                        f"`{path}:{line_number}` sets `{key}` to a non-empty, "
                        "non-placeholder value. Real `.env` files (as opposed "
                        "to `.env.example`) shouldn't be tracked at all.",
                        fix=f"Remove `{path}` from version control (add it to "
                        "`.gitignore`), rotate any credential it contained, and "
                        "commit an `.env.example` with empty/placeholder values "
                        "instead.",
                        file=path,
                        line=line_number,
                        namespace="secrets",
                    )
                )
        return findings

    # -- pii/db-dump-committed ---------------------------------------------

    def _db_dump_findings(self, repo: RepoView) -> list[Finding]:
        findings = []
        for path in repo.paths:
            lower = path.lower()
            if lower.endswith((".dump", ".bak")):
                findings.append(
                    self._finding(
                        "db-dump-committed",
                        "warning",
                        "pii",
                        "Database dump/backup file committed",
                        f"`{path}` is a database dump or backup file. These "
                        "routinely contain real patient data, far more of it "
                        "than any single fixture, and are easy to commit by "
                        "accident.",
                        fix="Remove the file from the repository and its "
                        "history; store dumps outside version control.",
                        file=path,
                    )
                )
            elif lower.endswith(".sql") and not _is_migrations_path(path):
                content = repo.files.get(path)
                if content and len(content.encode("utf-8", errors="replace")) > _DESTRUCTIVE_SQL_SIZE_THRESHOLD:
                    findings.append(
                        self._finding(
                            "db-dump-committed",
                            "warning",
                            "pii",
                            "Large raw SQL file outside a migrations directory",
                            f"`{path}` is a {len(content) // 1000}KB+ `.sql` file "
                            "outside a migrations directory — shaped more like a "
                            "database export than a schema change.",
                            fix="Confirm this isn't a data export; if it is, "
                            "remove it from the repository and its history.",
                            file=path,
                        )
                    )
        return findings

    @staticmethod
    def _finding(
        rule_suffix: str,
        severity: str,
        category: str,
        title: str,
        message: str,
        *,
        fix: str,
        file: str | None = None,
        line: int | None = None,
        namespace: str = "pii",
    ) -> Finding:
        return Finding(
            rule_id=f"{namespace}/{rule_suffix}",
            pack="pii",
            severity=severity,
            category=category,
            title=title,
            message=message,
            fix=fix,
            file=file,
            line=line,
            docs_url=f"{TOOL_URI}#{namespace}-{rule_suffix}",
        )
