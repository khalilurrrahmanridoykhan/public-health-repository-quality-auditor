from __future__ import annotations

from ..models import TOOL_URI, AuditPolicy, CheckResult, Finding
from .base import RepoView

DEPENDENCY_FILES = {
    "requirements.txt",
    "pyproject.toml",
    "environment.yml",
    "environment.yaml",
    "renv.lock",
    "package-lock.json",
    "poetry.lock",
    "uv.lock",
}
TEST_PREFIXES = ("tests/", "test/", ".github/workflows/")
DATA_DICTIONARY_NAMES = {
    "data_dictionary.csv",
    "data-dictionary.csv",
    "data_dictionary.md",
    "data-dictionary.md",
    "codebook.csv",
    "codebook.md",
}
REPRODUCTION_FILES = {"makefile", "dvc.yaml", "snakefile", "nextflow.config"}
ETHICS_TERMS = ("ethics", "irb", "institutional review", "consent")

# README anchors for each check, matching this project's own README headings.
DOCS_ANCHORS = {
    "readme": "project-documentation",
    "license": "license",
    "citation": "citation",
    "dependencies": "dependencies",
    "reproduction": "reproduction",
    "tests": "tests-and-ci",
    "data_dictionary": "data-dictionary",
    "provenance": "data-provenance",
    "privacy": "privacy",
    "ethics": "ethics",
}


def checks(repo: RepoView, policy: AuditPolicy) -> list[CheckResult]:
    """The 10 deterministic repository-hygiene checks. Unchanged in behaviour
    from the pre-pack `audit_repository`; only the file-access layer moved to
    `RepoView`."""
    readme = repo.text("readme.md", "readme.rst")

    license_files = repo.find({"license", "license.md", "license.txt", "copying"})
    citation_files = repo.find({"citation.cff", "codemeta.json"})
    dependency_files = repo.find(DEPENDENCY_FILES)
    dictionary_files = repo.find(DATA_DICTIONARY_NAMES)
    reproduction_files = repo.find(REPRODUCTION_FILES)
    test_files = repo.with_prefix(TEST_PREFIXES)
    privacy_evidence = tuple(term for term in policy.privacy_terms if term in readme)
    ethics_evidence = tuple(term for term in ETHICS_TERMS if term in readme)
    source_evidence = tuple(
        term for term in ("data source", "data provenance", "source data") if term in readme
    )

    results = [
        CheckResult(
            "readme",
            "Project documentation",
            bool(readme.strip()),
            12,
            "Add a README explaining the research question, methods, data, and usage.",
            ("README",) if readme else (),
        ),
        CheckResult(
            "license",
            "License",
            bool(license_files),
            10,
            "Add a LICENSE and clarify whether data have separate reuse terms.",
            license_files,
        ),
        CheckResult(
            "citation",
            "Machine-readable citation",
            bool(citation_files),
            8,
            "Add CITATION.cff with authors, title, version, and preferred citation.",
            citation_files,
        ),
        CheckResult(
            "dependencies",
            "Dependency specification",
            bool(dependency_files),
            12,
            "Add a dependency or environment file with compatible version ranges.",
            dependency_files,
        ),
        CheckResult(
            "reproduction",
            "One-command reproduction",
            bool(reproduction_files)
            or "make reproduce" in readme
            or "how to reproduce" in readme,
            14,
            "Provide a Makefile, workflow, or documented single command that regenerates outputs.",
            reproduction_files,
        ),
        CheckResult(
            "tests",
            "Automated tests or CI",
            bool(test_files),
            12,
            "Add tests and a CI workflow for data validation and analytical invariants.",
            test_files[:5],
        ),
        CheckResult(
            "data_dictionary",
            "Data dictionary or codebook",
            bool(dictionary_files) or "data description" in readme,
            10,
            "Document variables, units, missing-value conventions, and allowed values.",
            dictionary_files,
        ),
        CheckResult(
            "provenance",
            "Data provenance",
            bool(source_evidence),
            8,
            "Document each data source, access date, transformation, and license.",
            source_evidence,
        ),
        CheckResult(
            "privacy",
            "Privacy and sensitive-data warning",
            bool(privacy_evidence),
            8,
            "State whether data are aggregate, synthetic, de-identified, or sensitive and define safe-use limits.",
            privacy_evidence,
        ),
        CheckResult(
            "ethics",
            "Ethics statement",
            bool(ethics_evidence),
            6,
            "State the ethics/IRB basis or explain why review was not required.",
            ethics_evidence,
        ),
    ]
    return [result for result in results if result.key not in policy.disabled_checks]


def findings_for(repo: RepoView, results: list[CheckResult]) -> list[Finding]:
    """Project a hygiene `CheckResult` list into general-purpose `Finding`s
    (one per failed check), for GitHub annotations and SARIF output."""
    anchor = repo.anchor()
    findings = []
    for result in results:
        if result.passed:
            continue
        findings.append(
            Finding(
                rule_id=f"hygiene/{result.key}",
                pack="hygiene",
                severity="warning",
                category="hygiene",
                title=result.title,
                message=result.recommendation,
                fix=result.recommendation,
                file=anchor,
                line=1 if anchor else None,
                docs_url=f"{TOOL_URI}#{DOCS_ANCHORS.get(result.key, '')}",
                evidence=result.evidence,
            )
        )
    return findings


class HygienePack:
    """The original 10 file-presence + README-keyword checks, as a pack."""

    id = "hygiene"

    def detect(self, repo: RepoView) -> float:
        return 1.0  # applies to every repository

    def checks(self, repo: RepoView, policy: AuditPolicy) -> list[CheckResult]:
        return checks(repo, policy)

    def run(self, repo: RepoView, policy: AuditPolicy) -> list[Finding]:
        return findings_for(repo, self.checks(repo, policy))
