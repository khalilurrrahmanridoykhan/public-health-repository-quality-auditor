from __future__ import annotations

import json
import re
from dataclasses import dataclass
from importlib import resources

import yaml

from ..models import AuditPolicy, Finding
from .base import RepoView

_VALID_TYPES = {"presence", "regex", "json_key"}
_VALID_SEVERITIES = {"error", "warning", "info"}
_VALID_WHEN = {"presence": {"exists", "missing"}, "json_key": {"present", "missing"}}


@dataclass(frozen=True)
class RulepackRule:
    id: str
    title: str
    category: str
    severity: str
    type: str
    message: str
    fix: str
    file_globs: tuple[str, ...] = ()
    when: str = ""
    pattern: str = ""
    key: str = ""


@dataclass(frozen=True)
class Rulepack:
    id: str
    version: str
    source_name: str
    rules: tuple[RulepackRule, ...]


def _glob_to_regex(pattern: str) -> re.Pattern:
    """Translates a constrained glob dialect to a regex: `**` matches any
    depth (including zero directories), `*` matches within one path
    segment, `?` matches one character. Deliberately smaller than a real
    glob library — this is YAML-authored by contributors who aren't
    writing Python, so the dialect is kept to what `rulepacks/README.md`
    can explain in a few lines."""
    pieces = []
    i = 0
    while i < len(pattern):
        char = pattern[i]
        if pattern[i : i + 3] == "**/":
            pieces.append("(?:.*/)?")
            i += 3
        elif char == "*":
            pieces.append("[^/]*")
            i += 1
        elif char == "?":
            pieces.append("[^/]")
            i += 1
        else:
            pieces.append(re.escape(char))
            i += 1
    return re.compile(f"^{''.join(pieces)}$")


def _matching_paths(repo: RepoView, globs: tuple[str, ...]) -> list[str]:
    patterns = [_glob_to_regex(glob) for glob in globs]
    return sorted(
        path for path in repo.paths if any(pattern.match(path) for pattern in patterns)
    )


def _parse_rule(raw: object, index: int) -> tuple[RulepackRule | None, str | None]:
    if not isinstance(raw, dict):
        return None, f"rule #{index + 1} is not a mapping"

    rule_id = raw.get("id")
    if not isinstance(rule_id, str) or not rule_id.strip():
        return None, f"rule #{index + 1} has no string `id`"

    rule_type = raw.get("type")
    if rule_type not in _VALID_TYPES:
        return None, f"rule `{rule_id}` has an unknown `type` (expected one of {sorted(_VALID_TYPES)})"

    severity = raw.get("severity", "warning")
    if severity not in _VALID_SEVERITIES:
        return None, f"rule `{rule_id}` has an unknown `severity`"

    file_globs = raw.get("file_globs")
    if not isinstance(file_globs, list) or not file_globs or not all(
        isinstance(item, str) for item in file_globs
    ):
        return None, f"rule `{rule_id}` needs a non-empty `file_globs` list of strings"

    when = raw.get("when", "")
    if rule_type in _VALID_WHEN and when not in _VALID_WHEN[rule_type]:
        return None, (
            f"rule `{rule_id}` (type {rule_type}) needs `when` to be one of "
            f"{sorted(_VALID_WHEN[rule_type])}"
        )

    pattern = raw.get("pattern", "")
    if rule_type == "regex":
        if not isinstance(pattern, str) or not pattern:
            return None, f"rule `{rule_id}` (type regex) needs a non-empty `pattern`"
        try:
            re.compile(pattern)
        except re.error as error:
            return None, f"rule `{rule_id}` has an invalid `pattern`: {error}"

    key = raw.get("key", "")
    if rule_type == "json_key" and (not isinstance(key, str) or not key):
        return None, f"rule `{rule_id}` (type json_key) needs a non-empty `key`"

    title = raw.get("title")
    message = raw.get("message")
    if not isinstance(title, str) or not title:
        return None, f"rule `{rule_id}` has no string `title`"
    if not isinstance(message, str) or not message:
        return None, f"rule `{rule_id}` has no string `message`"

    return (
        RulepackRule(
            id=rule_id,
            title=title,
            category=raw.get("category", "hygiene")
            if isinstance(raw.get("category", "hygiene"), str)
            else "hygiene",
            severity=severity,
            type=rule_type,
            message=message,
            fix=raw.get("fix", "") if isinstance(raw.get("fix", ""), str) else "",
            file_globs=tuple(file_globs),
            when=when,
            pattern=pattern,
            key=key,
        ),
        None,
    )


def parse_rulepack(content: str, source_name: str) -> tuple[Rulepack | None, list[str]]:
    """Parses one rulepack YAML file's content. Never raises — a malformed
    rulepack is skipped with a warning, the same policy this project uses
    for a malformed `.ph-repo-auditor.yml`, not a hard failure of the
    whole audit."""
    warnings: list[str] = []
    try:
        parsed = yaml.safe_load(content)
    except yaml.YAMLError as error:
        return None, [f"`{source_name}`: invalid YAML ({error})"]

    if not isinstance(parsed, dict):
        return None, [f"`{source_name}`: must be a YAML mapping"]

    rulepack_id = parsed.get("id")
    if not isinstance(rulepack_id, str) or not rulepack_id.strip():
        return None, [f"`{source_name}`: has no string `id`"]

    version = parsed.get("version", "0.0.0")
    if not isinstance(version, str):
        version = str(version)

    raw_rules = parsed.get("rules")
    if not isinstance(raw_rules, list) or not raw_rules:
        return None, [f"`{source_name}`: has no non-empty `rules` list"]

    rules: list[RulepackRule] = []
    for index, raw_rule in enumerate(raw_rules):
        rule, warning = _parse_rule(raw_rule, index)
        if warning:
            warnings.append(f"`{source_name}`: {warning} — skipped")
        if rule:
            rules.append(rule)

    if not rules:
        warnings.append(f"`{source_name}`: no valid rules — rulepack skipped")
        return None, warnings

    return Rulepack(id=rulepack_id, version=version, source_name=source_name, rules=tuple(rules)), warnings


