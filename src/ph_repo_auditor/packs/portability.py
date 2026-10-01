from __future__ import annotations

import ipaddress
import re

from ..models import TOOL_URI, AuditPolicy, Finding
from .base import RepoView

SOURCE_SUFFIXES = (".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".rb")

# Excludes a match immediately preceded by "<letter>/" — the universal
# `Product/X.Y.Z.W` shape of a User-Agent or version-pin string (e.g.
# `Chrome/141.0.0.0`), which is a dotted-quad but not an IP address. A real
# `scheme://<ip>` URL still matches: the two characters before the digits
# there are "//", not "<letter>/".
_IPV4_RE = re.compile(r"(?<![A-Za-z]/)\b(?:\d{1,3}\.){3}\d{1,3}\b")
# Database/queue connection strings with a literal host embedded —
# narrower and far less noisy than matching any https:// URL, which flags
# every legitimate reference to a well-known public API (github.com,
# hl7.org, ...) a tool like this one inevitably contains.
_CONNECTION_STRING_RE = re.compile(
    r"\b(postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqp[s]?)://"
    r"(?:[^@/\s\"']*@)?([A-Za-z0-9.-]+)(?::\d+)?/",
    re.IGNORECASE,
)
_PLACEHOLDER_HOST_RE = re.compile(
    r"^(localhost|\$\{.*\}|%\(.*\)s|\{\{.*\}\}|<.*>)$"
)

_HOME_PATH_RE = re.compile(r"(?<![\w/])/(?:home|Users)/[A-Za-z0-9_.\-]+(?:/|\b)")
# Excludes a drive letter immediately preceded by a backslash — almost
# always a regex escape (`\A`, `\Z`, `\b`, `\w`, ...) rather than a real
# Windows path; a genuine path's drive letter is preceded by a quote,
# space, or start of string instead.
_WINDOWS_PATH_RE = re.compile(r"(?<!\\)\b[A-Za-z]:\\[^\s\"'`]+")

_MYSQL_ONLY_SQL_RE = re.compile(r"`|\bENGINE\s*=|\bAUTO_INCREMENT\b", re.IGNORECASE)

# A path containing any of these is presumed test code — IP/hostname
# literals there are overwhelmingly sample/mock data, not a real
# non-portable deployment value (mirrors pii._is_synthetic_path).
_TEST_PATH_MARKERS = ("test", "tests", "spec", "specs", "fixture", "fixtures")


def _is_test_path(path: str) -> bool:
    segments = {segment.lower() for segment in path.split("/")[:-1]}
    name = path.rsplit("/", 1)[-1].lower()
    return bool(segments & set(_TEST_PATH_MARKERS)) or any(
        name.startswith(f"{marker}_") or name.endswith(f"_{marker}.py")
        or name.endswith(f"_{marker}.rb")
        for marker in ("test", "spec")
    )


# Special-use ranges Python's ipaddress module doesn't classify as
# private/reserved on all versions, but IANA's own special-purpose
# registry does: RFC 6598 (carrier-grade NAT) and the AS112 direct-
# delegation block — the latter found live in Discourse's SSRF-guard
# range table (lib/final_destination/ssrf_detector.rb), which Python's
# stdlib doesn't recognise as special-use.
_EXTRA_RESERVED_IPV4_NETWORKS = (
    ipaddress.IPv4Network("100.64.0.0/10"),
    ipaddress.IPv4Network("192.175.48.0/24"),
)
# Universally-recognised placeholder IPs that turn up in both examples and
# real "test mode" code paths (e.g. Discourse's lookup_ips stubbing a DNS
# result under Rails.env.test?) even outside a test/spec file.
_PLACEHOLDER_IPV4 = {"1.2.3.4"}


def _is_reserved_ipv4(ip: str) -> bool:
    """Whether `ip` is in a private/reserved/special-use range (RFC 1918,
    loopback, link-local, RFC 5737 documentation ranges, RFC 6598
    carrier-grade NAT, ...). These show up constantly as SSRF-guard
    allow/deny lists, network examples, and test fixtures — not as a
    specific, real, non-portable deployment host, which is what this rule
    is actually trying to catch."""
    if ip in _PLACEHOLDER_IPV4:
        return True
    try:
        address = ipaddress.IPv4Address(ip)
    except ValueError:
        return True  # not a real IPv4 address at all (e.g. a version string)
    if (
        address.is_private
        or address.is_reserved
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_unspecified
    ):
        return True
    return any(network.supernet_of(ipaddress.IPv4Network(f"{address}/32"))
               for network in _EXTRA_RESERVED_IPV4_NETWORKS)


_MIGRATION_DIR_NAMES = {"migration", "migrations", "migrate"}


def _is_migrations_path(path: str) -> bool:
    """Whether `path` sits under a conventional migration directory —
    matches directory segments exactly, not a loose substring (see
    `migration_safety._is_migrations_path` for why that matters)."""
    segments = [segment.lower() for segment in path.split("/")[:-1]]
    if any(segment in _MIGRATION_DIR_NAMES for segment in segments):
        return True
    return "alembic" in segments and "versions" in segments


def _is_portability_relevant_path(path: str) -> bool:
    """Name-only guess for callers (the GitHub App client) deciding what to
    fetch before seeing content — bounded to a conventional `src/` root, the
    same scoping `_is_dhis2_relevant_source` uses, since fetching every
    source file in an arbitrary repo over the Contents API doesn't scale."""
    lowered = path.lower()
    if lowered.endswith(SOURCE_SUFFIXES):
        return lowered.startswith("src/") or "/src/" in lowered
    return lowered.endswith(".sql") and not _is_migrations_path(path)


class PortabilityPack:
    """Cross-cutting checks for environment-specific values that don't
    survive being deployed somewhere other than the author's own machine —
    the recurring reason a "works on my laptop" public-health tool never
    makes it to a second site. Applies to every repository.

    `hardcoded-hostname`'s IP matching was refined after self-testing
    against Discourse: a real SSRF-guard module (`lib/final_destination/
    ssrf_detector.rb`) builds its private-IP-range denylist from literal
    RFC 1918/5737/6598 addresses, and a User-Agent string pinned a browser
    version (`Chrome/141.0.0.0`) that's a dotted-quad but not an IP at all.
    Private/reserved/documentation-range addresses are now excluded (they're
    security-reference data or test fixtures, not a real deployment host),
    an obvious `Product/version` context is excluded, and IP/connection-
    string matches are skipped entirely in files under a test/spec/fixture
    path — mirroring the same false-positive class Phase 2's `pii-in-
    example` and this project's own first hostname-matching draft both hit.
    """

    id = "portability"

    def detect(self, repo: RepoView) -> float:
        return 1.0

    def run(self, repo: RepoView, policy: AuditPolicy) -> list[Finding]:
        findings: list[Finding] = []
        for path in repo.paths:
            lower = path.lower()
            if lower.endswith(SOURCE_SUFFIXES):
                content = repo.files.get(path)
                if content is None:
                    continue
                if not _is_test_path(path):
                    findings.extend(self._hostname_findings(path, content))
                findings.extend(self._absolute_path_findings(path, content))
            elif lower.endswith(".sql") and not _is_migrations_path(path):
                content = repo.files.get(path)
                if content is None:
                    continue
                findings.extend(self._db_specific_sql_findings(path, content))
        return findings

    # -- portability/hardcoded-hostname ------------------------------------

    def _hostname_findings(self, path: str, content: str) -> list[Finding]:
        findings = []
        seen: set[tuple[int, str]] = set()
        for line_number, line in enumerate(content.splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith(("#", "//", "*")):
                continue
            for match in _IPV4_RE.finditer(line):
                ip = match.group(0)
                if _is_reserved_ipv4(ip) or (line_number, ip) in seen:
                    continue
                seen.add((line_number, ip))
                findings.append(
                    self._finding(
                        "hardcoded-hostname",
                        "warning",
                        "portability",
                        "Hardcoded IP address in source",
                        f"`{path}:{line_number}` has a literal IP address "
                        f"(`{ip}`) baked into source rather than coming from "
                        "configuration.",
                        fix="Read the address from an environment variable "
                        "or config file instead of hardcoding it.",
                        file=path,
                        line=line_number,
                    )
                )
            for match in _CONNECTION_STRING_RE.finditer(line):
                scheme, host = match.group(1), match.group(2)
                if (
                    _PLACEHOLDER_HOST_RE.match(host)
                    or (re.fullmatch(r"(?:\d{1,3}\.){3}\d{1,3}", host) and _is_reserved_ipv4(host))
                    or (line_number, host) in seen
                ):
                    continue
                seen.add((line_number, host))
                findings.append(
                    self._finding(
                        "hardcoded-hostname",
                        "warning",
                        "portability",
                        "Hardcoded database host in a connection string",
                        f"`{path}:{line_number}` has a `{scheme}://` connection "
                        f"string with a literal host (`{host}`) rather than "
                        "one built from configuration.",
                        fix="Build the connection string from environment "
                        "variables or a config file instead of hardcoding "
                        "the host.",
                        file=path,
                        line=line_number,
                    )
                )
        return findings

    # -- portability/absolute-path -----------------------------------------

    def _absolute_path_findings(self, path: str, content: str) -> list[Finding]:
        findings = []
        for line_number, line in enumerate(content.splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith(("#", "//", "*")):
                continue
            match = _HOME_PATH_RE.search(line) or _WINDOWS_PATH_RE.search(line)
            if not match:
                continue
            findings.append(
                self._finding(
                    "absolute-path",
                    "warning",
                    "portability",
                    "Absolute, machine-specific path in source",
                    f"`{path}:{line_number}` hardcodes an absolute path "
                    f"(`{match.group(0)}`) that only resolves on the "
                    "machine it was written on.",
                    fix="Build the path from a config value, environment "
                    "variable, or a path relative to the project root.",
                    file=path,
                    line=line_number,
                )
            )
        return findings

    # -- portability/db-specific-sql -----------------------------------

    def _db_specific_sql_findings(self, path: str, content: str) -> list[Finding]:
        if not _MYSQL_ONLY_SQL_RE.search(content):
            return []
        for line_number, line in enumerate(content.splitlines(), start=1):
            if _MYSQL_ONLY_SQL_RE.search(line):
                return [
                    self._finding(
                        "db-specific-sql",
                        "warning",
                        "portability",
                        "Engine-locked SQL outside a migration",
                        f"`{path}:{line_number}` uses MySQL-only syntax "
                        "(backtick quoting, ENGINE=, AUTO_INCREMENT) in a "
                        "`.sql` file that isn't under a migrations "
                        "directory, so it won't run against another engine "
                        "the deployment might use.",
                        fix="Use ANSI-standard SQL, or move "
                        "engine-specific DDL into a proper migration where "
                        "it's at least isolated and reviewable as such.",
                        file=path,
                        line=line_number,
                    )
                ]
        return []

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
            rule_id=f"portability/{rule_suffix}",
            pack="portability",
            severity=severity,
            category=category,
            title=title,
            message=message,
            fix=fix,
            file=file,
            line=line,
            docs_url=f"{TOOL_URI}#portability-{rule_suffix}",
        )
