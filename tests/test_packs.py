import pytest

from ph_repo_auditor.auditor import audit_repository
from ph_repo_auditor.models import AuditPolicy
from ph_repo_auditor.packs import HygienePack, PackRegistry, RepoView


def test_hygiene_pack_always_detects():
    repo = RepoView({})
    assert HygienePack().detect(repo) == 1.0


def test_registry_defaults_to_every_detecting_pack():
    repo = RepoView({"README.md": "hello"})
    active = PackRegistry().select(repo)
    assert {pack.id for pack in active} == {"hygiene"}


def test_registry_rejects_unknown_pack_id():
    repo = RepoView({})
    with pytest.raises(ValueError, match="fhir"):
        PackRegistry().select(repo, ("fhir",))


def test_registry_can_select_a_subset_of_packs():
    repo = RepoView({})
    active = PackRegistry().select(repo, ("hygiene",))
    assert [pack.id for pack in active] == ["hygiene"]


def test_audit_repository_with_an_empty_registry_scores_zero_and_finds_nothing():
    repo_files = {"README.md": "Ethics. Privacy. Data provenance."}
    report = audit_repository(
        "owner/study", repo_files, registry=PackRegistry(())
    )
    assert report.results == []
    assert report.findings == ()
    assert report.pack_scores == ()
    assert report.score == 0


def test_findings_mirror_failed_checks_and_carry_docs_urls():
    report = audit_repository("owner/empty", {})
    assert len(report.findings) == 10
    assert all(finding.pack == "hygiene" for finding in report.findings)
    assert all(finding.severity == "warning" for finding in report.findings)
    readme_finding = next(f for f in report.findings if f.rule_id == "hygiene/readme")
    assert readme_finding.docs_url.endswith("#project-documentation")
    # No tracked files at all: nothing to anchor an annotation to.
    assert readme_finding.file is None


def test_findings_anchor_to_the_readme_when_present():
    report = audit_repository("owner/study", {"README.md": "", "LICENSE": None})
    readme_finding = next(f for f in report.findings if f.rule_id == "hygiene/readme")
    assert readme_finding.file == "readme.md"
    assert readme_finding.line == 1


def test_passing_checks_produce_no_findings():
    files = {
        "README.md": "Data provenance. Privacy. Ethics.",
        "LICENSE": None,
        "CITATION.cff": None,
        "requirements.txt": None,
        "Makefile": None,
        "tests/test_analysis.py": None,
        "docs/data-dictionary.csv": None,
    }
    report = audit_repository("owner/study", files)
    assert report.score == 100
    assert report.findings == ()
    assert len(report.pack_scores) == 1
    assert report.pack_scores[0].pack == "hygiene"
    assert report.pack_scores[0].score == 100


def test_pack_scores_do_not_average_with_hygiene():
    # A stand-in second pack with its own (lower) score must not move the
    # hygiene-driven `report.score`.
    class AlwaysFailsPack:
        id = "stub"

        def detect(self, repo):
            return 1.0

        def run(self, repo, policy):
            from ph_repo_auditor.models import Finding

            return [
                Finding(
                    rule_id="stub/always-fails",
                    pack="stub",
                    severity="error",
                    category="stub",
                    title="Stub failure",
                    message="Always fails, for testing.",
                )
            ]

    registry = PackRegistry((HygienePack(), AlwaysFailsPack()))
    files = {
        "README.md": "Data provenance. Privacy. Ethics.",
        "LICENSE": None,
        "CITATION.cff": None,
        "requirements.txt": None,
        "Makefile": None,
        "tests/test_analysis.py": None,
        "docs/data-dictionary.csv": None,
    }
    report = audit_repository("owner/study", files, registry=registry)
    assert report.score == 100  # unaffected by the stub pack's finding
    assert len(report.findings) == 1
    assert report.findings[0].pack == "stub"


def test_repo_view_honours_ignore_paths():
    repo = RepoView(
        {"generated/tests/test_fake.py": None, "tests/test_real.py": None},
        ignore_paths=("generated",),
    )
    assert repo.paths == frozenset({"tests/test_real.py"})


def test_to_sarif_has_one_rule_per_rule_id_and_a_location_when_anchored():
    report = audit_repository("owner/study", {"README.md": "", "LICENSE": None})
    sarif = report.to_sarif()
    assert sarif["version"] == "2.1.0"
    run = sarif["runs"][0]
    rule_ids = {rule["id"] for rule in run["tool"]["driver"]["rules"]}
    assert rule_ids == {finding.rule_id for finding in report.findings}
    readme_result = next(
        r for r in run["results"] if r["ruleId"] == "hygiene/readme"
    )
    assert readme_result["locations"][0]["physicalLocation"]["artifactLocation"][
        "uri"
    ] == "readme.md"


def test_to_sarif_omits_locations_for_unanchored_findings():
    report = audit_repository("owner/empty", {})
    sarif = report.to_sarif()
    assert all("locations" not in result for result in sarif["runs"][0]["results"])
