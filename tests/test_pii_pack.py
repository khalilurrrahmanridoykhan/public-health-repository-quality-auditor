from ph_repo_auditor.auditor import audit_repository
from ph_repo_auditor.models import AuditPolicy
from ph_repo_auditor.packs import PackRegistry, PiiPack, RepoView

PATIENT_CSV = (
    "name,date_of_birth,diagnosis,address,phone\n"
    "Jane Doe,1990-01-02,Hypertension,123 Main St,+8801700000000\n"
)
AGGREGATE_CSV = "name,count\nMalaria,42\nDengue,7\n"


def _run(files: dict[str, str | None]):
    return PiiPack().run(RepoView(files), AuditPolicy())


# -- detection ------------------------------------------------------------


def test_pii_pack_always_detects():
    assert PiiPack().detect(RepoView({"README.md": "hi"})) == 1.0
    assert PiiPack().detect(RepoView({})) == 1.0


# -- pii/patient-data-in-repo -----------------------------------------------


def test_patient_shaped_csv_is_flagged():
    findings = _run({"data/patients.csv": PATIENT_CSV})
    hits = [f for f in findings if f.rule_id == "pii/patient-data-in-repo"]
    assert len(hits) == 1
    assert hits[0].severity == "error"
    assert hits[0].file == "data/patients.csv"


def test_aggregate_csv_is_not_flagged():
    findings = _run({"data/case_counts.csv": AGGREGATE_CSV})
    assert not any(f.rule_id == "pii/patient-data-in-repo" for f in findings)


def test_single_identity_column_alone_is_not_flagged():
    # One cluster hit (a "name" column on, say, an org-unit lookup table)
    # isn't suspicious by itself — needs several clusters together.
    findings = _run({"data/org_units.csv": "name,code\nSylhet,SYL\n"})
    assert not any(f.rule_id == "pii/patient-data-in-repo" for f in findings)


def test_patient_shaped_csv_under_a_fixtures_path_is_not_flagged():
    findings = _run({"tests/fixtures/patients.csv": PATIENT_CSV})
    assert not any(f.rule_id == "pii/patient-data-in-repo" for f in findings)


# -- secrets/committed-env-values --------------------------------------------


def test_env_file_with_a_real_value_is_flagged():
    findings = _run({".env": "DATABASE_URL=postgres://user:pass@db.example.com/app\n"})
    hits = [f for f in findings if f.rule_id == "secrets/committed-env-values"]
    assert len(hits) == 1
    assert hits[0].line == 1


def test_env_example_is_not_flagged():
    findings = _run({".env.example": "DATABASE_URL=postgres://user:pass@host/app\n"})
    assert not any(f.rule_id == "secrets/committed-env-values" for f in findings)


def test_env_file_with_placeholder_values_is_not_flagged():
    files = {".env": "API_KEY=\nSECRET=changeme\nTOKEN=<your-token-here>\n"}
    findings = _run(files)
    assert not any(f.rule_id == "secrets/committed-env-values" for f in findings)


def test_env_file_comments_are_ignored():
    findings = _run({".env": "# DATABASE_URL=postgres://user:pass@host/app\n"})
    assert not any(f.rule_id == "secrets/committed-env-values" for f in findings)


# -- pii/db-dump-committed ---------------------------------------------------


def test_dump_file_is_flagged():
    findings = _run({"backup/prod.dump": "binary-ish content"})
    assert any(f.rule_id == "pii/db-dump-committed" for f in findings)


def test_bak_file_is_flagged():
    findings = _run({"db/app.bak": "binary-ish content"})
    assert any(f.rule_id == "pii/db-dump-committed" for f in findings)


def test_large_sql_file_outside_migrations_is_flagged():
    findings = _run({"export/dump.sql": "INSERT INTO patients VALUES (1);\n" * 2000})
    assert any(f.rule_id == "pii/db-dump-committed" for f in findings)


def test_small_sql_file_outside_migrations_is_not_flagged():
    findings = _run({"scripts/seed.sql": "INSERT INTO lookup VALUES (1, 'x');\n"})
    assert not any(f.rule_id == "pii/db-dump-committed" for f in findings)


def test_large_sql_file_inside_migrations_is_not_flagged_as_a_dump():
    content = "CREATE TABLE t (id int);\n" * 2000
    findings = _run({"db/migrations/0001_init.sql": content})
    assert not any(f.rule_id == "pii/db-dump-committed" for f in findings)


# -- integration ------------------------------------------------------------


def test_disabled_packs_turns_the_pii_pack_off():
    policy = AuditPolicy(disabled_packs=("pii",))
    report = audit_repository("owner/repo", {"data/patients.csv": PATIENT_CSV}, policy)
    assert not any(f.pack == "pii" for f in report.findings)


def test_pii_pack_registered_in_default_registry():
    repo = RepoView({"README.md": "hi"})
    active = PackRegistry().select(repo)
    assert "pii" in {pack.id for pack in active}
