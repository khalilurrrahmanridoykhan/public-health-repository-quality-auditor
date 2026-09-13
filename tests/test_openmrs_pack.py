import json

from ph_repo_auditor.auditor import audit_repository
from ph_repo_auditor.models import AuditPolicy
from ph_repo_auditor.packs import OpenmrsPack, PackRegistry, RepoView

OPENMRS_CONFIG_XML = """<?xml version="1.0" encoding="UTF-8"?>
<module configVersion="1.0">
    <id>@MODULE_ID@</id>
    <name>@MODULE_NAME@</name>
    <package>@MODULE_PACKAGE@</package>
</module>
"""

GENERIC_CONFIG_XML = """<?xml version="1.0" encoding="UTF-8"?>
<module>
    <name>not-openmrs</name>
</module>
"""


def _run(files: dict[str, str | None]):
    return OpenmrsPack().run(RepoView(files), AuditPolicy())


def _changelog(changesets_xml: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<databaseChangeLog xmlns="http://www.liquibase.org/xml/ns/dbchangelog">\n'
        f"{changesets_xml}\n"
        "</databaseChangeLog>\n"
    )


# -- detection ------------------------------------------------------------


def test_detect_requires_an_openmrs_marker():
    assert OpenmrsPack().detect(RepoView({"README.md": "hi"})) == 0.0
    assert OpenmrsPack().detect(RepoView({"omod/src/main/resources/config.xml": OPENMRS_CONFIG_XML})) == 1.0
    assert OpenmrsPack().detect(RepoView({"pom.xml": "<project><packaging>omod</packaging></project>"})) == 1.0
    assert (
        OpenmrsPack().detect(
            RepoView({"src/routes.json": json.dumps({"$schema": "https://json.openmrs.org/routes.schema.json"})})
        )
        == 1.0
    )


def test_detect_requires_config_xml_to_actually_look_like_openmrss():
    # config.xml is too generic a filename to trust on its own.
    assert OpenmrsPack().detect(RepoView({"config.xml": GENERIC_CONFIG_XML})) == 0.0


def test_detect_recognises_peer_dependency_only_modules():
    # The *correct* O3 convention is peerDependencies, not dependencies —
    # a module that gets this right must still be detected.
    files = {
        "package.json": json.dumps(
            {
                "peerDependencies": {"@openmrs/esm-framework": "6.0.0"},
                "devDependencies": {"@openmrs/esm-framework": "6.0.0"},
            }
        )
    }
    assert OpenmrsPack().detect(RepoView(files)) == 1.0


# -- Liquibase checks -------------------------------------------------------


def test_missing_id_or_author_is_flagged():
    changelog = _changelog('<changeSet author="me"><sql>SELECT 1</sql></changeSet>')
    findings = _run({"config.xml": OPENMRS_CONFIG_XML, "api/liquibase.xml": changelog})
    assert any(f.rule_id == "openmrs/liquibase-missing-id" for f in findings)


def test_duplicate_id_and_author_is_flagged():
    changelog = _changelog(
        '<changeSet id="dupe-1" author="me"><addColumn tableName="t">'
        '<column name="c" type="varchar(1)"/></addColumn>'
        '<preConditions onFail="MARK_RAN"><not><columnExists tableName="t" columnName="c"/></not></preConditions>'
        "</changeSet>"
        '<changeSet id="dupe-1" author="me"><addColumn tableName="t2">'
        '<column name="c" type="varchar(1)"/></addColumn>'
        '<preConditions onFail="MARK_RAN"><not><columnExists tableName="t2" columnName="c"/></not></preConditions>'
        "</changeSet>"
    )
    findings = _run({"config.xml": OPENMRS_CONFIG_XML, "api/liquibase.xml": changelog})
    dupes = [f for f in findings if f.rule_id == "openmrs/liquibase-duplicate-id"]
    assert len(dupes) == 1
    assert "dupe-1" in dupes[0].message


def test_raw_sql_with_no_rollback_is_flagged():
    changelog = _changelog('<changeSet id="a" author="me"><sql>UPDATE t SET x = 1</sql></changeSet>')
    findings = _run({"config.xml": OPENMRS_CONFIG_XML, "api/liquibase.xml": changelog})
    assert any(f.rule_id == "openmrs/liquibase-sql-no-rollback" for f in findings)


