from __future__ import annotations

import json
import re

from ..models import TOOL_URI, AuditPolicy, Finding
from .base import RepoView

D2_CONFIG_NAMES = {"d2.config.js", "d2.config.json"}
SOURCE_SUFFIXES = (".js", ".jsx", ".ts", ".tsx")

# The App Platform's documented d2.config `type` values.
VALID_D2_TYPES = {"app", "widget", "app+widget"}

# Metadata collection keys distinctive enough to a DHIS2 export that seeing
# one is a reliable signal, unlike generic names ("programs", "indicators")
# that plenty of non-DHIS2 JSON could also use.
DHIS2_DISTINCTIVE_METADATA_KEYS = {
    "organisationUnits",
    "organisationUnitGroups",
    "categoryCombos",
    "categoryOptionCombos",
    "categoryOptions",
    "trackedEntityTypes",
    "trackedEntityAttributes",
    "programStages",
    "programRules",
    "programRuleVariables",
    "optionSets",
    "legendSets",
    "dataElementGroups",
    "dataElementGroupSets",
    "sqlViews",
}
# Once a file is already known to be a DHIS2 bundle, these (more generic)
# collection keys are also fair game for the structural checks below.
DHIS2_ALL_METADATA_KEYS = DHIS2_DISTINCTIVE_METADATA_KEYS | {
    "dataElements",
    "programs",
    "dataSets",
    "indicators",
    "indicatorTypes",
    "categories",
    "options",
}

UID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]{10}$")

# A curated subset of DHIS2's reference-field-name -> owning-collection-key
# schema (not the full metadata schema) used for the dangling-reference
# check: a field only counts as "should resolve locally" when its matching
# top-level collection is itself present in the bundle.
REFERENCE_FIELD_TO_COLLECTION = {
    "categoryCombo": "categoryCombos",
    "categoryOptionCombo": "categoryOptionCombos",
    "optionSet": "optionSets",
    "legendSet": "legendSets",
    "dataElement": "dataElements",
    "trackedEntityType": "trackedEntityTypes",
    "program": "programs",
    "programStage": "programStages",
    "trackedEntityAttribute": "trackedEntityAttributes",
    "dataSet": "dataSets",
    "indicatorType": "indicatorTypes",
}

_D2_TYPE_RE = re.compile(r"""type\s*:\s*['"]([\w+]+)['"]""")
_D2_ENTRYPOINTS_RE = re.compile(r"entryPoints\s*:\s*\{")

_HARDCODED_URL_RE = re.compile(
    r"""['"`](https?://(?:play\.dhis2\.org|debug\.dhis2\.org|"""
    r"""[a-z0-9.-]+\.dhis2\.org|[a-z0-9.-]+\.dhis2\.com)[^'"`]*)['"`]""",
    re.IGNORECASE,
)
_FETCH_API_RE = re.compile(
    r"""(?:fetch|axios\.\w+)\s*\(\s*['"`][^'"`]*/api/""",
)

_MUTATING_SQL_RE = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|GRANT|REVOKE|CREATE)\b",
    re.IGNORECASE,
)

_PROGRAM_RULE_VARIABLE_RE = re.compile(r"#\{([A-Za-z0-9_]+)\}")
_BUILTIN_VARIABLE_RE = re.compile(r"V\{([A-Za-z0-9_]+)\}")
# DHIS2's documented program rule built-in variables (v{...}).
KNOWN_BUILTIN_VARIABLES = {
    "event_date",
    "due_date",
    "enrollment_date",
    "incident_date",
    "enrollment_status",
    "enrollment_count",
    "current_date",
    "event_count",
    "tei_count",
    "value_count",
    "zero_pos_value_count",
    "event_status",
    "program_stage_id",
    "program_stage_name",
    "org_unit_code",
    "environment",
    "completed_date",
    "event_id",
    "enrollment_id",
    "event_organisation_unit",
    "creation_date",
    "sync_status",
    "analytics_period_start",
    "analytics_period_end",
}


def _is_dhis2_relevant_source(path: str) -> bool:
    """Source files worth fetching over an API (not just a local scan): app
    entry points and anything under a conventional `src/` root."""
    lowered = path.lower()
    if not lowered.endswith(SOURCE_SUFFIXES):
        return False
    return lowered.startswith("src/") or "/src/" in lowered


