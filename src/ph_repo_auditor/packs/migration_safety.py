from __future__ import annotations

import re

from ..models import TOOL_URI, AuditPolicy, Finding
from .base import RepoView

_DESTRUCTIVE_SQL_RE = re.compile(
    r"\b(DROP\s+TABLE|DROP\s+COLUMN|TRUNCATE)\b", re.IGNORECASE
)
_CREATE_OR_ADD_SQL_RE = re.compile(
    r"\b(CREATE\s+TABLE|ADD\s+COLUMN)\b(?!\s+IF\s+NOT\s+EXISTS)", re.IGNORECASE
)
_DML_SQL_RE = re.compile(
    r"\b(INSERT\s+INTO|UPDATE\s+\w+\s+SET|DELETE\s+FROM)\b", re.IGNORECASE
)
_DDL_SQL_RE = re.compile(
    r"\b(CREATE\s+TABLE|ALTER\s+TABLE|DROP\s+TABLE)\b", re.IGNORECASE
)

# Flyway's own versioned/undo naming convention: V1__thing.sql / U1__thing.sql.
_FLYWAY_VERSIONED_RE = re.compile(r"^V([0-9][0-9.]*)__.+\.sql$", re.IGNORECASE)
_FLYWAY_UNDO_RE = re.compile(r"^U([0-9][0-9.]*)__.+\.sql$", re.IGNORECASE)

_DJANGO_MIGRATION_RE = re.compile(r"class\s+Migration\s*\(\s*migrations\.Migration\s*\)")
_DJANGO_RUNPYTHON_SINGLE_ARG_RE = re.compile(
    r"migrations\.RunPython\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)"
)

_RAILS_MIGRATION_RE = re.compile(r"class\s+\w+\s*<\s*ActiveRecord::Migration")
_RAILS_CHANGE_METHOD_RE = re.compile(r"def\s+change\b")
_RAILS_IRREVERSIBLE_DSL_RE = re.compile(
    r"\b(drop_table|remove_column|change_column)\b"
)
_RAILS_SCHEMA_DSL_RE = re.compile(
    r"\b(create_table|add_column|drop_table|remove_column|add_index|change_column)\b"
)
_RAILS_DATA_RE = re.compile(r"\.(update_all|find_each|delete_all)\b|\bexecute\s*\(")

_ALEMBIC_REVISION_RE = re.compile(r"^\s*revision(?::\s*\w+)?\s*=")
_ALEMBIC_DOWNGRADE_RE = re.compile(
    r"def\s+downgrade\s*\([^)]*\)\s*(?:->[^:]+)?:\s*\n((?:[ \t]+.*\n?)*)"
)


_MIGRATION_DIR_NAMES = {"migration", "migrations", "migrate"}


def _is_migrations_path(path: str) -> bool:
    """Whether `path` sits under a conventional migration directory.

    Matches directory *segments* exactly (Flyway's `migration`, Django/
    Prisma's `migrations`, Rails' `migrate`, Alembic's `versions` under
    `alembic/`) rather than a loose substring match — a loose "migrat" in
    path.lower() match would also catch this pack's own source/test
    filenames (`migration_safety.py`, `test_migration_safety_pack.py`),
    which legitimately contain the word "migration" without being one.
    """
    segments = [segment.lower() for segment in path.split("/")[:-1]]
    if any(segment in _MIGRATION_DIR_NAMES for segment in segments):
        return True
    return "alembic" in segments and "versions" in segments


def _is_relevant_migration_path(path: str) -> bool:
    """Name-only guess for callers (the GitHub App client) deciding what to
    fetch before seeing content."""
    name = path.rsplit("/", 1)[-1].lower()
    if not _is_migrations_path(path):
        return name == "alembic.ini"
    return name.endswith((".sql", ".py", ".rb"))


