from ph_repo_auditor.auditor import audit_repository


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