def _is_likely_dhis2_metadata_path(path: str) -> bool:
    """A cheap, name-only guess at "this JSON file might be a DHIS2 metadata
    bundle" for callers (the GitHub App client) that must decide what to
    fetch *before* seeing its content, unlike the local CLI scan which reads
    everything and can check the actual keys. Used only to bound the number
    of speculative Contents API calls; false negatives here just mean a
    metadata file with an unconventional name goes unchecked over the
    webhook path, not a wrong result."""
    if not path.endswith(".json"):
        return False
    name = path.rsplit("/", 1)[-1].lower()
    return "metadata" in name or "metadata" in path.lower().split("/")[:-1]


def _parse_json(content: str) -> object | None:
    try:
        return json.loads(content)
    except (ValueError, TypeError):
        return None


def _package_dependencies(repo: RepoView) -> dict:
    content = repo.get("package.json")
    if content is None:
        return {}
    parsed = _parse_json(content)
    if not isinstance(parsed, dict):
        return {}
    deps = {}
    deps.update(parsed.get("dependencies") or {})
    deps.update(parsed.get("devDependencies") or {})
    return deps


def _iter_bare_references(node: object):
    """Yield (field_name, uid) for every `{"id": "<uid>"}` reference object
    found anywhere in a metadata bundle, at any nesting depth — DHIS2's
    standard shape for "this field points at another object"."""
    if isinstance(node, dict):
        for key, value in node.items():
            if (
                isinstance(value, dict)
                and set(value.keys()) == {"id"}
                and isinstance(value["id"], str)
            ):
                yield key, value["id"]
            else:
                yield from _iter_bare_references(value)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_bare_references(item)


