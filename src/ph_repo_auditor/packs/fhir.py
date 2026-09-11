from __future__ import annotations

import json
import re
import shutil

import yaml

from ..models import TOOL_URI, AuditPolicy, Finding
from .base import RepoView

FSH_CONFIG_NAMES = {"sushi-config.yaml", "sushi-config.yml"}
CONFORMANCE_FILENAME_RE = re.compile(
    r"^(structuredefinition|valueset|codesystem|implementationguide|"
    r"capabilitystatement|searchparameter|operationdefinition|conceptmap|"
    r"namingsystem)-.+\.json$"
)
FHIR_RELEVANT_DIR_SEGMENTS = {
    "examples",
    "example",
    "fsh-generated",
    "fhir",
    "resources",
    "tests",
    "test",  # SUSHI's `input/tests/` fixture convention
}

CONFORMANCE_RESOURCE_TYPES = {
    "StructureDefinition",
    "ValueSet",
    "CodeSystem",
    "ImplementationGuide",
    "CapabilityStatement",
    "SearchParameter",
    "OperationDefinition",
    "ConceptMap",
    "NamingSystem",
}

# Resource types that wrap/support other content rather than being a clinical
# instance meant to conform to a specific profile. Real US Core IG data shows
# these committed under input/examples|resources with no meta.profile as a
# matter of course (a Bundle's *entries* carry profiles, not the Bundle
# itself; Parameters/Requirements/Library are infrastructure, not patient
# data) — flagging them would just be false-positive noise.
INFRASTRUCTURE_RESOURCE_TYPES = {
    "Bundle",
    "Parameters",
    "Requirements",
    "Library",
    "OperationOutcome",
    "Binary",
}

# Canonicals under these roots are defined by the base spec / THO, never by
# the IG itself, so a reference to one is never "unresolved".
CORE_CANONICAL_PREFIXES = (
    "http://hl7.org/fhir/",
    "http://terminology.hl7.org/",
)

FHIR_VERSION_ALIASES = {
    "R2": "1.0.2",
    "R3": "3.0.2",
    "R4": "4.0.1",
    "R4B": "4.3.0",
    "R5": "5.0.0",
}
VALID_FHIR_VERSIONS = {"1.0.2", "3.0.2", "4.0.0", "4.0.1", "4.3.0", "5.0.0"}

_PINNED_VERSION_RE = re.compile(r"^\d+(\.\d+){1,3}([.\-][0-9A-Za-z]+)*$")
_UNPINNED_WORDS = {"current", "dev", "latest", "master", "main", "draft"}

_TEST_DATA_MARKERS = ("test", "example", "synthetic", "fictitious", "sample", "fake")
_SSN_LIKE = re.compile(r"^\d{3}-\d{2}-\d{4}$")
# Long enough substrings of the ascending/descending digit cycle to catch any
# sequential run up to 17 digits (the longest realistic national-ID length),
# wrapping past 9 back to 0 the way "...7890123..." does.
_ASCENDING_DIGITS = "0123456789" * 3
_DESCENDING_DIGITS = "9876543210" * 3


def _filenames(repo: RepoView) -> dict[str, str]:
    return {path.rsplit("/", 1)[-1]: path for path in repo.paths}


