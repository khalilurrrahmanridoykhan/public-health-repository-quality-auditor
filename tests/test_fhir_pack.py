import json

import pytest

from ph_repo_auditor.auditor import audit_repository
from ph_repo_auditor.models import AuditPolicy
from ph_repo_auditor.packs import FhirPack, PackRegistry, RepoView
from ph_repo_auditor.packs.fhir import _is_realistic_identifier


SUSHI_CONFIG = """
canonical: http://example.org/fhir/demo
fhirVersion: 4.0.1
dependencies:
  hl7.fhir.us.core: 6.1.0
  hl7.fhir.uv.ips: current
"""

STRUCTURE_DEFINITION = json.dumps(
    {
        "resourceType": "StructureDefinition",
        "url": "http://example.org/fhir/demo/StructureDefinition/DemoPatient",
        "baseDefinition": "http://hl7.org/fhir/StructureDefinition/Patient",
        "differential": {
            "element": [
                {
                    "path": "Patient.identifier",
                    "slicing": {
                        "discriminator": [{"type": "value", "path": "system"}],
                        "rules": "open",
                    },
                },
                {
                    "path": "Patient.telecom",
                    "slicing": {"rules": "open"},  # no discriminator: should flag
                },
                {
                    "path": "Patient.extension",
                    "type": [
                        {
                            "code": "Extension",
                            "profile": [
                                "http://example.org/fhir/demo/StructureDefinition/MissingExtension"
                            ],
                        }
                    ],
                },
            ]
        },
    }
)


def _repo(files: dict[str, str | None]) -> RepoView:
    return RepoView(files)


def test_detect_requires_a_fhir_marker():
    assert FhirPack().detect(_repo({"README.md": "hello"})) == 0.0
    assert FhirPack().detect(_repo({"sushi-config.yaml": SUSHI_CONFIG})) == 1.0
    assert FhirPack().detect(_repo({"input/fsh/patients.fsh": "Instance: x"})) == 1.0
    assert (
        FhirPack().detect(_repo({"fsh-generated/resources/StructureDefinition-x.json": "{}"}))
        == 1.0
    )


def test_missing_profile_meta_flags_examples_without_it():
    files = {
        "sushi-config.yaml": SUSHI_CONFIG,
        "examples/patient-no-profile.json": json.dumps(
            {"resourceType": "Patient", "id": "example"}
        ),
    }
    findings = FhirPack().run(_repo(files), AuditPolicy())
    ids = {f.rule_id for f in findings}
    assert "fhir/missing-profile-meta" in ids


def test_missing_profile_meta_does_not_flag_examples_with_it():
    files = {
        "sushi-config.yaml": SUSHI_CONFIG,
        "examples/patient-example.json": json.dumps(
            {
                "resourceType": "Patient",
                "id": "example",
                "meta": {"profile": ["http://example.org/fhir/demo/StructureDefinition/DemoPatient"]},
            }
        ),
    }
    findings = FhirPack().run(_repo(files), AuditPolicy())
    assert not any(f.rule_id == "fhir/missing-profile-meta" for f in findings)


def test_missing_profile_meta_ignores_infrastructure_resource_types():
    # Bundle/Parameters/Requirements/Library wrap or support content rather
    # than being a clinical instance meant to conform to a specific profile.
    files = {
        "sushi-config.yaml": SUSHI_CONFIG,
        "examples/manifest-bundle.json": json.dumps({"resourceType": "Bundle", "type": "collection"}),
        "examples/manifest.json": json.dumps({"resourceType": "Parameters"}),
    }
    findings = FhirPack().run(_repo(files), AuditPolicy())
    assert not any(f.rule_id == "fhir/missing-profile-meta" for f in findings)


def test_unresolved_canonical_flags_a_reference_under_the_igs_own_root():
    files = {
        "sushi-config.yaml": SUSHI_CONFIG,
        "fsh-generated/resources/StructureDefinition-DemoPatient.json": STRUCTURE_DEFINITION,
    }
    findings = FhirPack().run(_repo(files), AuditPolicy())
    unresolved = [f for f in findings if f.rule_id == "fhir/unresolved-canonical"]
    assert len(unresolved) == 1
    assert "MissingExtension" in unresolved[0].message