class MigrationSafetyPack:
    """Cross-cutting migration-safety checks across the frameworks a
    public-health data platform is likely to actually use: raw-SQL
    migrations (Flyway, Prisma), Django, Rails, and Alembic. Regex
    heuristics over migration file text, not a real SQL/Python/Ruby parse —
    same rigor tier as the DHIS2 pack's source scanning.

    Liquibase (OpenMRS's migration tool) is already covered by
    `OpenmrsPack`; this pack intentionally doesn't duplicate it. Knex (the
    plan's sixth framework) is deferred: its migrations are plain JS/TS
    functions (`exports.up = (knex) => ...`) with no textual convention as
    reliable as Flyway's `V__`/`U__` naming or Django's `RunPython`, so a
    regex-only pass would be guessing rather than checking — needs real
    Knex repos to shape the rules against first, same reasoning as the
    DHIS2 pack's `no-i18n-extraction` deferral.
    """

    id = "migration-safety"

    def detect(self, repo: RepoView) -> float:
        for path in repo.paths:
            name = path.rsplit("/", 1)[-1]
            lowered = name.lower()
            if lowered == "alembic.ini":
                return 1.0
            if not _is_migrations_path(path):
                continue
            content = repo.files.get(path)
            if content is None:
                continue
            if _FLYWAY_VERSIONED_RE.match(name) or name.lower().endswith(
                "migration.sql"
            ):
                return 1.0
            if lowered.endswith(".py") and _DJANGO_MIGRATION_RE.search(content):
                return 1.0
            if lowered.endswith(".py") and _ALEMBIC_REVISION_RE.search(content):
                return 1.0
            if lowered.endswith(".rb") and _RAILS_MIGRATION_RE.search(content):
                return 1.0
        return 0.0

    def run(self, repo: RepoView, policy: AuditPolicy) -> list[Finding]:
        findings: list[Finding] = []
        flyway_versions = {
            _FLYWAY_VERSIONED_RE.match(path.rsplit("/", 1)[-1]).group(1)
            for path in repo.paths
            if _is_migrations_path(path)
            and _FLYWAY_VERSIONED_RE.match(path.rsplit("/", 1)[-1])
        }
        flyway_undo_versions = {
            _FLYWAY_UNDO_RE.match(path.rsplit("/", 1)[-1]).group(1)
            for path in repo.paths
            if _is_migrations_path(path)
            and _FLYWAY_UNDO_RE.match(path.rsplit("/", 1)[-1])
        }

        for path in repo.paths:
            if not _is_migrations_path(path):
                continue
            content = repo.files.get(path)
            if content is None:
                continue
            name = path.rsplit("/", 1)[-1]
            lowered = name.lower()

            if lowered.endswith(".sql"):
                findings.extend(
                    self._raw_sql_checks(path, name, content, flyway_versions, flyway_undo_versions)
                )
            elif lowered.endswith(".py"):
                if _DJANGO_MIGRATION_RE.search(content):
                    findings.extend(self._django_checks(path, content))
                elif _ALEMBIC_REVISION_RE.search(content):
                    findings.extend(self._alembic_checks(path, content))
            elif lowered.endswith(".rb") and _RAILS_MIGRATION_RE.search(content):
                findings.extend(self._rails_checks(path, content))

        return findings

    # -- raw SQL (Flyway / Prisma / generic) -------------------------------

    def _raw_sql_checks(
        self,
        path: str,
        name: str,
        content: str,
        flyway_versions: set[str],
        flyway_undo_versions: set[str],
    ) -> list[Finding]:
        findings = []
        flyway_match = _FLYWAY_VERSIONED_RE.match(name)
        if flyway_match and _DESTRUCTIVE_SQL_RE.search(content):
            version = flyway_match.group(1)
            if version not in flyway_undo_versions:
                findings.append(
                    self._finding(
                        "irreversible",
                        "warning",
                        "migration-safety",
                        "Destructive migration has no undo script",
                        f"`{path}` drops or truncates something but there's no "
                        f"matching Flyway undo script (`U{version}__*.sql`).",
                        fix=f"Add `U{version}__*.sql` describing how to reverse "
                        "this migration, or document why it's intentionally "
                        "one-way.",
                        file=path,
                    )
                )

        if _CREATE_OR_ADD_SQL_RE.search(content):
            findings.append(
                self._finding(
                    "non-idempotent",
                    "info",
                    "migration-safety",
                    "Schema change has no existence guard",
                    f"`{path}` creates a table or adds a column without an "
                    "`IF NOT EXISTS` guard, so re-running it by hand after a "
                    "partial failure will error instead of being a no-op.",
                    fix="Add `IF NOT EXISTS` to the CREATE TABLE / ADD COLUMN "
                    "statement.",
                    file=path,
                )
            )

        if _DDL_SQL_RE.search(content) and _DML_SQL_RE.search(content):
            findings.append(
                self._finding(
                    "data-and-schema-mixed",
                    "warning",
                    "migration-safety",
                    "Schema change and data change in the same migration",
                    f"`{path}` both alters schema (CREATE/ALTER/DROP TABLE) and "
                    "manipulates data (INSERT/UPDATE/DELETE) in one migration — "
                    "on a large health database this holds a schema lock for "
                    "as long as the data operation takes.",
                    fix="Split the schema change and the data backfill into "
                    "separate migrations.",
                    file=path,
                )
            )
        return findings

    # -- Django -------------------------------------------------------------

    def _django_checks(self, path: str, content: str) -> list[Finding]:
        findings = []
        for match in _DJANGO_RUNPYTHON_SINGLE_ARG_RE.finditer(content):
            line = content.count("\n", 0, match.start()) + 1
            findings.append(
                self._finding(
                    "irreversible",
                    "warning",
                    "migration-safety",
                    "RunPython with no reverse function",
                    f"`{path}:{line}` calls `migrations.RunPython({match.group(1)})` "
                    "with no reverse function, so `migrate` backwards will fail "
                    "on this migration.",
                    fix="Pass a reverse function as RunPython's second "
                    "argument, or `migrations.RunPython.noop` if going "
                    "backward is genuinely a no-op.",
                    file=path,
                    line=line,
                )
            )

        has_schema_op = bool(
            re.search(r"migrations\.(AddField|RemoveField|CreateModel|DeleteModel|AlterField)\s*\(", content)
        )
        has_data_op = "RunPython(" in content or "RunSQL(" in content
        if has_schema_op and has_data_op:
            findings.append(
                self._finding(
                    "data-and-schema-mixed",
                    "warning",
                    "migration-safety",
                    "Schema change and data change in the same migration",
                    f"`{path}` combines a schema operation (AddField/CreateModel/...) "
                    "with a data operation (RunPython/RunSQL) in one migration.",
                    fix="Split the schema change and the data backfill into "
                    "separate migrations.",
                    file=path,
                )
            )
        return findings

    # -- Rails ----------------------------------------------------------------

    def _rails_checks(self, path: str, content: str) -> list[Finding]:
        findings = []
        if _RAILS_CHANGE_METHOD_RE.search(content) and _RAILS_IRREVERSIBLE_DSL_RE.search(content):
            findings.append(
                self._finding(
                    "irreversible",
                    "warning",
                    "migration-safety",
                    "Irreversible operation inside def change",
                    f"`{path}` uses `drop_table`/`remove_column`/`change_column` "
                    "inside `def change`, which Rails can't always auto-reverse "
                    "(it needs the original column type or table definition to "
                    "roll back).",
                    fix="Split into `def up` / `def down` with an explicit "
                    "reversal, or pass the extra arguments `change` needs to "
                    "reverse automatically.",
                    file=path,
                )
            )
        if _RAILS_SCHEMA_DSL_RE.search(content) and _RAILS_DATA_RE.search(content):
            findings.append(
                self._finding(
                    "data-and-schema-mixed",
                    "warning",
                    "migration-safety",
                    "Schema change and data change in the same migration",
                    f"`{path}` combines schema DSL (create_table/add_column/...) "
                    "with a data operation (update_all/find_each/execute) in "
                    "one migration.",
                    fix="Split the schema change and the data backfill into "
                    "separate migrations.",
                    file=path,
                )
            )
        return findings

    # -- Alembic ----------------------------------------------------------

    def _alembic_checks(self, path: str, content: str) -> list[Finding]:
        findings = []
        downgrade_match = _ALEMBIC_DOWNGRADE_RE.search(content)
        if downgrade_match:
            body = downgrade_match.group(1)
            meaningful = [
                line
                for line in body.splitlines()
                if line.strip() and line.strip() != "pass" and not line.strip().startswith("#")
            ]
            has_upgrade_ops = "def upgrade(" in content and "op." in content.split(
                "def downgrade(", 1
            )[0]
            if not meaningful and has_upgrade_ops:
                findings.append(
                    self._finding(
                        "irreversible",
                        "warning",
                        "migration-safety",
                        "downgrade() is empty",
                        f"`{path}` has an `upgrade()` with real operations but "
                        "an empty `downgrade()`.",
                        fix="Implement `downgrade()` to reverse `upgrade()`'s "
                        "operations, or document why this revision is "
                        "intentionally one-way.",
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
    ) -> Finding:
        return Finding(
            rule_id=f"migration/{rule_suffix}",
            pack="migration-safety",
            severity=severity,
            category=category,
            title=title,
            message=message,
            fix=fix,
            file=file,
            line=line,
            docs_url=f"{TOOL_URI}#migration-{rule_suffix}",
        )
