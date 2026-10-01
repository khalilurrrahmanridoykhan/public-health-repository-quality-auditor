from ph_repo_auditor.auditor import audit_repository
from ph_repo_auditor.models import AuditPolicy
from ph_repo_auditor.packs import PackRegistry, PortabilityPack, RepoView


def _run(files: dict[str, str | None]):
    return PortabilityPack().run(RepoView(files), AuditPolicy())


# -- detection ------------------------------------------------------------


def test_portability_pack_always_detects():
    assert PortabilityPack().detect(RepoView({"README.md": "hi"})) == 1.0
    assert PortabilityPack().detect(RepoView({})) == 1.0


# -- portability/hardcoded-hostname --------------------------------------


def test_literal_ip_address_is_flagged():
    findings = _run({"app.py": 'HOST = "10.20.30.40"\n'})
    hits = [f for f in findings if f.rule_id == "portability/hardcoded-hostname"]
    assert len(hits) == 1
    assert hits[0].line == 1


def test_loopback_ip_is_not_flagged():
    findings = _run({"app.py": 'HOST = "127.0.0.1"\n'})
    assert not any(f.rule_id == "portability/hardcoded-hostname" for f in findings)


def test_public_api_url_is_not_flagged():
    # The generic case: a reference to a well-known public API/docs host
    # (this is exactly what this project's own source does for
    # api.github.com) is not a portability problem.
    findings = _run({"app.py": 'API_ROOT = "https://api.github.com"\n'})
    assert not any(f.rule_id == "portability/hardcoded-hostname" for f in findings)


def test_db_connection_string_with_literal_host_is_flagged():
    findings = _run({"settings.py": 'DATABASE_URL = "postgres://user:pass@db.internal.example/app"\n'})
    hits = [f for f in findings if f.rule_id == "portability/hardcoded-hostname"]
    assert len(hits) == 1
    assert "db.internal.example" in hits[0].message


def test_db_connection_string_to_localhost_is_not_flagged():
    findings = _run({"settings.py": 'DATABASE_URL = "postgres://user:pass@localhost/app"\n'})
    assert not any(f.rule_id == "portability/hardcoded-hostname" for f in findings)


def test_commented_out_ip_is_ignored():
    findings = _run({"app.py": "# HOST = \"10.20.30.40\"\n"})
    assert not any(f.rule_id == "portability/hardcoded-hostname" for f in findings)


# -- portability/absolute-path -------------------------------------------


def test_home_directory_path_is_flagged():
    findings = _run({"script.py": 'DATA_DIR = "/Users/alex/data"\n'})
    hits = [f for f in findings if f.rule_id == "portability/absolute-path"]
    assert len(hits) == 1


def test_linux_home_path_is_flagged():
    findings = _run({"script.py": 'DATA_DIR = "/home/alex/data"\n'})
    assert any(f.rule_id == "portability/absolute-path" for f in findings)


def test_windows_path_is_flagged():
    findings = _run({"script.py": 'DATA_DIR = "C:\\\\Users\\\\alex\\\\data"\n'})
    assert any(f.rule_id == "portability/absolute-path" for f in findings)


def test_relative_path_is_not_flagged():
    findings = _run({"script.py": 'DATA_DIR = "./data"\n'})
    assert not any(f.rule_id == "portability/absolute-path" for f in findings)


# -- portability/db-specific-sql -----------------------------------------


def test_mysql_only_sql_outside_migrations_is_flagged():
    files = {"scripts/seed.sql": "CREATE TABLE `t` (id INT) ENGINE=InnoDB;\n"}
    findings = _run(files)
    assert any(f.rule_id == "portability/db-specific-sql" for f in findings)


def test_mysql_only_sql_inside_a_migration_is_not_flagged_by_this_pack():
    # OpenmrsPack/MigrationSafetyPack own migration-directory SQL; this
    # cross-cutting pack only looks outside migrations, to avoid double
    # -reporting the same line under two packs.
    files = {"db/migrations/0001_init.sql": "CREATE TABLE `t` (id INT) ENGINE=InnoDB;\n"}
    findings = _run(files)
    assert not any(f.rule_id == "portability/db-specific-sql" for f in findings)


def test_portable_sql_is_not_flagged():
    files = {"scripts/seed.sql": "CREATE TABLE t (id INT);\n"}
    findings = _run(files)
    assert not any(f.rule_id == "portability/db-specific-sql" for f in findings)


# -- integration ------------------------------------------------------------


def test_disabled_packs_turns_the_portability_pack_off():
    policy = AuditPolicy(disabled_packs=("portability",))
    report = audit_repository("owner/repo", {"app.py": 'HOST = "10.20.30.40"\n'}, policy)
    assert not any(f.pack == "portability" for f in report.findings)


def test_portability_pack_registered_in_default_registry():
    repo = RepoView({"README.md": "hi"})
    active = PackRegistry().select(repo)
    assert "portability" in {pack.id for pack in active}
