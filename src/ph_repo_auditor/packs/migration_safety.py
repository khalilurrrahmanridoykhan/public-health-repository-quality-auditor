from __future__ import annotations

import re

from ..models import TOOL_URI, AuditPolicy, Finding
from .base import RepoView

_DML_SQL_RE = re.compile(
    r"\b(INSERT\s+INTO|UPDATE\s+\w+\s+SET|DELETE\s+FROM)\b", re.IGNORECASE
)
_DDL_SQL_RE = re.compile(
    r"\b(CREATE\s+TABLE|ALTER\s+TABLE|DROP\s+TABLE)\b", re.IGNORECASE
)
# Postgres dollar-quoted string bodies (`$$ ... $$` / `$tag$ ... $tag$`) —
# almost always a function/trigger definition. Stripped out before the DDL/
# DML scan below: a plpgsql history-tracking trigger routinely contains its
# own `insert into` inside the function body, which isn't data manipulation
# the migration *executes* — it's the DDL that defines the trigger.
_DOLLAR_QUOTED_RE = re.compile(r"\$([A-Za-z_]*)\$.*?\$\1\$", re.DOTALL)

# Flyway's own versioned-migration naming convention: V1__thing.sql.
_FLYWAY_VERSIONED_RE = re.compile(r"^V([0-9][0-9.]*)__.+\.sql$", re.IGNORECASE)

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

# re.MULTILINE so `^` anchors each line, not just the start of the whole
# file — a real Alembic script almost always has a license header or
# module docstring before `revision = "..."`, which `^` without MULTILINE
# would never see past (confirmed live: this silently no-op'd this pack's
# entire Alembic branch against a real 399-file repo, apache/superset).
_ALEMBIC_REVISION_RE = re.compile(r"^\s*revision(?::\s*\w+)?\s*=", re.MULTILINE)
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
    reliable as Flyway's `V__` naming or Django's `RunPython`, so a
    regex-only pass would be guessing rather than checking — needs real
    Knex repos to shape the rules against first, same reasoning as the
    DHIS2 pack's `no-i18n-extraction` deferral.

    `migration/irreversible` and `migration/non-idempotent` only apply to
    Django, Rails, and Alembic, **not** raw SQL (Flyway/Prisma) — both were
    tried there first and dropped after self-testing against a real
    127-migration Flyway repo (Opetushallitus/kouta-backend). Flyway's
    "undo" migration (`U__*.sql`) is a Teams/Enterprise-only feature almost
    no Community-edition user can act on, so flagging every `DROP`/
    `TRUNCATE` for lacking one was unactionable advice, not a real finding;
    `CREATE TABLE`/`ADD COLUMN` without `IF NOT EXISTS` isn't an idiom
    Flyway (or Prisma) actually uses — Flyway's own model is versioned,
    forward-only migrations tracked in its own history table, not
    idempotent re-runs — and the check fired on 37% of that real repo's
    migrations with no genuine issue behind it. `data-and-schema-mixed`
    was kept but fixed: its first pass also fired on nearly half of
    kouta-backend's migrations because Postgres history-tracking triggers
    (`create function ... as $$ ... insert into ... $$`) textually contain
    `insert into` inside their dollar-quoted body — compiled, not executed
    by the migration. Stripping dollar-quoted blocks before the DDL/DML
    scan took that down to 8 real hits (verified by inspection — each one
    a genuine top-level `UPDATE`/`DELETE` alongside a schema change,
    outside any function body).

    The Alembic branch had its own real bug, also only found by testing
    against a real repo: `_ALEMBIC_REVISION_RE`'s `^` anchor was compiled
    without `re.MULTILINE`, so it only ever matched `revision = ` at the
    very start of the file — never true in practice, since a real Alembic
    script almost always opens with a license header or module docstring.
    This made detect() and both Alembic checks a silent no-op on every
    real file tested (confirmed: 0 findings against a 399-file real repo,
    apache/superset, before the fix; 48 genuine findings — real
    `upgrade()` logic paired with an empty `downgrade(): pass`, several
    with their own "can't be downgraded" comments — after it). Hand-written
    unit tests never caught this because they put `revision = ` on the
    first line of the fixture with no header before it.
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
        for path in repo.paths:
            if not _is_migrations_path(path):
                continue
            content = repo.files.get(path)
            if content is None:
                continue
            name = path.rsplit("/", 1)[-1]
            lowered = name.lower()

            if lowered.endswith(".sql"):
                findings.extend(self._raw_sql_checks(path, content))
            elif lowered.endswith(".py"):
                if _DJANGO_MIGRATION_RE.search(content):
                    findings.extend(self._django_checks(path, content))
                elif _ALEMBIC_REVISION_RE.search(content):
                    findings.extend(self._alembic_checks(path, content))
            elif lowered.endswith(".rb") and _RAILS_MIGRATION_RE.search(content):
                findings.extend(self._rails_checks(path, content))

        return findings

    # -- raw SQL (Flyway / Prisma / generic) -------------------------------

    def _raw_sql_checks(self, path: str, content: str) -> list[Finding]:
        findings = []
        # Ignore dollar-quoted bodies (Postgres function/trigger definitions,
        # e.g. `create function ... as $$ ... $$`) when looking for DML:
        # statements inside one are compiled, not executed by the migration
        # itself, so an INSERT inside a history-tracking trigger function
        # isn't "data manipulation in this migration."
        ddl_only = _DOLLAR_QUOTED_RE.sub("", content)
        if _DDL_SQL_RE.search(ddl_only) and _DML_SQL_RE.search(ddl_only):
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