class RulepackPack:
    """Wraps one community-contributed YAML rulepack as a `Pack`. Always
    detects at confidence 1.0 — a loaded rulepack is, by definition, one
    its author wanted applied; whether any of its rules actually fire
    depends on the rule's own `file_globs`/`when`, not on pack-level
    detection.
    """

    def __init__(self, rulepack: Rulepack):
        self.rulepack = rulepack
        self.id = f"rulepack:{rulepack.id}"

    def detect(self, repo: RepoView) -> float:
        return 1.0

    def run(self, repo: RepoView, policy: AuditPolicy) -> list[Finding]:
        findings: list[Finding] = []
        for rule in self.rulepack.rules:
            if rule.type == "presence":
                findings.extend(self._presence_findings(repo, rule))
            elif rule.type == "regex":
                findings.extend(self._regex_findings(repo, rule))
            elif rule.type == "json_key":
                findings.extend(self._json_key_findings(repo, rule))
        return findings

    def _presence_findings(self, repo: RepoView, rule: RulepackRule) -> list[Finding]:
        matches = _matching_paths(repo, rule.file_globs)
        if rule.when == "exists" and matches:
            return [self._finding(rule, file=matches[0])]
        if rule.when == "missing" and not matches:
            return [self._finding(rule, file=repo.anchor())]
        return []

    def _regex_findings(self, repo: RepoView, rule: RulepackRule) -> list[Finding]:
        findings = []
        compiled = re.compile(rule.pattern)
        for path in _matching_paths(repo, rule.file_globs):
            content = repo.files.get(path)
            if not content:
                continue
            for line_number, line in enumerate(content.splitlines(), start=1):
                if compiled.search(line):
                    findings.append(self._finding(rule, file=path, line=line_number))
        return findings

    def _json_key_findings(self, repo: RepoView, rule: RulepackRule) -> list[Finding]:
        findings = []
        for path in _matching_paths(repo, rule.file_globs):
            content = repo.files.get(path)
            if content is None:
                continue
            try:
                parsed = json.loads(content)
            except (ValueError, TypeError):
                continue
            if not isinstance(parsed, dict):
                continue
            present = _has_key_path(parsed, rule.key)
            if (rule.when == "missing" and not present) or (
                rule.when == "present" and present
            ):
                findings.append(self._finding(rule, file=path))
        return findings

    def _finding(
        self, rule: RulepackRule, *, file: str | None, line: int | None = None
    ) -> Finding:
        return Finding(
            rule_id=f"{self.rulepack.id}/{rule.id}",
            pack=self.id,
            severity=rule.severity,
            category=rule.category,
            title=rule.title,
            message=rule.message,
            fix=rule.fix,
            file=file,
            line=line,
        )


def _has_key_path(value: dict, dotted_key: str) -> bool:
    current: object = value
    for segment in dotted_key.split("."):
        if not isinstance(current, dict) or segment not in current:
            return False
        current = current[segment]
    return True


def rulepack_relevant_paths(file_paths: list[str]) -> set[str]:
    """Which of `file_paths` at least one loaded rulepack's `file_globs`
    could match — for the GitHub App client, which (unlike the CLI's
    `scan_directory`, which just reads everything matching a suffix
    allowlist) must decide what to fetch over the Contents API *before*
    it has any content to check `regex`/`json_key` rules against.
    `presence` rules don't need this: a path merely existing in the tree
    listing is already enough to evaluate one."""
    packs, _ = load_rulepacks()
    all_globs = tuple(
        glob
        for pack in packs
        for rule in pack.rulepack.rules
        if rule.type != "presence"
        for glob in rule.file_globs
    )
    if not all_globs:
        return set()
    patterns = [_glob_to_regex(glob) for glob in all_globs]
    return {path for path in file_paths if any(pattern.match(path) for pattern in patterns)}


def load_rulepacks() -> tuple[list[RulepackPack], list[str]]:
    """Discovers every `*.yml`/`*.yaml` file bundled under
    `ph_repo_auditor/rulepacks/` and loads it as a `Pack`. This is the
    mechanism behind this plan's "a third party can add a working rule
    via PR touching only `rulepacks/` + a fixture" bar — no change to
    `registry.py` is needed for a new rulepack file to take effect.
    """
    packs: list[RulepackPack] = []
    warnings: list[str] = []
    try:
        rulepacks_dir = resources.files("ph_repo_auditor").joinpath("rulepacks")
        entries = sorted(
            entry for entry in rulepacks_dir.iterdir() if entry.name.endswith((".yml", ".yaml"))
        )
    except (FileNotFoundError, ModuleNotFoundError):
        return packs, warnings

    for entry in entries:
        content = entry.read_text(encoding="utf-8")
        rulepack, parse_warnings = parse_rulepack(content, entry.name)
        warnings.extend(parse_warnings)
        if rulepack:
            packs.append(RulepackPack(rulepack))
    return packs, warnings
