from ph_repo_auditor.auditor import audit_repository
from ph_repo_auditor.standards import (
    STATUS_CLEAN,
    STATUS_FLAGGED,
    STATUS_NOT_AUTOMATABLE,
    dpg_readiness,
    dpg_readiness_markdown,
)

CLEAN_FILES = {
    "README.md": "Data provenance. Privacy. Ethics.",
    "LICENSE": None,
    "CITATION.cff": None,
    "requirements.txt": None,
    "Makefile": None,
    "tests/test_analysis.py": None,
    "docs/data-dictionary.csv": None,
}


def _by_id(results, indicator_id):
    return next(result for result in results if result.id == indicator_id)


def test_dpg_readiness_covers_all_nine_indicators():
    report = audit_repository("owner/repo", CLEAN_FILES)
    results = dpg_readiness(report)
    assert [result.id for result in results] == [
        "1",
        "2",
        "3",
        "4",
        "5",
        "6",
        "7",
        "8",
        "9a",
        "9b",
        "9c",
    ]


def test_not_automatable_indicators_never_claim_a_pass_or_fail():
    report = audit_repository("owner/repo", CLEAN_FILES)
    results = dpg_readiness(report)
    for indicator_id in ("1", "3", "4", "6", "9b", "9c"):
        assert _by_id(results, indicator_id).status == STATUS_NOT_AUTOMATABLE


def test_clean_repo_shows_clean_for_every_automated_indicator():
    report = audit_repository("owner/repo", CLEAN_FILES)
    results = dpg_readiness(report)
    for indicator_id in ("2", "5", "7", "8", "9a"):
        assert _by_id(results, indicator_id).status == STATUS_CLEAN


def test_missing_license_flags_indicator_2_only():
    files = dict(CLEAN_FILES)
    del files["LICENSE"]
    report = audit_repository("owner/repo", files)
    results = dpg_readiness(report)
    assert _by_id(results, "2").status == STATUS_FLAGGED
    assert "No LICENSE file" in _by_id(results, "2").detail
    # Everything else keeps its prior status — one failing check doesn't
    # cascade into unrelated indicators.
    assert _by_id(results, "5").status == STATUS_CLEAN


def test_missing_documentation_checks_flags_indicator_5_with_specifics():
    report = audit_repository("owner/empty", {})
    results = dpg_readiness(report)
    indicator_5 = _by_id(results, "5")
    assert indicator_5.status == STATUS_FLAGGED
    assert "readme" in indicator_5.detail
    assert "dependencies" in indicator_5.detail
    assert "reproduction" in indicator_5.detail


def test_missing_privacy_language_flags_indicator_7():
    files = {**CLEAN_FILES, "README.md": "Just a plain readme, nothing else."}
    report = audit_repository("owner/repo", files)
    results = dpg_readiness(report)
    assert _by_id(results, "7").status == STATUS_FLAGGED


def test_a_pii_pack_finding_flags_both_indicator_8_and_9a():
    # A committed secret is an error-severity pii finding — it should show
    # up both as a standards/best-practices gap (8) and a data-privacy
    # gap (9a), the two indicators that are actually about this.
    report = audit_repository(
        "owner/repo", {".env": "API_KEY=sk-real-secret-123\n", **CLEAN_FILES}
    )
    results = dpg_readiness(report)
    assert _by_id(results, "8").status == STATUS_FLAGGED
    assert "pii" in _by_id(results, "8").detail
    assert _by_id(results, "9a").status == STATUS_FLAGGED
    assert "secrets/committed-env-values" in _by_id(results, "9a").detail


OPENMRS_CONFIG_XML = """<?xml version="1.0" encoding="UTF-8"?>
<module configVersion="1.0">
    <id>@MODULE_ID@</id>
    <name>@MODULE_NAME@</name>
    <package>@MODULE_PACKAGE@</package>
</module>
"""


def test_a_non_pii_error_finding_flags_indicator_8_but_not_9a():
    # Only the pii pack's findings are evidence for 9a specifically —
    # some other pack's error finding (an OpenMRS Liquibase changeSet
    # with no id/author, openmrs/liquibase-missing-id, error-severity)
    # is still a standards/best-practices gap (8), but not a data-privacy
    # one specifically.
    changelog = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<databaseChangeLog xmlns="http://www.liquibase.org/xml/ns/dbchangelog">\n'
        '<changeSet author="me"><sql>SELECT 1</sql></changeSet>\n'
        "</databaseChangeLog>\n"
    )
    report = audit_repository(
        "owner/repo",
        {
            **CLEAN_FILES,
            "config.xml": OPENMRS_CONFIG_XML,
            "api/liquibase.xml": changelog,
        },
    )
    hits = [f for f in report.findings if f.severity == "error"]
    assert any(f.pack == "openmrs" for f in hits)
    results = dpg_readiness(report)
    assert _by_id(results, "8").status == STATUS_FLAGGED
    assert "openmrs" in _by_id(results, "8").detail
    assert _by_id(results, "9a").status == STATUS_CLEAN


def test_markdown_renders_a_disclaimer_and_every_indicator():
    report = audit_repository("owner/repo", CLEAN_FILES)
    markdown = dpg_readiness_markdown(dpg_readiness(report))
    assert "not a certification" in markdown
    assert "DPG Registry submission" in markdown
    for indicator_id in ("1", "2", "3", "4", "5", "6", "7", "8", "9a", "9b", "9c"):
        assert f"| {indicator_id} |" in markdown


def test_markdown_uses_the_right_icon_per_status():
    report = audit_repository("owner/repo", CLEAN_FILES)
    markdown = dpg_readiness_markdown(dpg_readiness(report))
    assert "| ✅ |" in markdown  # indicator 2 (license present)
    assert "| ⚪ |" in markdown  # indicator 1 (not automatable)


def test_cli_dpg_readiness_format_renders_for_a_fixture_repo(tmp_path, capsys):
    from ph_repo_auditor.cli import main

    (tmp_path / "README.md").write_text("Data provenance. Privacy. Ethics.\n")
    (tmp_path / "LICENSE").write_text("MIT")

    main([str(tmp_path), "--format", "dpg-readiness"])
    output = capsys.readouterr().out
    assert "DPG Standard readiness" in output
    assert "| 2 |" in output
    assert "not a certification" in output