def _is_fhir_relevant_json(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    if not name.lower().endswith(".json"):
        return False
    if CONFORMANCE_FILENAME_RE.match(name):
        return True
    segments = path.split("/")[:-1]
    return any(segment in FHIR_RELEVANT_DIR_SEGMENTS for segment in segments)


def _parse_json(content: str) -> object | None:
    try:
        return json.loads(content)
    except (ValueError, TypeError):
        return None


def _looks_synthetic(path: str, resource: dict) -> bool:
    # Only the file's own basename, not the full path: an "examples/" (or
    # "fsh-generated/") directory is where almost every instance lives, so
    # matching against the whole path would make this exclusion a no-op.
    basename = path.rsplit("/", 1)[-1].lower()
    haystack = " ".join(
        [
            basename,
            str(resource.get("id", "")).lower(),
            json.dumps(resource.get("text", {})).lower(),
        ]
    )
    if any(marker in haystack for marker in _TEST_DATA_MARKERS):
        return True
    for tag in (resource.get("meta") or {}).get("tag", []) or []:
        if isinstance(tag, dict) and tag.get("code") in {"HTEST", "SUBSETTED"}:
            return True
    return False


def _is_realistic_identifier(value: str) -> bool:
    """Heuristic: does `value` look like a real government/patient ID rather
    than an obviously-fake placeholder? A privacy check should prefer false
    negatives over false positives, so anything with a well-known "this is
    clearly fake" shape (all one digit, or a sequential run) is excluded."""
    digits = value.replace("-", "") if _SSN_LIKE.match(value) else value
    if not digits.isdigit() or not 9 <= len(digits) <= 17:
        return False
    if len(set(digits)) == 1:
        return False  # "000-00-0000", "999999999999"
    if digits in _ASCENDING_DIGITS or digits in _DESCENDING_DIGITS:
        return False  # "123-45-6789", "1234567890", "987654321"
    return True


class FhirPack:
    """Checks for FHIR Implementation Guide / package repositories.

    Deliberately deterministic and offline: no HL7 validator JAR, no SUSHI
    invocation, no ValueSet expansion. Those need a JVM / npx / a terminology
    server respectively, none of which this pack assumes are on PATH; where a
    check would need one (`fsh-compile`, `$validate` conformance, ValueSet
    membership, cardinality-vs-base, FHIRPath invariants) it is left for a
    later pass rather than approximated unreliably.
    """

    id = "fhir"

    def detect(self, repo: RepoView) -> float:
        names = set(_filenames(repo))
        if names & FSH_CONFIG_NAMES:
            return 1.0
        if any(path.endswith(".fsh") for path in repo.paths):
            return 1.0
        if any(CONFORMANCE_FILENAME_RE.match(name) for name in names):
            return 1.0
        return 0.0

    def run(self, repo: RepoView, policy: AuditPolicy) -> list[Finding]:
        findings: list[Finding] = []

        sushi_config_path = next(
            (
                path
                for path in repo.paths
                if path.rsplit("/", 1)[-1] in FSH_CONFIG_NAMES
            ),
            None,
        )
        sushi_config = self._parse_sushi_config(repo, sushi_config_path)

        conformance: dict[str, dict] = {}
        instances: dict[str, dict] = {}
        candidate_paths = [path for path in repo.paths if _is_fhir_relevant_json(path)]
        for path in candidate_paths:
            content = repo.files.get(path)
            if content is None:
                continue
            parsed = _parse_json(content)
            if parsed is None:
                findings.append(
                    self._finding(
                        "invalid-json",
                        "error",
                        "config-validity",
                        "Invalid FHIR JSON",
                        f"`{path}` is not valid JSON.",
                        fix="Fix the JSON syntax error, or run it through SUSHI/a JSON linter.",
                        file=path,
                    )
                )
                continue
            if not isinstance(parsed, dict) or "resourceType" not in parsed:
                continue
            if parsed["resourceType"] in CONFORMANCE_RESOURCE_TYPES:
                conformance[path] = parsed
            else:
                instances[path] = parsed

        findings.extend(self._missing_profile_meta(instances))
        findings.extend(self._pii_in_examples(instances))
        findings.extend(self._slicing_no_discriminator(conformance))
        if sushi_config is not None and sushi_config_path is not None:
            findings.extend(self._unresolved_canonicals(sushi_config, conformance))
            findings.extend(self._unpinned_dependencies(sushi_config, sushi_config_path))
            findings.extend(
                self._fhir_version_checks(sushi_config, conformance, sushi_config_path)
            )
        findings.extend(self._fsh_compile_availability(repo))
        return findings

    # -- individual checks --------------------------------------------------

    def _parse_sushi_config(self, repo: RepoView, path: str | None) -> dict | None:
        if path is None:
            return None
        content = repo.files.get(path)
        if content is None:
            return None
        try:
            parsed = yaml.safe_load(content)
        except yaml.YAMLError:
            return None
        return parsed if isinstance(parsed, dict) else None

    def _missing_profile_meta(self, instances: dict[str, dict]) -> list[Finding]:
        findings = []
        for path, resource in instances.items():
            if resource.get("resourceType") in INFRASTRUCTURE_RESOURCE_TYPES:
                continue
            profiles = ((resource.get("meta") or {}).get("profile")) or []
            if not profiles:
                findings.append(
                    self._finding(
                        "missing-profile-meta",
                        "warning",
                        "interoperability",
                        "Example has no meta.profile",
                        f"`{path}` ({resource.get('resourceType')}) has no `meta.profile`, "
                        "so conformance to any profile can't be checked.",
                        fix="Add meta.profile with the canonical URL(s) this example conforms to.",
                        file=path,
                    )
                )
        return findings

    def _pii_in_examples(self, instances: dict[str, dict]) -> list[Finding]:
        findings = []
        for path, resource in instances.items():
            if resource.get("resourceType") not in {"Patient", "RelatedPerson", "Person"}:
                continue
            if _looks_synthetic(path, resource):
                continue
            for identifier in resource.get("identifier", []) or []:
                value = identifier.get("value") if isinstance(identifier, dict) else None
                if isinstance(value, str) and _is_realistic_identifier(value):
                    findings.append(
                        self._finding(
                            "pii-in-example",
                            "error",
                            "pii",
                            "Realistic-looking identifier in an example",
                            f"`{path}` has an identifier that looks like a real ID, with no "
                            "test-data marker (a 'test'/'example'/'synthetic' filename, id, "
                            "or an HTEST meta.tag).",
                            fix="Use an obviously-fake identifier (e.g. a repeating or "
                            "sequential digit pattern) or tag the resource "
                            "meta.tag = http://terminology.hl7.org/CodeSystem/v3-ActReason#HTEST.",
                            file=path,
                        )
                    )
                    break
        return findings

    def _slicing_no_discriminator(self, conformance: dict[str, dict]) -> list[Finding]:
        findings = []
        for path, resource in conformance.items():
            if resource.get("resourceType") != "StructureDefinition":
                continue
            # Prefer differential (what the IG authored); snapshot repeats the
            # same slices plus everything inherited, so only fall back to it
            # when there's no differential to look at.
            elements = (resource.get("differential") or {}).get("element")
            if not elements:
                elements = (resource.get("snapshot") or {}).get("element")
            for element in elements or []:
                slicing = element.get("slicing")
                if slicing is not None and not slicing.get("discriminator"):
                    findings.append(
                        self._finding(
                            "slicing-no-discriminator",
                            "warning",
                            "interoperability",
                            "Slicing with no discriminator",
                            f"`{path}` slices `{element.get('path', '?')}` without a "
                            "discriminator, so consumers can't tell which slice a "
                            "repeated element belongs to.",
                            fix="Add slicing.discriminator (type + path) or remove the slicing.",
                            file=path,
                        )
                    )
        return findings

    def _unresolved_canonicals(
        self, sushi_config: dict, conformance: dict[str, dict]
    ) -> list[Finding]:
        canonical_root = sushi_config.get("canonical")
        if not isinstance(canonical_root, str) or not canonical_root:
            return []
        defined = {
            resource["url"] for resource in conformance.values() if isinstance(resource.get("url"), str)
        }
        findings = []
        seen: set[tuple[str, str]] = set()
        for path, resource in conformance.items():
            for ref in self._referenced_canonicals(resource):
                if not ref.startswith(canonical_root):
                    continue  # external dependency; assumed resolved by its package
                if ref.startswith(CORE_CANONICAL_PREFIXES):
                    continue
                if ref in defined:
                    continue
                key = (path, ref)
                if key in seen:
                    continue
                seen.add(key)
                findings.append(
                    self._finding(
                        "unresolved-canonical",
                        "error",
                        "reference-integrity",
                        "Unresolved canonical reference",
                        f"`{path}` references `{ref}`, which is under this IG's own "
                        "canonical root but isn't defined by any resource in the repo.",
                        fix="Create the missing profile/ValueSet/CodeSystem, or fix the typo "
                        "in the canonical URL.",
                        file=path,
                    )
                )
        return findings

    @staticmethod
    def _referenced_canonicals(resource: dict) -> set[str]:
        refs: set[str] = set()
        base = resource.get("baseDefinition")
        if isinstance(base, str):
            refs.add(base)
        for section in ("differential", "snapshot"):
            for element in (resource.get(section) or {}).get("element", []) or []:
                for type_entry in element.get("type", []) or []:
                    if not isinstance(type_entry, dict):
                        continue
                    for key in ("profile", "targetProfile"):
                        value = type_entry.get(key)
                        if isinstance(value, str):
                            refs.add(value)
                        elif isinstance(value, list):
                            refs.update(v for v in value if isinstance(v, str))
                binding = element.get("binding")
                if isinstance(binding, dict) and isinstance(binding.get("valueSet"), str):
                    refs.add(binding["valueSet"])
        compose = resource.get("compose") or {}
        for entry in (compose.get("include") or []) + (compose.get("exclude") or []):
            if not isinstance(entry, dict):
                continue
            if isinstance(entry.get("system"), str):
                refs.add(entry["system"])
            for value_set in entry.get("valueSet") or []:
                if isinstance(value_set, str):
                    refs.add(value_set)
        for entry in resource.get("global", []) or []:
            if isinstance(entry, dict) and isinstance(entry.get("profile"), str):
                refs.add(entry["profile"])
        return refs

    def _unpinned_dependencies(self, sushi_config: dict, config_path: str) -> list[Finding]:
        dependencies = sushi_config.get("dependencies")
        if not isinstance(dependencies, dict):
            return []
        findings = []
        for package_id, spec in dependencies.items():
            version = spec.get("version") if isinstance(spec, dict) else spec
            if isinstance(version, (int, float)):
                version = str(version)
            pinned = (
                isinstance(version, str)
                and version.lower() not in _UNPINNED_WORDS
                and not any(ch in version for ch in "^~<>*xX")
                and bool(_PINNED_VERSION_RE.match(version))
            )
            if not pinned:
                findings.append(
                    self._finding(
                        "unpinned-dependency",
                        "warning",
                        "version-compat",
                        "Unpinned IG dependency",
                        f"Dependency `{package_id}` is not pinned to an exact version "
                        f"(got `{version!r}`).",
                        fix="Pin it to an exact released version, e.g. "
                        f"`{package_id}: 6.1.0`.",
                        file=config_path,
                    )
                )
        return findings

    def _fhir_version_checks(
        self, sushi_config: dict, conformance: dict[str, dict], config_path: str
    ) -> list[Finding]:
        findings = []
        declared = self._normalise_versions(sushi_config.get("fhirVersion"))
        if declared:
            invalid = [v for v in declared if v not in VALID_FHIR_VERSIONS]
            for value in invalid:
                findings.append(
                    self._finding(
                        "invalid-fhir-version",
                        "error",
                        "version-compat",
                        "Unrecognised fhirVersion",
                        f"`{config_path}` declares fhirVersion `{value}`, which isn't a "
                        "released FHIR version.",
                        fix="Use a released version (e.g. 4.0.1) or an alias (R4, R4B, R5).",
                        file=config_path,
                    )
                )
            for path, resource in conformance.items():
                if resource.get("resourceType") != "ImplementationGuide":
                    continue
                ig_versions = self._normalise_versions(resource.get("fhirVersion"))
                if ig_versions and set(ig_versions) != set(declared):
                    findings.append(
                        self._finding(
                            "version-mismatch",
                            "error",
                            "version-compat",
                            "fhirVersion mismatch",
                            f"`{config_path}` declares fhirVersion {sorted(declared)} but "
                            f"`{path}` declares {sorted(ig_versions)}.",
                            fix="Make the ImplementationGuide resource's fhirVersion match "
                            "sushi-config.yaml (rebuild with SUSHI if it's generated).",
                            file=path,
                        )
                    )
        return findings

    @staticmethod
    def _normalise_versions(value: object) -> list[str]:
        if value is None:
            return []
        raw = value if isinstance(value, list) else [value]
        return [
            FHIR_VERSION_ALIASES.get(str(v), str(v))
            for v in raw
            if isinstance(v, (str, int, float))
        ]

    def _fsh_compile_availability(self, repo: RepoView) -> list[Finding]:
        if not any(path.endswith(".fsh") for path in repo.paths):
            return []
        if shutil.which("sushi"):
            return []  # present, but v1 doesn't yet invoke it (needs filesystem access)
        return [
            self._finding(
                "fsh-compile-skipped",
                "info",
                "config-validity",
                "FSH compile check skipped",
                "SUSHI isn't on PATH, so .fsh files weren't compiled to check for errors.",
                fix="Install SUSHI (`npm i -g fsh-sushi`) to enable this check.",
            )
        ]

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
            rule_id=f"fhir/{rule_suffix}",
            pack="fhir",
            severity=severity,
            category=category,
            title=title,
            message=message,
            fix=fix,
            file=file,
            line=line,
            docs_url=f"{TOOL_URI}#fhir-{rule_suffix}",
        )