def test_unresolved_canonical_ignores_core_and_external_dependency_canonicals():
    # baseDefinition points at core FHIR; that must never be "unresolved".
    files = {
        "sushi-config.yaml": SUSHI_CONFIG,
        "fsh-generated/resources/StructureDefinition-Minimal.json": json.dumps(
            {
                "resourceType": "StructureDefinition",
                "url": "http://example.org/fhir/demo/StructureDefinition/Minimal",
                "baseDefinition": "http://hl7.org/fhir/StructureDefinition/Patient",
            }
        ),
    }
    findings = FhirPack().run(_repo(files), AuditPolicy())
    assert not any(f.rule_id == "fhir/unresolved-canonical" for f in findings)


def test_slicing_no_discriminator():
    files = {
        "sushi-config.yaml": SUSHI_CONFIG,
        "fsh-generated/resources/StructureDefinition-DemoPatient.json": STRUCTURE_DEFINITION,
    }
    findings = FhirPack().run(_repo(files), AuditPolicy())
    slicing_findings = [f for f in findings if f.rule_id == "fhir/slicing-no-discriminator"]
    assert len(slicing_findings) == 1
    assert "Patient.telecom" in slicing_findings[0].message


def test_unpinned_dependency_flags_current_but_not_the_pinned_one():
    files = {"sushi-config.yaml": SUSHI_CONFIG}
    findings = FhirPack().run(_repo(files), AuditPolicy())
    unpinned = {f.message for f in findings if f.rule_id == "fhir/unpinned-dependency"}
    assert any("hl7.fhir.uv.ips" in m for m in unpinned)
    assert not any("hl7.fhir.us.core" in m for m in unpinned)


def test_invalid_fhir_version_is_flagged():
    files = {"sushi-config.yaml": "canonical: http://example.org/fhir/demo\nfhirVersion: 9.9.9\n"}
    findings = FhirPack().run(_repo(files), AuditPolicy())
    assert any(f.rule_id == "fhir/invalid-fhir-version" for f in findings)


def test_fhir_version_aliases_are_accepted():
    files = {"sushi-config.yaml": "canonical: http://example.org/fhir/demo\nfhirVersion: R4\n"}
    findings = FhirPack().run(_repo(files), AuditPolicy())
    assert not any(f.rule_id == "fhir/invalid-fhir-version" for f in findings)


def test_version_mismatch_between_config_and_ig_resource():
    files = {
        "sushi-config.yaml": SUSHI_CONFIG,  # fhirVersion: 4.0.1
        "fsh-generated/resources/ImplementationGuide-demo.json": json.dumps(
            {"resourceType": "ImplementationGuide", "fhirVersion": ["4.3.0"]}
        ),
    }
    findings = FhirPack().run(_repo(files), AuditPolicy())
    mismatches = [f for f in findings if f.rule_id == "fhir/version-mismatch"]
    assert len(mismatches) == 1
    assert "4.0.1" in mismatches[0].message and "4.3.0" in mismatches[0].message


def test_non_json_files_under_a_relevant_directory_are_ignored():
    # Real IGs commit fsh-generated/*.md and *.txt build artifacts alongside
    # the generated JSON; those must never be parsed as (invalid) FHIR JSON.
    files = {
        "sushi-config.yaml": SUSHI_CONFIG,
        "fsh-generated/fsh-index.txt": "not json and not meant to be",
        "input/resources/readme.md": "# Resources\nnot json either",
    }
    findings = FhirPack().run(_repo(files), AuditPolicy())
    assert not any(f.rule_id == "fhir/invalid-json" for f in findings)


def test_invalid_json_is_flagged_for_fhir_relevant_files_only():
    files = {
        "sushi-config.yaml": SUSHI_CONFIG,
        "fsh-generated/resources/StructureDefinition-broken.json": "{not json",
    }
    findings = FhirPack().run(_repo(files), AuditPolicy())
    assert any(f.rule_id == "fhir/invalid-json" for f in findings)


def test_pii_in_example_flags_a_realistic_identifier():
    files = {
        "sushi-config.yaml": SUSHI_CONFIG,
        "examples/patient1.json": json.dumps(
            {
                "resourceType": "Patient",
                "id": "patient1",
                "identifier": [{"system": "http://ssn.example.org", "value": "444-22-1234"}],
            }
        ),
    }
    findings = FhirPack().run(_repo(files), AuditPolicy())
    pii = [f for f in findings if f.rule_id == "fhir/pii-in-example"]
    assert len(pii) == 1
    assert pii[0].severity == "error"


