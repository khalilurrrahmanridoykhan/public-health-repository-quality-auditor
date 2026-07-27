from collections.abc import Mapping

from .models import AuditPolicy, AuditReport, CheckResult


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
PRIVACY_TERMS = (
    "privacy",
    "de-ident",
    "anonym",
    "patient",
    "person-level",
    "person level",
    "sensitive data",
)
ETHICS_TERMS = ("ethics", "irb", "institutional review", "consent")


def _normalise_paths(files: Mapping[str, str | None]) -> dict[str, str | None]:
    return {path.strip("/").lower(): content for path, content in files.items()}


def _find(paths: set[str], names: set[str]) -> tuple[str, ...]:
    return tuple(sorted(path for path in paths if path.rsplit("/", 1)[-1] in names))


def audit_repository(
    repository: str,
    files: Mapping[str, str | None],
    policy: AuditPolicy | None = None,
    policy_warnings: tuple[str, ...] = (),
) -> AuditReport:
    policy = policy or AuditPolicy()
    normalised = _normalise_paths(files)
    normalised = {
        path: content
        for path, content in normalised.items()
        if not any(
            path == prefix or path.startswith(f"{prefix}/")
            for prefix in policy.ignore_paths
        )
    }
    paths = set(normalised)
    readme = next(
        (content or "" for path, content in normalised.items() if path in {"readme.md", "readme.rst"}),
        "",
    ).lower()

    license_files = _find(paths, {"license", "license.md", "license.txt", "copying"})
    citation_files = _find(paths, {"citation.cff", "codemeta.json"})
    dependency_files = _find(paths, DEPENDENCY_FILES)
    dictionary_files = _find(paths, DATA_DICTIONARY_NAMES)
    reproduction_files = _find(paths, REPRODUCTION_FILES)
    test_files = tuple(
        sorted(path for path in paths if path.startswith(TEST_PREFIXES))
    )
    privacy_evidence = tuple(term for term in PRIVACY_TERMS if term in readme)
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
    results = [
        result for result in results if result.key not in policy.disabled_checks
    ]
    missing_required_files = tuple(
        path for path in policy.required_files if path not in paths
    )
    return AuditReport(
        repository=repository,
        results=results,
        minimum_score=policy.minimum_score,
        missing_required_files=missing_required_files,
        policy_warnings=policy_warnings,
    )
