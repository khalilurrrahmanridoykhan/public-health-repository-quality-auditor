from ph_repo_auditor.auditor import audit_repository
from ph_repo_auditor.models import AuditPolicy
from ph_repo_auditor.packs import MigrationSafetyPack, PackRegistry, RepoView


def _run(files: dict[str, str | None]):
    return MigrationSafetyPack().run(RepoView(files), AuditPolicy())


# -- detection ------------------------------------------------------------


def test_detect_requires_a_migration_framework_marker():
    assert MigrationSafetyPack().detect(RepoView({"README.md": "hi"})) == 0.0
    assert MigrationSafetyPack().detect(RepoView({"alembic.ini": "[alembic]\n"})) == 1.0


def test_detect_recognises_flyway_versioned_sql():
    files = {"db/migration/V1__init.sql": "CREATE TABLE t (id int);\n"}
    assert MigrationSafetyPack().detect(RepoView(files)) == 1.0


def test_detect_recognises_prisma_migration_sql():
    files = {"prisma/migrations/20240101_init/migration.sql": "CREATE TABLE t (id int);\n"}
    assert MigrationSafetyPack().detect(RepoView(files)) == 1.0


def test_detect_recognises_django_migration():
    files = {
        "app/migrations/0001_initial.py": (
            "from django.db import migrations\n\n"
            "class Migration(migrations.Migration):\n    operations = []\n"
        )
    }
    assert MigrationSafetyPack().detect(RepoView(files)) == 1.0


def test_detect_recognises_rails_migration():
    files = {
        "db/migrate/20240101000000_create_things.rb": (
            "class CreateThings < ActiveRecord::Migration[7.0]\n"
            "  def change\n    create_table :things\n  end\nend\n"
        )
    }
    assert MigrationSafetyPack().detect(RepoView(files)) == 1.0


def test_detect_recognises_alembic_revision_behind_a_license_header():
    # Regression: a real Alembic script almost always has a license header
    # or docstring before `revision = `, not on line 1 — the ^ anchor in
    # _ALEMBIC_REVISION_RE must be MULTILINE or it silently never matches
    # (found live against apache/superset's real migrations).
    content = (
        "# Licensed under the Apache License, Version 2.0\n"
        '"""Init\n\nRevision ID: abc123\nRevises: None\n"""\n'
        "revision = 'abc123'\n"
        "down_revision = None\n\n"
        "def upgrade():\n    pass\n\n"
        "def downgrade():\n    pass\n"
    )
    files = {"alembic/versions/abc123_init.py": content}
    assert MigrationSafetyPack().detect(RepoView(files)) == 1.0


# -- raw SQL (Flyway / Prisma) ------------------------------------------
#
# migration/irreversible and migration/non-idempotent were tried for raw
# SQL too, then dropped after self-testing against a real 127-migration
# Flyway repo (Opetushallitus/kouta-backend) showed neither matches real
# practice there — see MigrationSafetyPack's docstring.


def test_flyway_destructive_migration_is_not_flagged_irreversible():
    # Flyway's undo migrations are a Teams/Enterprise-only feature; most
    # Community users have no way to act on "add a U__ script."
    files = {"db/migration/V2__drop_old.sql": "DROP TABLE legacy_patients;\n"}
    findings = _run(files)
    assert not any(f.rule_id == "migration/irreversible" for f in findings)


def test_create_table_without_if_not_exists_is_not_flagged_non_idempotent():
    # IF NOT EXISTS guards aren't a Flyway/Prisma idiom — Flyway's own
    # model is versioned, forward-only migrations, not idempotent re-runs.
    files = {"db/migration/V1__init.sql": "CREATE TABLE t (id int);\n"}
    findings = _run(files)
    assert not any(f.rule_id == "migration/non-idempotent" for f in findings)


def test_schema_and_data_mixed_in_raw_sql_is_flagged():
    files = {
        "db/migration/V3__add_and_seed.sql": (
            "ALTER TABLE t ADD COLUMN status text;\n"
            "UPDATE t SET status = 'active';\n"
        )
    }
    findings = _run(files)
    assert any(f.rule_id == "migration/data-and-schema-mixed" for f in findings)


def test_schema_only_raw_sql_is_not_flagged_as_mixed():
    files = {"db/migration/V1__init.sql": "CREATE TABLE IF NOT EXISTS t (id int);\n"}
    findings = _run(files)
    assert not any(f.rule_id == "migration/data-and-schema-mixed" for f in findings)


def test_dml_inside_a_trigger_function_body_is_not_flagged_as_mixed():
    # A plpgsql history-tracking trigger's own `insert into` (inside a
    # dollar-quoted function body) is DDL defining the trigger, not data
    # manipulation the migration itself executes — the exact real-world
    # pattern found in Opetushallitus/kouta-backend's history tables.
    content = (
        "alter table patients drop column if exists legacy_code;\n\n"
        "create or replace function update_patients_history() returns trigger\n"
        "    language plpgsql\n"
        "as\n"
        "$$\n"
        "begin\n"
        "insert into patients_history (id, name) values (old.id, old.name);\n"
        "return old;\n"
        "end;\n"
        "$$;\n"
    )
    findings = _run({"db/migration/V9__drop_legacy_code.sql": content})
    assert not any(f.rule_id == "migration/data-and-schema-mixed" for f in findings)


