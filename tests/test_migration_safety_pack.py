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


# -- raw SQL (Flyway / Prisma) ------------------------------------------


def test_flyway_destructive_migration_with_no_undo_is_flagged():
    files = {"db/migration/V2__drop_old.sql": "DROP TABLE legacy_patients;\n"}
    findings = _run(files)
    assert any(f.rule_id == "migration/irreversible" for f in findings)


def test_flyway_destructive_migration_with_a_matching_undo_is_not_flagged():
    files = {
        "db/migration/V2__drop_old.sql": "DROP TABLE legacy_patients;\n",
        "db/migration/U2__drop_old.sql": "CREATE TABLE legacy_patients (id int);\n",
    }
    findings = _run(files)
    assert not any(f.rule_id == "migration/irreversible" for f in findings)


def test_create_table_without_if_not_exists_is_flagged_non_idempotent():
    files = {"db/migration/V1__init.sql": "CREATE TABLE t (id int);\n"}
    findings = _run(files)
    assert any(f.rule_id == "migration/non-idempotent" for f in findings)


def test_create_table_with_if_not_exists_is_not_flagged():
    files = {"db/migration/V1__init.sql": "CREATE TABLE IF NOT EXISTS t (id int);\n"}
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
