import json

from ph_repo_auditor.auditor import audit_repository
from ph_repo_auditor.models import AuditPolicy
from ph_repo_auditor.packs import Dhis2Pack, PackRegistry, RepoView

D2_CONFIG_JS = """
const config = {
    type: 'app',
    name: 'demo-app',
    entryPoints: {
        app: './src/App.tsx',
    },
}

module.exports = config
"""


def _repo(files: dict[str, str | None]) -> RepoView:
    return RepoView(files)


def _run(files: dict[str, str | None]):
    return Dhis2Pack().run(_repo(files), AuditPolicy())


# -- detection ----------------------------------------------------------


def test_detect_requires_a_dhis2_marker():
    assert Dhis2Pack().detect(_repo({"README.md": "hello"})) == 0.0
    assert Dhis2Pack().detect(_repo({"d2.config.js": D2_CONFIG_JS})) == 1.0
    assert (
        Dhis2Pack().detect(
            _repo({"package.json": json.dumps({"dependencies": {"@dhis2/app-runtime": "3.0.0"}})})
        )
        == 1.0
    )
    assert (
        Dhis2Pack().detect(
            _repo({"metadata/export.json": json.dumps({"organisationUnits": []})})
        )
        == 1.0
    )


def test_detect_ignores_generic_json_keys_shared_with_unrelated_domains():
    # "programs"/"indicators"/"dataSets" alone are too generic to trust —
    # only the DHIS2-distinctive keys should trigger detection.
    files = {"catalog.json": json.dumps({"programs": [], "indicators": [], "dataSets": []})}
    assert Dhis2Pack().detect(_repo(files)) == 0.0


def test_detect_is_case_insensitive_for_d2_config():
    assert Dhis2Pack().detect(_repo({"D2.Config.js": D2_CONFIG_JS})) == 1.0


# -- d2.config checks -----------------------------------------------------


def test_valid_d2_config_produces_no_findings():
    findings = _run({"d2.config.js": D2_CONFIG_JS})
    assert not any(f.rule_id == "dhis2/invalid-d2-config" for f in findings)


def test_d2_config_missing_type_and_entrypoints_is_flagged():
    findings = _run({"d2.config.js": "module.exports = { name: 'x' }"})
    messages = [f for f in findings if f.rule_id == "dhis2/invalid-d2-config"]
    assert len(messages) == 2  # missing type, missing entryPoints


def test_d2_config_json_variant_is_parsed_structurally():
    findings = _run(
        {"d2.config.json": json.dumps({"type": "app", "entryPoints": {"app": "./src/App.js"}})}
    )
    assert not any(f.rule_id == "dhis2/invalid-d2-config" for f in findings)
    bad = _run({"d2.config.json": json.dumps({"type": "not-a-real-type"})})
    assert len([f for f in bad if f.rule_id == "dhis2/invalid-d2-config"]) == 2


# -- source-level checks ----------------------------------------------------


def test_hardcoded_instance_url_is_flagged_with_line_number():
    content = "export const BASE = 'https://play.dhis2.org/demo/api/programs.json'\n"
    findings = _run({"src/App.tsx": content})
    hits = [f for f in findings if f.rule_id == "dhis2/hardcoded-instance-url"]
    assert len(hits) == 1
    assert hits[0].line == 1
    assert hits[0].file == "src/App.tsx"


def test_raw_fetch_to_api_is_flagged():
    content = "fetch('/api/dataElements.json').then(r => r.json())\n"
    findings = _run({"src/App.tsx": content})
    assert any(f.rule_id == "dhis2/raw-fetch-to-api" for f in findings)


def test_fetch_through_a_helper_function_is_not_flagged():
    # The recommended DHIS2 Routes pattern: no literal '/api/' string at the
    # fetch() call site.
    content = "fetch(routeRunUrl(routeId, subPath, params), { method: 'GET' })\n"
    findings = _run({"src/App.tsx": content})
    assert not any(f.rule_id == "dhis2/raw-fetch-to-api" for f in findings)


def test_bare_domain_mentions_in_comments_are_not_flagged():
    # Real-world false-positive risk: prose in comments mentioning an
    # instance hostname with no scheme/quotes shouldn't trip the regex.
    content = "// confirmed against play.dhis2.org (stable-2-43-1)\nconst x = 1\n"
    findings = _run({"src/App.tsx": content})
    assert not any(f.rule_id == "dhis2/hardcoded-instance-url" for f in findings)


# -- metadata bundle checks --------------------------------------------------


def test_duplicate_uid_across_collections():
    bundle = {
        "dataElements": [{"id": "abcdefghijk", "name": "A"}],
        "indicators": [{"id": "abcdefghijk", "name": "B"}],
    }
    findings = _run({"metadata.json": json.dumps(bundle)})
    dup = [f for f in findings if f.rule_id == "dhis2/metadata-duplicate-uid"]
    assert len(dup) == 1
    assert "abcdefghijk" in dup[0].message


def test_no_duplicate_uid_when_all_unique():
    bundle = {
        "dataElements": [{"id": "abcdefghijk", "name": "A"}],
        "indicators": [{"id": "zyxwvutsrqp", "name": "B"}],
    }
    findings = _run({"metadata.json": json.dumps(bundle)})
    assert not any(f.rule_id == "dhis2/metadata-duplicate-uid" for f in findings)


def test_dangling_reference_when_collection_present_but_id_missing():
    bundle = {
        "dataElements": [
            {"id": "dataelem000", "categoryCombo": {"id": "missingcomb"}}
        ],
        "categoryCombos": [{"id": "presentcomb"}],
    }
    findings = _run({"metadata.json": json.dumps(bundle)})
    dangling = [f for f in findings if f.rule_id == "dhis2/metadata-dangling-ref"]
    assert len(dangling) == 1
    assert "missingcomb" in dangling[0].message