def test_pii_in_example_does_not_flag_obviously_synthetic_ids():
    files = {
        "sushi-config.yaml": SUSHI_CONFIG,
        "examples/patient-example.json": json.dumps(
            {
                "resourceType": "Patient",
                "id": "example",
                "identifier": [{"system": "http://ssn.example.org", "value": "123-45-6789"}],
            }
        ),
    }
    findings = FhirPack().run(_repo(files), AuditPolicy())
    assert not any(f.rule_id == "fhir/pii-in-example" for f in findings)


def test_pii_in_example_respects_test_data_markers():
    files = {
        "sushi-config.yaml": SUSHI_CONFIG,
        "examples/patient-test-data.json": json.dumps(
            {
                "resourceType": "Patient",
                "id": "test-data",
                "identifier": [{"value": "444-22-1234"}],
            }
        ),
    }
    findings = FhirPack().run(_repo(files), AuditPolicy())
    assert not any(f.rule_id == "fhir/pii-in-example" for f in findings)


@pytest.mark.parametrize(
    "value,expected",
    [
        ("444-22-1234", True),
        ("123-45-6789", False),  # classic sequential placeholder
        ("999-99-9999", False),  # all-same-digit placeholder
        ("1234567890", False),  # classic sequential placeholder, no dashes
        ("5551234567", True),
        ("abc", False),
        ("12", False),  # too short to be a national ID
    ],
)
def test_is_realistic_identifier(value, expected):
    assert _is_realistic_identifier(value) is expected


def test_fsh_compile_skipped_when_sushi_missing(monkeypatch):
    monkeypatch.setattr("ph_repo_auditor.packs.fhir.shutil.which", lambda _: None)
    files = {"input/fsh/patients.fsh": "Instance: x"}
    findings = FhirPack().run(_repo(files), AuditPolicy())
    skipped = [f for f in findings if f.rule_id == "fhir/fsh-compile-skipped"]
    assert len(skipped) == 1
    assert skipped[0].severity == "info"


def test_fsh_compile_check_silent_when_sushi_present(monkeypatch):
    monkeypatch.setattr("ph_repo_auditor.packs.fhir.shutil.which", lambda _: "/usr/local/bin/sushi")
    files = {"input/fsh/patients.fsh": "Instance: x"}
    findings = FhirPack().run(_repo(files), AuditPolicy())
    assert not any(f.rule_id == "fhir/fsh-compile-skipped" for f in findings)


def test_error_findings_block_passed_even_with_a_perfect_hygiene_score():
    files = {
        "README.md": "Data provenance. Privacy. Ethics.",
        "LICENSE": None,
        "CITATION.cff": None,
        "requirements.txt": None,
        "Makefile": None,
        "tests/test_analysis.py": None,
        "docs/data-dictionary.csv": None,
        "sushi-config.yaml": SUSHI_CONFIG,
        "fsh-generated/resources/StructureDefinition-broken.json": "{not json",
    }
    report = audit_repository("owner/study", files)
    assert report.score == 100  # hygiene is unaffected
    assert report.has_blocking_findings
    assert not report.passed


def test_disabled_packs_policy_turns_the_fhir_pack_off():
    files = {
        "sushi-config.yaml": SUSHI_CONFIG,
        "fsh-generated/resources/StructureDefinition-broken.json": "{not json",
    }
    policy = AuditPolicy(disabled_packs=("fhir",))
    report = audit_repository("owner/study", files, policy)
    assert not any(f.pack == "fhir" for f in report.findings)


def test_ig_with_no_dependency_or_conformance_issues_has_no_findings():
    files = {
        "sushi-config.yaml": SUSHI_CONFIG,
        "fsh-generated/resources/StructureDefinition-Minimal.json": json.dumps(
            {
                "resourceType": "StructureDefinition",
                "url": "http://example.org/fhir/demo/StructureDefinition/Minimal",
                "baseDefinition": "http://hl7.org/fhir/StructureDefinition/Patient",
            }
        ),
        "fsh-generated/resources/ImplementationGuide-demo.json": json.dumps(
            {"resourceType": "ImplementationGuide", "fhirVersion": ["4.0.1"]}
        ),
        "examples/patient-example.json": json.dumps(
            {
                "resourceType": "Patient",
                "id": "example",
                "meta": {"profile": ["http://example.org/fhir/demo/StructureDefinition/Minimal"]},
            }
        ),
    }
    report = audit_repository(
        "owner/study", files, registry=PackRegistry((FhirPack(),))
    )
    # The only findable issue left unpinned in SUSHI_CONFIG is hl7.fhir.uv.ips.
    assert {f.rule_id for f in report.findings} == {"fhir/unpinned-dependency"}