class Dhis2Pack:
    """Checks for DHIS2 App Platform apps and raw metadata export bundles.

    Source-level checks (hardcoded URLs, direct /api/ fetches) are regex
    heuristics over JS/TS/JSX/TSX text, not a real JS/JSX parse — deliberately
    conservative (require a literal quoted string) to keep false positives
    low rather than trying to understand arbitrary JS with a regex.

    `no-app-runtime-provider` from the original plan was dropped after
    testing against 4 real App Platform apps: none of them author their own
    `<Provider>` — `@dhis2/cli-app-scripts` wraps the app in one at build
    time, so the check would false-positive on every modern DHIS2 app.
    """

    id = "dhis2"

    def detect(self, repo: RepoView) -> float:
        names = {path.rsplit("/", 1)[-1].lower() for path in repo.paths}
        if names & D2_CONFIG_NAMES:
            return 1.0
        if any(name.startswith("@dhis2/") for name in _package_dependencies(repo)):
            return 1.0
        for path in repo.paths:
            if not path.lower().endswith(".json"):
                continue
            content = repo.files.get(path)
            if content is None:
                continue
            parsed = _parse_json(content)
            if isinstance(parsed, dict) and DHIS2_DISTINCTIVE_METADATA_KEYS & parsed.keys():
                return 1.0
        return 0.0

    def run(self, repo: RepoView, policy: AuditPolicy) -> list[Finding]:
        findings: list[Finding] = []
        findings.extend(self._d2_config_checks(repo))

        source_paths = [
            path
            for path in repo.paths
            if path.lower().endswith(SOURCE_SUFFIXES) and repo.files.get(path) is not None
        ]
        for path in source_paths:
            content = repo.files[path]
            findings.extend(self._hardcoded_url_findings(path, content))
            findings.extend(self._raw_fetch_findings(path, content))

        for path in repo.paths:
            if not path.lower().endswith(".json"):
                continue
            content = repo.files.get(path)
            if content is None:
                continue
            bundle = _parse_json(content)
            if not isinstance(bundle, dict) or not DHIS2_ALL_METADATA_KEYS & bundle.keys():
                continue
            findings.extend(self._duplicate_uids(bundle, path))
            findings.extend(self._dangling_references(bundle, path))
            findings.extend(self._sqlview_mutating_statements(bundle, path))
            findings.extend(self._program_rule_checks(bundle, path))
        return findings

    # -- individual checks --------------------------------------------------

    def _d2_config_checks(self, repo: RepoView) -> list[Finding]:
        config_path = next(
            (
                path
                for path in repo.paths
                if path.rsplit("/", 1)[-1].lower() in D2_CONFIG_NAMES
            ),
            None,
        )
        if config_path is None:
            return []
        content = repo.files.get(config_path)
        if content is None:
            return []

        if config_path.lower().endswith(".json"):
            parsed = _parse_json(content)
            config_type = parsed.get("type") if isinstance(parsed, dict) else None
            has_entry_points = isinstance(parsed, dict) and bool(parsed.get("entryPoints"))
        else:
            match = _D2_TYPE_RE.search(content)
            config_type = match.group(1) if match else None
            has_entry_points = bool(_D2_ENTRYPOINTS_RE.search(content))

        findings = []
        if config_type not in VALID_D2_TYPES:
            findings.append(
                self._finding(
                    "invalid-d2-config",
                    "error",
                    "config-validity",
                    "d2.config missing a recognised type",
                    f"`{config_path}` doesn't declare a recognised `type` "
                    f"({', '.join(sorted(VALID_D2_TYPES))}); got {config_type!r}.",
                    fix="Set `type` to one of the App Platform's supported app types.",
                    file=config_path,
                )
            )
        if not has_entry_points:
            findings.append(
                self._finding(
                    "invalid-d2-config",
                    "error",
                    "config-validity",
                    "d2.config missing entryPoints",
                    f"`{config_path}` has no `entryPoints`, so the App Platform "
                    "doesn't know what to build.",
                    fix="Add an entryPoints object, e.g. `{ app: './src/App.js' }`.",
                    file=config_path,
                )
            )
        return findings

    def _hardcoded_url_findings(self, path: str, content: str) -> list[Finding]:
        findings = []
        for line_number, line in enumerate(content.splitlines(), start=1):
            match = _HARDCODED_URL_RE.search(line)
            if match:
                findings.append(
                    self._finding(
                        "hardcoded-instance-url",
                        "warning",
                        "portability",
                        "Hardcoded DHIS2 instance URL",
                        f"`{path}:{line_number}` hardcodes `{match.group(1)}` instead of "
                        "going through the app-runtime config or a Route.",
                        fix="Read the instance base URL from useConfig()/useDataEngine(), "
                        "or define a Route instead of a literal URL.",
                        file=path,
                        line=line_number,
                    )
                )
        return findings

    def _raw_fetch_findings(self, path: str, content: str) -> list[Finding]:
        findings = []
        for line_number, line in enumerate(content.splitlines(), start=1):
            if _FETCH_API_RE.search(line):
                findings.append(
                    self._finding(
                        "raw-fetch-to-api",
                        "warning",
                        "portability",
                        "Direct fetch to the DHIS2 API",
                        f"`{path}:{line_number}` calls the Web API directly instead of "
                        "useDataQuery/useDataMutation.",
                        fix="Use useDataQuery/useDataMutation (or useDataEngine) so auth, "
                        "the instance base URL, and error handling are handled for you.",
                        file=path,
                        line=line_number,
                    )
                )
        return findings

    def _duplicate_uids(self, bundle: dict, path: str) -> list[Finding]:
        occurrences: dict[str, list[str]] = {}
        for collection_key, items in bundle.items():
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                uid = item.get("id")
                if isinstance(uid, str) and UID_RE.match(uid):
                    occurrences.setdefault(uid, []).append(collection_key)
        findings = []
        for uid, collections in sorted(occurrences.items()):
            if len(collections) > 1:
                findings.append(
                    self._finding(
                        "metadata-duplicate-uid",
                        "error",
                        "reference-integrity",
                        "Duplicate metadata UID",
                        f"`{path}` defines id `{uid}` more than once "
                        f"(in {', '.join(sorted(set(collections)))}).",
                        fix="DHIS2 UIDs must be globally unique; regenerate one of the "
                        "duplicates.",
                        file=path,
                    )
                )
        return findings

    def _dangling_references(self, bundle: dict, path: str) -> list[Finding]:
        defined_by_collection: dict[str, set[str]] = {
            key: {
                item["id"]
                for item in items
                if isinstance(item, dict) and isinstance(item.get("id"), str)
            }
            for key, items in bundle.items()
            if isinstance(items, list)
        }
        findings = []
        seen: set[tuple[str, str]] = set()
        for field_name, uid in _iter_bare_references(bundle):
            collection_key = REFERENCE_FIELD_TO_COLLECTION.get(field_name)
            if collection_key is None or collection_key not in defined_by_collection:
                continue  # not a tracked field, or the bundle isn't self-contained for it
            if not UID_RE.match(uid) or uid in defined_by_collection[collection_key]:
                continue
            key = (field_name, uid)
            if key in seen:
                continue
            seen.add(key)
            findings.append(
                self._finding(
                    "metadata-dangling-ref",
                    "error",
                    "reference-integrity",
                    "Dangling metadata reference",
                    f"`{path}` references {field_name} `{uid}`, which isn't defined in "
                    f"this bundle's own `{collection_key}` array (present, but missing "
                    "this id).",
                    fix="Include the referenced object in the export, or confirm it "
                    "already exists on the target instance before importing.",
                    file=path,
                )
            )
        return findings

    def _sqlview_mutating_statements(self, bundle: dict, path: str) -> list[Finding]:
        findings = []
        for view in bundle.get("sqlViews", []) or []:
            if not isinstance(view, dict):
                continue
            query = view.get("sqlQuery")
            if isinstance(query, str) and _MUTATING_SQL_RE.search(query):
                findings.append(
                    self._finding(
                        "sqlview-mutating-statement",
                        "error",
                        "config-validity",
                        "SQL View contains a mutating statement",
                        f"`{path}` SQL View `{view.get('name', view.get('id', '?'))}` "
                        "has a non-SELECT statement in sqlQuery.",
                        fix="SQL Views must be read-only SELECT queries; DHIS2 will "
                        "reject or refuse to run one that mutates data.",
                        file=path,
                    )
                )
        return findings

    def _program_rule_checks(self, bundle: dict, path: str) -> list[Finding]:
        has_variable_collection = "programRuleVariables" in bundle
        variable_names = {
            variable["name"]
            for variable in bundle.get("programRuleVariables", []) or []
            if isinstance(variable, dict) and isinstance(variable.get("name"), str)
        }
        findings = []
        seen: set[tuple[str, str]] = set()
        for rule in bundle.get("programRules", []) or []:
            if not isinstance(rule, dict):
                continue
            rule_label = rule.get("name", rule.get("id", "?"))
            expressions = [rule.get("condition")]
            for action in rule.get("programRuleActions", []) or []:
                if isinstance(action, dict):
                    expressions.append(action.get("data"))
            for expression in expressions:
                if not isinstance(expression, str):
                    continue
                if has_variable_collection:
                    for name in _PROGRAM_RULE_VARIABLE_RE.findall(expression):
                        key = (rule_label, f"#{name}")
                        if name not in variable_names and key not in seen:
                            seen.add(key)
                            findings.append(
                                self._finding(
                                    "program-rule-undefined-var",
                                    "warning",
                                    "reference-integrity",
                                    "Undefined program rule variable",
                                    f"`{path}` program rule `{rule_label}` references "
                                    f"`#{{{name}}}`, which isn't in this bundle's "
                                    "programRuleVariables.",
                                    fix="Add a matching programRuleVariable, or fix the "
                                    "typo.",
                                    file=path,
                                )
                            )
                for name in _BUILTIN_VARIABLE_RE.findall(expression):
                    key = (rule_label, f"V{{{name}}}")
                    if name not in KNOWN_BUILTIN_VARIABLES and key not in seen:
                        seen.add(key)
                        findings.append(
                            self._finding(
                                "program-rule-undefined-var",
                                "warning",
                                "reference-integrity",
                                "Unrecognised program rule built-in variable",
                                f"`{path}` program rule `{rule_label}` references "
                                f"`V{{{name}}}`, which isn't a documented DHIS2 "
                                "built-in variable.",
                                fix="Check for a typo against DHIS2's documented "
                                "V{...} variables.",
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
            rule_id=f"dhis2/{rule_suffix}",
            pack="dhis2",
            severity=severity,
            category=category,
            title=title,
            message=message,
            fix=fix,
            file=file,
            line=line,
            docs_url=f"{TOOL_URI}#dhis2-{rule_suffix}",
        )
