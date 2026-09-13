from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET

from ..models import TOOL_URI, AuditPolicy, Finding
from .base import RepoView

ROUTES_SCHEMA_MARKER = "json.openmrs.org/routes.schema.json"
NON_ROLLBACK_CHANGE_TAGS = {"sql", "sqlFile", "customChange"}
STRUCTURAL_CHANGE_TAGS = {"createTable", "addColumn", "dropTable", "dropColumn"}

_MYSQL_ONLY_SQL_RE = re.compile(r"`|\bENGINE\s*=|\bAUTO_INCREMENT\b", re.IGNORECASE)
_CONCEPT_UUID_CALL_RE = re.compile(
    r"getConceptByUuid\s*\(\s*[\"']"
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
    r"[\"']"
)
_EXPORTED_CONST_RE = re.compile(r"export\s+const\s+([A-Za-z0-9_]+)\s*=")


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _iter_by_local_name(root: ET.Element, name: str):
    for element in root.iter():
        if _local_name(element.tag) == name:
            yield element


def _parse_json(content: str) -> object | None:
    try:
        return json.loads(content)
    except (ValueError, TypeError):
        return None


def _is_openmrs_config_xml(content: str) -> bool:
    """A config.xml is OpenMRS's module descriptor only if its root is
    <module> with a <package> child — config.xml is too generic a filename
    to trust on its own."""
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return False
    if _local_name(root.tag) != "module":
        return False
    return any(_local_name(child.tag) == "package" for child in root)


def _is_openmrs_relevant_path(path: str) -> bool:
    """A cheap, name-only guess at "this file is worth fetching" for callers
    (the GitHub App client) that must decide what to fetch before seeing
    content — unlike the local CLI scan, which just reads everything."""
    name = path.rsplit("/", 1)[-1].lower()
    if name in {"pom.xml", "config.xml", "routes.json"}:
        return True
    if name.endswith(".java"):
        return True
    return name.endswith(".xml") and ("liquibase" in name or "changelog" in name)


def _all_dependency_names(repo: RepoView) -> set[str]:
    """Every package named in dependencies/devDependencies/peerDependencies —
    for detect(), where a *correctly* peerDependency-only O3 module (the
    convention this pack's own o3-missing-framework-peer rule wants to see)
    must still count as depending on esm-framework."""
    content = repo.get("package.json")
    if content is None:
        return set()
    parsed = _parse_json(content)
    if not isinstance(parsed, dict):
        return set()
    names: set[str] = set()
    for key in ("dependencies", "devDependencies", "peerDependencies"):
        names.update((parsed.get(key) or {}).keys())
    return names