# -- Django -----------------------------------------------------------------


def test_django_runpython_with_no_reverse_is_flagged():
    content = (
        "from django.db import migrations\n\n"
        "def forwards(apps, schema_editor):\n    pass\n\n"
        "class Migration(migrations.Migration):\n"
        "    operations = [migrations.RunPython(forwards)]\n"
    )
    findings = _run({"app/migrations/0002_data.py": content})
    hits = [f for f in findings if f.rule_id == "migration/irreversible"]
    assert len(hits) == 1


def test_django_runpython_with_a_reverse_is_not_flagged():
    content = (
        "from django.db import migrations\n\n"
        "def forwards(apps, schema_editor):\n    pass\n\n"
        "def backwards(apps, schema_editor):\n    pass\n\n"
        "class Migration(migrations.Migration):\n"
        "    operations = [migrations.RunPython(forwards, backwards)]\n"
    )
    findings = _run({"app/migrations/0002_data.py": content})
    assert not any(f.rule_id == "migration/irreversible" for f in findings)


def test_django_schema_and_data_op_mixed_is_flagged():
    content = (
        "from django.db import migrations\n\n"
        "class Migration(migrations.Migration):\n"
        "    operations = [\n"
        "        migrations.AddField('model', 'status', models.TextField()),\n"
        "        migrations.RunPython(lambda a, s: None),\n"
        "    ]\n"
    )
    findings = _run({"app/migrations/0003_mixed.py": content})
    assert any(f.rule_id == "migration/data-and-schema-mixed" for f in findings)


# -- Rails ------------------------------------------------------------------


def test_rails_drop_table_inside_change_is_flagged_irreversible():
    content = (
        "class DropLegacy < ActiveRecord::Migration[7.0]\n"
        "  def change\n    drop_table :legacy_patients\n  end\nend\n"
    )
    findings = _run({"db/migrate/20240101000000_drop_legacy.rb": content})
    assert any(f.rule_id == "migration/irreversible" for f in findings)


def test_rails_create_table_inside_change_is_not_flagged_irreversible():
    content = (
        "class CreateThings < ActiveRecord::Migration[7.0]\n"
        "  def change\n    create_table :things do |t|\n    end\n  end\nend\n"
    )
    findings = _run({"db/migrate/20240101000000_create_things.rb": content})
    assert not any(f.rule_id == "migration/irreversible" for f in findings)


def test_rails_schema_and_data_mixed_is_flagged():
    content = (
        "class BackfillStatus < ActiveRecord::Migration[7.0]\n"
        "  def change\n"
        "    add_column :patients, :status, :string\n"
        "    Patient.update_all(status: 'active')\n"
        "  end\nend\n"
    )
    findings = _run({"db/migrate/20240101000000_backfill_status.rb": content})
    assert any(f.rule_id == "migration/data-and-schema-mixed" for f in findings)


# -- Alembic ------------------------------------------------------------


def test_alembic_empty_downgrade_is_flagged():
    content = (
        "revision = 'abc123'\n"
        "down_revision = None\n\n"
        "def upgrade():\n    op.create_table('t')\n\n"
        "def downgrade():\n    pass\n"
    )
    findings = _run({"alembic/versions/abc123_init.py": content})
    assert any(f.rule_id == "migration/irreversible" for f in findings)


def test_alembic_empty_downgrade_behind_a_license_header_is_flagged():
    # Same regression as the detect() test above, but through run() —
    # confirms _alembic_checks actually gets dispatched to on a realistic
    # file, not just that detect() fires.
    content = (
        "# Licensed under the Apache License, Version 2.0\n"
        '"""Init\n\nRevision ID: abc123\n"""\n'
        "revision = 'abc123'\n"
        "down_revision = None\n\n"
        "def upgrade():\n    op.create_table('t')\n\n"
        "def downgrade():\n    pass\n"
    )
    findings = _run({"alembic/versions/abc123_init.py": content})
    assert any(f.rule_id == "migration/irreversible" for f in findings)


def test_alembic_implemented_downgrade_is_not_flagged():
    content = (
        "revision = 'abc123'\n"
        "down_revision = None\n\n"
        "def upgrade():\n    op.create_table('t')\n\n"
        "def downgrade():\n    op.drop_table('t')\n"
    )
    findings = _run({"alembic/versions/abc123_init.py": content})
    assert not any(f.rule_id == "migration/irreversible" for f in findings)


# -- integration ------------------------------------------------------------


def test_disabled_packs_turns_the_migration_safety_pack_off():
    files = {"db/migration/V2__drop_old.sql": "DROP TABLE legacy_patients;\n"}
    policy = AuditPolicy(disabled_packs=("migration-safety",))
    report = audit_repository("owner/repo", files, policy)
    assert not any(f.pack == "migration-safety" for f in report.findings)


def test_migration_safety_pack_registered_in_default_registry():
    repo = RepoView({"alembic.ini": "[alembic]\n"})
    active = PackRegistry().select(repo)
    assert "migration-safety" in {pack.id for pack in active}