def test_raw_sql_with_a_rollback_is_not_flagged():
    changelog = _changelog(
        '<changeSet id="a" author="me"><sql>UPDATE t SET x = 1</sql>'
        "<rollback><sql>UPDATE t SET x = 0</sql></rollback></changeSet>"
    )
    findings = _run({"config.xml": OPENMRS_CONFIG_XML, "api/liquibase.xml": changelog})
    assert not any(f.rule_id == "openmrs/liquibase-sql-no-rollback" for f in findings)


def test_create_table_without_auto_rollback_needs_no_explicit_rollback():
    # createTable/addColumn are Liquibase auto-rollback-capable; only
    # sql/sqlFile/customChange genuinely need an explicit <rollback>.
    changelog = _changelog(
        '<changeSet id="a" author="me">'
        '<preConditions onFail="MARK_RAN"><not><tableExists tableName="t"/></not></preConditions>'
        '<createTable tableName="t"><column name="id" type="int"/></createTable>'
        "</changeSet>"
    )
    findings = _run({"config.xml": OPENMRS_CONFIG_XML, "api/liquibase.xml": changelog})
    assert not any(f.rule_id == "openmrs/liquibase-sql-no-rollback" for f in findings)


def test_create_table_without_preconditions_is_flagged_non_idempotent():
    changelog = _changelog(
        '<changeSet id="a" author="me"><createTable tableName="t">'
        '<column name="id" type="int"/></createTable></changeSet>'
    )
    findings = _run({"config.xml": OPENMRS_CONFIG_XML, "api/liquibase.xml": changelog})
    assert any(f.rule_id == "openmrs/liquibase-non-idempotent" for f in findings)


def test_create_table_with_preconditions_is_not_flagged():
    changelog = _changelog(
        '<changeSet id="a" author="me">'
        '<preConditions onFail="MARK_RAN"><not><tableExists tableName="t"/></not></preConditions>'
        '<createTable tableName="t"><column name="id" type="int"/></createTable>'
        "</changeSet>"
    )
    findings = _run({"config.xml": OPENMRS_CONFIG_XML, "api/liquibase.xml": changelog})
    assert not any(f.rule_id == "openmrs/liquibase-non-idempotent" for f in findings)


def test_backtick_and_mysql_keywords_in_raw_sql_are_flagged():
    changelog = _changelog(
        '<changeSet id="a" author="me"><sql>CREATE TABLE `t` (id INT) ENGINE=InnoDB</sql>'
        "<rollback><sql>DROP TABLE t</sql></rollback></changeSet>"
    )
    findings = _run({"config.xml": OPENMRS_CONFIG_XML, "api/liquibase.xml": changelog})
    assert any(f.rule_id == "openmrs/liquibase-db-specific-sql" for f in findings)


def test_portable_raw_sql_is_not_flagged():
    changelog = _changelog(
        '<changeSet id="a" author="me"><sql>UPDATE t SET x = 1</sql>'
        "<rollback><sql>UPDATE t SET x = 0</sql></rollback></changeSet>"
    )
    findings = _run({"config.xml": OPENMRS_CONFIG_XML, "api/liquibase.xml": changelog})
    assert not any(f.rule_id == "openmrs/liquibase-db-specific-sql" for f in findings)


def test_non_liquibase_xml_is_ignored():
    findings = _run(
        {
            "config.xml": OPENMRS_CONFIG_XML,
            "web.xml": '<?xml version="1.0"?><web-app></web-app>',
        }
    )
    assert findings == []


# -- concept UUID checks ----------------------------------------------------


def test_hardcoded_concept_uuid_is_flagged():
    java = (
        "class X {\n"
        "  void m() {\n"
        '    Context.getConceptService().getConceptByUuid("aa2842cc-e370-4a01-8c1f-0568d3e0a0d1");\n'
        "  }\n"
        "}\n"
    )
    findings = _run({"config.xml": OPENMRS_CONFIG_XML, "api/src/main/java/X.java": java})
    hits = [f for f in findings if f.rule_id == "openmrs/hardcoded-concept-uuid"]
    assert len(hits) == 1
    assert hits[0].line == 3


