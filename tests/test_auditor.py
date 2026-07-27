from ph_repo_auditor.auditor import audit_repository
from ph_repo_auditor.models import AuditPolicy
from ph_repo_auditor.policy import parse_policy


def test_complete_repository_scores_highly():
    files = {
        "README.md": """
        # Study
        ## Data source
        Public aggregate data. No patient-level data.
        ## Ethics
        IRB review was not required.
        """,
        "LICENSE": None,
        "CITATION.cff": None,
        "requirements.txt": None,
        "Makefile": None,
        "tests/test_analysis.py": None,
        "docs/data-dictionary.csv": None,
    }

    report = audit_repository("owner/study", files)

    assert report.score == 100
    assert report.grade == "A"
    assert all(result.passed for result in report.results)


def test_empty_repository_returns_actionable_report():
    report = audit_repository("owner/empty", {})

    assert report.score == 0
    assert report.grade == "F"
    assert len(report.results) == 10
    assert "Recommended next steps" in report.to_markdown()


def test_paths_are_case_insensitive():
    report = audit_repository(
        "owner/study",
        {
            "README.MD": "Data provenance. Privacy. Ethics.",
            "License.md": None,
            "Requirements.txt": None,
            "CITATION.CFF": None,
            "Makefile": None,
            ".github/workflows/ci.yml": None,
            "docs/CodeBook.md": None,
        },
    )

    assert report.score == 100


def test_policy_controls_threshold_checks_paths_and_required_files():
    policy, warnings = parse_policy(
        """
minimum_score: 95
disabled_checks: [ethics]
required_files: [CITATION.cff, docs/protocol.md]
ignore_paths: [generated]
"""
    )
    report = audit_repository(
        "owner/study",
        {
            "README.md": "Data provenance. Privacy.",
            "LICENSE": None,
            "CITATION.cff": None,
            "requirements.txt": None,
            "Makefile": None,
            ".github/workflows/ci.yml": None,
            "docs/codebook.md": None,
            "generated/tests/test_fake.py": None,
        },
        policy,
        warnings,
    )

    assert not warnings
    assert "ethics" not in {result.key for result in report.results}
    assert report.minimum_score == 95
    assert report.missing_required_files == ("docs/protocol.md",)
    assert not report.passed


def test_invalid_policy_uses_safe_defaults_and_reports_warnings():
    policy, warnings = parse_policy(
        """
minimum_score: 101
disabled_checks: [unknown]
required_files: invalid
"""
    )

    assert policy == AuditPolicy()
    assert len(warnings) == 3