class OpenmrsPack:
    """Checks for OpenMRS Java modules (config.xml, Liquibase changelogs)
    and O3 microfrontends (routes.json, package.json).

    Regex/ElementTree heuristics only, no Java or TypeScript parse. Two
    rules from the original design were dropped after checking real OpenMRS
    modules rather than shipped speculatively — see the README.
    """

    id = "openmrs"

    def detect(self, repo: RepoView) -> float:
        for path in repo.paths:
            name = path.rsplit("/", 1)[-1].lower()
            if name == "pom.xml":
                content = repo.files.get(path)
                if content and "<packaging>omod</packaging>" in content:
                    return 1.0
            elif name == "config.xml":
                content = repo.files.get(path)
                if content and _is_openmrs_config_xml(content):
                    return 1.0
            elif name == "routes.json":
                content = repo.files.get(path)
                if content and ROUTES_SCHEMA_MARKER in content:
                    return 1.0
        if "@openmrs/esm-framework" in _all_dependency_names(repo):
            return 1.0
        return 0.0

    def run(self, repo: RepoView, policy: AuditPolicy) -> list[Finding]:
        findings: list[Finding] = []
        for path in repo.paths:
            if not path.lower().endswith(".xml"):
                continue
            content = repo.files.get(path)
            if content is None:
                continue
            try:
                root = ET.fromstring(content)
            except ET.ParseError:
                continue
            if _local_name(root.tag) != "databaseChangeLog":
                continue
            findings.extend(self._liquibase_checks(root, path))

        findings.extend(self._concept_uuid_findings(repo))
        findings.extend(self._o3_framework_peer_check(repo))
        findings.extend(self._o3_routes_checks(repo))
        return findings

    # -- Liquibase checks -----------------------------------------------

    def _liquibase_checks(self, root: ET.Element, path: str) -> list[Finding]:
        findings = []
        seen_ids: dict[tuple[str, str], int] = {}
        for change_set in _iter_by_local_name(root, "changeSet"):
            change_id = change_set.get("id")
            author = change_set.get("author")
            if not change_id or not author:
                findings.append(
                    self._finding(
                        "liquibase-missing-id",
                        "error",
                        "config-validity",
                        "changeSet missing id or author",
                        f"`{path}` has a changeSet with no `id` and/or `author` attribute.",
                        fix="Give every changeSet a unique id and an author.",
                        file=path,
                    )
                )
                continue
            key = (change_id, author)
            seen_ids[key] = seen_ids.get(key, 0) + 1

            direct_children = {_local_name(child.tag) for child in change_set}
            if direct_children & NON_ROLLBACK_CHANGE_TAGS and "rollback" not in direct_children:
                findings.append(
                    self._finding(
                        "liquibase-sql-no-rollback",
                        "warning",
                        "migration-safety",
                        "Raw SQL changeSet has no rollback",
                        f"`{path}` changeSet `{change_id}` ({author}) runs raw SQL/a custom "
                        "change with no <rollback>, so `liquibase rollback` will fail on it.",
                        fix="Add a <rollback> element describing how to undo this change.",
                        file=path,
                    )
                )
            if direct_children & STRUCTURAL_CHANGE_TAGS and "preConditions" not in direct_children:
                findings.append(
                    self._finding(
                        "liquibase-non-idempotent",
                        "warning",
                        "migration-safety",
                        "Schema change has no preConditions guard",
                        f"`{path}` changeSet `{change_id}` ({author}) creates/drops a "
                        "table or column with no <preConditions>, so re-running it on an "
                        "already-migrated database will fail instead of being skipped.",
                        fix='Add <preConditions onFail="MARK_RAN"> checking the table/column '
                        "doesn't already exist.",
                        file=path,
                    )
                )
            for sql_element in list(change_set.findall("*")):
                if _local_name(sql_element.tag) != "sql" or not sql_element.text:
                    continue
                if _MYSQL_ONLY_SQL_RE.search(sql_element.text):
                    findings.append(
                        self._finding(
                            "liquibase-db-specific-sql",
                            "warning",
                            "portability",
                            "MySQL-only syntax in a raw SQL changeSet",
                            f"`{path}` changeSet `{change_id}` ({author}) uses backtick "
                            "quoting or MySQL-only keywords (ENGINE=, AUTO_INCREMENT) in "
                            "raw SQL, which won't run on other databases Liquibase targets.",
                            fix="Use Liquibase's structured change types (createTable, "
                            "addColumn, ...) instead of raw MySQL SQL where possible.",
                            file=path,
                        )
                    )

        for (change_id, author), count in seen_ids.items():
            if count > 1:
                findings.append(
                    self._finding(
                        "liquibase-duplicate-id",
                        "error",
                        "reference-integrity",
                        "Duplicate Liquibase changeSet id",
                        f"`{path}` has {count} changeSets with id `{change_id}` and author "
                        f"`{author}`.",
                        fix="Give each changeSet a unique id (a UUID is the OpenMRS convention).",
                        file=path,
                    )
                )
        return findings

    # -- Java concept lookups ---------------------------------------------

    def _concept_uuid_findings(self, repo: RepoView) -> list[Finding]:
        findings = []
        for path in repo.paths:
            if not path.lower().endswith(".java"):
                continue
            content = repo.files.get(path)
            if content is None:
                continue
            for line_number, line in enumerate(content.splitlines(), start=1):
                if _CONCEPT_UUID_CALL_RE.search(line):
                    findings.append(
                        self._finding(
                            "hardcoded-concept-uuid",
                            "warning",
                            "portability",
                            "Hardcoded concept UUID",
                            f"`{path}:{line_number}` calls getConceptByUuid with a literal "
                            "UUID, which only exists in dictionaries that happen to use the "
                            "same UUID for that concept.",
                            fix="Use getConceptByMapping(code, source) against a concept "
                            "mapping (e.g. CIEL, SNOMED CT) instead, or read the UUID from "
                            "a configurable global property.",
                            file=path,
                            line=line_number,
                        )
                    )
        return findings

    # -- O3 checks ------------------------------------------------------

    def _o3_framework_peer_check(self, repo: RepoView) -> list[Finding]:
        content = repo.get("package.json")
        if content is None:
            return []
        parsed = _parse_json(content)
        if not isinstance(parsed, dict):
            return []
        if "@openmrs/esm-framework" in (parsed.get("dependencies") or {}):
            return [
                self._finding(
                    "o3-missing-framework-peer",
                    "error",
                    "config-validity",
                    "esm-framework listed as a regular dependency",
                    "`package.json` lists `@openmrs/esm-framework` under `dependencies`. "
                    "The shell provides exactly one copy of it at runtime; bundling your "
                    "own can load two incompatible copies side by side.",
                    fix="Move `@openmrs/esm-framework` to `peerDependencies` (and keep it "
                    "in `devDependencies` for local builds/tests).",
                    file="package.json",
                )
            ]
        return []

    def _o3_routes_checks(self, repo: RepoView) -> list[Finding]:
        findings = []
        for path in repo.paths:
            if path.rsplit("/", 1)[-1].lower() != "routes.json":
                continue
            content = repo.files.get(path)
            if content is None:
                continue
            parsed = _parse_json(content)
            if parsed is None:
                findings.append(
                    self._finding(
                        "o3-invalid-routes-json",
                        "error",
                        "config-validity",
                        "Invalid routes.json",
                        f"`{path}` is not valid JSON.",
                        fix="Fix the JSON syntax error.",
                        file=path,
                    )
                )
                continue
            if not isinstance(parsed, dict):
                continue

            index_content = self._sibling_index_content(repo, path)
            if index_content is None:
                continue
            exported = set(_EXPORTED_CONST_RE.findall(index_content))
            for section in ("pages", "extensions", "modals"):
                for entry in parsed.get(section, []) or []:
                    if not isinstance(entry, dict):
                        continue
                    component = entry.get("component")
                    if isinstance(component, str) and component not in exported:
                        findings.append(
                            self._finding(
                                "o3-route-missing-export",
                                "error",
                                "reference-integrity",
                                "routes.json references a missing export",
                                f"`{path}` {section[:-1]} `{entry.get('name', component)}` "
                                f"points at component `{component}`, which has no matching "
                                "`export const` in the module's entry file.",
                                fix="Add the export, or fix the component name in routes.json.",
                                file=path,
                            )
                        )
        return findings

    @staticmethod
    def _sibling_index_content(repo: RepoView, routes_path: str) -> str | None:
        directory = routes_path.rsplit("/", 1)[0] if "/" in routes_path else ""
        for name in ("index.ts", "index.tsx", "index.js"):
            candidate = f"{directory}/{name}" if directory else name
            content = repo.get(candidate)
            if content is not None:
                return content
        return None

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
            rule_id=f"openmrs/{rule_suffix}",
            pack="openmrs",
            severity=severity,
            category=category,
            title=title,
            message=message,
            fix=fix,
            file=file,
            line=line,
            docs_url=f"{TOOL_URI}#openmrs-{rule_suffix}",
        )