def test_concept_lookup_by_mapping_is_not_flagged():
    java = (
        "class X {\n"
        "  void m() {\n"
        '    Context.getConceptService().getConceptByMapping("1234", "CIEL");\n'
        "  }\n"
        "}\n"
    )
    findings = _run({"config.xml": OPENMRS_CONFIG_XML, "api/src/main/java/X.java": java})
    assert not any(f.rule_id == "openmrs/hardcoded-concept-uuid" for f in findings)


def test_concept_lookup_by_variable_is_not_flagged():
    java = (
        "class X {\n"
        "  void m(String conceptUuid) {\n"
        "    Context.getConceptService().getConceptByUuid(conceptUuid);\n"
        "  }\n"
        "}\n"
    )
    findings = _run({"config.xml": OPENMRS_CONFIG_XML, "api/src/main/java/X.java": java})
    assert not any(f.rule_id == "openmrs/hardcoded-concept-uuid" for f in findings)


# -- O3 checks ------------------------------------------------------------


def test_esm_framework_as_a_regular_dependency_is_flagged():
    files = {
        "package.json": json.dumps({"dependencies": {"@openmrs/esm-framework": "6.0.0"}}),
    }
    findings = _run(files)
    assert any(f.rule_id == "openmrs/o3-missing-framework-peer" for f in findings)


def test_esm_framework_as_a_peer_dependency_is_not_flagged():
    files = {
        "package.json": json.dumps(
            {
                "peerDependencies": {"@openmrs/esm-framework": "6.0.0"},
                "devDependencies": {"@openmrs/esm-framework": "6.0.0"},
            }
        ),
    }
    findings = _run(files)
    assert not any(f.rule_id == "openmrs/o3-missing-framework-peer" for f in findings)


def test_invalid_routes_json_is_flagged():
    files = {"package.json": json.dumps({"peerDependencies": {"@openmrs/esm-framework": "6.0.0"}})}
    files["src/routes.json"] = "{not json"
    findings = _run(files)
    assert any(f.rule_id == "openmrs/o3-invalid-routes-json" for f in findings)


def test_route_component_with_no_export_is_flagged():
    routes = json.dumps(
        {
            "$schema": "https://json.openmrs.org/routes.schema.json",
            "modals": [{"name": "edit-thing-modal", "component": "editThingModal"}],
        }
    )
    index_ts = "export const otherThingModal = getAsyncLifecycle(() => import('./x'), {});\n"
    findings = _run({"src/routes.json": routes, "src/index.ts": index_ts})
    hits = [f for f in findings if f.rule_id == "openmrs/o3-route-missing-export"]
    assert len(hits) == 1
    assert "editThingModal" in hits[0].message


def test_route_component_with_a_matching_export_is_not_flagged():
    routes = json.dumps(
        {
            "$schema": "https://json.openmrs.org/routes.schema.json",
            "pages": [{"component": "root", "route": "thing"}],
        }
    )
    index_ts = "export const root = getAsyncLifecycle(() => import('./root'), {});\n"
    findings = _run({"src/routes.json": routes, "src/index.ts": index_ts})
    assert not any(f.rule_id == "openmrs/o3-route-missing-export" for f in findings)


def test_route_check_is_skipped_without_a_sibling_entry_file():
    routes = json.dumps(
        {
            "$schema": "https://json.openmrs.org/routes.schema.json",
            "pages": [{"component": "root", "route": "thing"}],
        }
    )
    findings = _run({"src/routes.json": routes})
    assert not any(f.rule_id == "openmrs/o3-route-missing-export" for f in findings)


# -- integration ------------------------------------------------------------


def test_disabled_packs_turns_the_openmrs_pack_off():
    files = {"config.xml": OPENMRS_CONFIG_XML, "api/liquibase.xml": _changelog('<changeSet author="me"><sql>x</sql></changeSet>')}
    policy = AuditPolicy(disabled_packs=("openmrs",))
    report = audit_repository("owner/module", files, policy)
    assert not any(f.pack == "openmrs" for f in report.findings)


def test_openmrs_pack_registered_in_default_registry():
    repo = RepoView({"config.xml": OPENMRS_CONFIG_XML})
    active = PackRegistry().select(repo)
    assert "openmrs" in {pack.id for pack in active}