def test_no_dangling_reference_when_owning_collection_absent():
    # The bundle doesn't claim to be self-contained for categoryCombos, so a
    # reference to one that isn't included is assumed to exist on-instance.
    bundle = {"dataElements": [{"id": "dataelem000", "categoryCombo": {"id": "external001"}}]}
    findings = _run({"metadata.json": json.dumps(bundle)})
    assert not any(f.rule_id == "dhis2/metadata-dangling-ref" for f in findings)


def test_no_dangling_reference_when_id_is_present():
    bundle = {
        "dataElements": [{"id": "dataelem000", "categoryCombo": {"id": "presentcomb"}}],
        "categoryCombos": [{"id": "presentcomb"}],
    }
    findings = _run({"metadata.json": json.dumps(bundle)})
    assert not any(f.rule_id == "dhis2/metadata-dangling-ref" for f in findings)


def test_dangling_reference_found_at_arbitrary_nesting_depth():
    bundle = {
        "programs": [
            {
                "id": "prog0000000",
                "programStages": [
                    {
                        "id": "stage000000",
                        "programStageDataElements": [
                            {"dataElement": {"id": "missingelem"}}
                        ],
                    }
                ],
            }
        ],
        "dataElements": [{"id": "someelem000"}],
    }
    findings = _run({"metadata.json": json.dumps(bundle)})
    dangling = [f for f in findings if f.rule_id == "dhis2/metadata-dangling-ref"]
    assert len(dangling) == 1
    assert "missingelem" in dangling[0].message


def test_sqlview_mutating_statement_is_flagged():
    bundle = {
        "sqlViews": [
            {"id": "sv00000001a", "name": "bad view", "sqlQuery": "DELETE FROM dataelement"}
        ]
    }
    findings = _run({"metadata.json": json.dumps(bundle)})
    hits = [f for f in findings if f.rule_id == "dhis2/sqlview-mutating-statement"]
    assert len(hits) == 1
    assert hits[0].severity == "error"


def test_sqlview_select_only_is_not_flagged():
    bundle = {
        "sqlViews": [
            {"id": "sv00000001a", "name": "ok view", "sqlQuery": "SELECT * FROM dataelement"}
        ]
    }
    findings = _run({"metadata.json": json.dumps(bundle)})
    assert not any(f.rule_id == "dhis2/sqlview-mutating-statement" for f in findings)


def test_program_rule_undefined_variable_is_flagged():
    bundle = {
        "programRuleVariables": [{"name": "age"}],
        "programRules": [
            {
                "id": "rule0000001",
                "name": "check age",
                "condition": "#{age} > 5 && #{weight} < 10",
            }
        ],
    }
    findings = _run({"metadata.json": json.dumps(bundle)})
    undefined = [f for f in findings if f.rule_id == "dhis2/program-rule-undefined-var"]
    assert len(undefined) == 1
    assert "weight" in undefined[0].message


def test_program_rule_variable_defined_is_not_flagged():
    bundle = {
        "programRuleVariables": [{"name": "age"}],
        "programRules": [{"id": "rule0000001", "condition": "#{age} > 5"}],
    }
    findings = _run({"metadata.json": json.dumps(bundle)})
    assert not any(f.rule_id == "dhis2/program-rule-undefined-var" for f in findings)


def test_program_rule_skips_variable_check_when_collection_absent():
    bundle = {"programRules": [{"id": "rule0000001", "condition": "#{whatever}"}]}
    findings = _run({"metadata.json": json.dumps(bundle)})
    assert not any(f.rule_id == "dhis2/program-rule-undefined-var" for f in findings)


def test_program_rule_unknown_builtin_variable_is_flagged():
    bundle = {
        "programRules": [
            {"id": "rule0000001", "condition": "V{event_date} > '2020-01-01'"}
        ]
    }
    clean = _run({"metadata.json": json.dumps(bundle)})
    assert not any(f.rule_id == "dhis2/program-rule-undefined-var" for f in clean)

    bundle["programRules"][0]["condition"] = "V{made_up_variable} > 0"
    findings = _run({"metadata.json": json.dumps(bundle)})
    hits = [f for f in findings if f.rule_id == "dhis2/program-rule-undefined-var"]
    assert len(hits) == 1
    assert "made_up_variable" in hits[0].message


def test_program_rule_action_data_is_also_checked():
    bundle = {
        "programRuleVariables": [{"name": "age"}],
        "programRules": [
            {
                "id": "rule0000001",
                "programRuleActions": [{"data": "#{undefined_var}"}],
            }
        ],
    }
    findings = _run({"metadata.json": json.dumps(bundle)})
    assert any(
        f.rule_id == "dhis2/program-rule-undefined-var" and "undefined_var" in f.message
        for f in findings
    )


def test_non_dhis2_json_is_not_treated_as_a_metadata_bundle():
    findings = _run(
        {
            "d2.config.js": D2_CONFIG_JS,
            "package.json": json.dumps({"name": "demo", "dependencies": {}}),
        }
    )
    assert findings == []


# -- integration --------------------------------------------------------


def test_disabled_packs_turns_the_dhis2_pack_off():
    files = {"d2.config.js": "module.exports = { name: 'x' }"}
    policy = AuditPolicy(disabled_packs=("dhis2",))
    report = audit_repository("owner/app", files, policy)
    assert not any(f.pack == "dhis2" for f in report.findings)


def test_dhis2_pack_registered_in_default_registry():
    repo = RepoView({"d2.config.js": D2_CONFIG_JS})
    active = PackRegistry().select(repo)
    assert "dhis2" in {pack.id for pack in active}
