import uuid

import psycopg
import pytest

from tender_desk import migrate
from tender_desk.db import DSN


@pytest.fixture
def scratch_dsn():
    try:
        admin = psycopg.connect(DSN, autocommit=True)
    except Exception:
        pytest.skip("local database not running")
    name = "migtest_" + uuid.uuid4().hex[:8]
    admin.execute(f'CREATE DATABASE "{name}"')
    yield DSN.rsplit("/", 1)[0] + "/" + name
    admin.execute(f'DROP DATABASE "{name}" WITH (FORCE)')
    admin.close()


def test_applies_everything_once_and_is_idempotent(scratch_dsn, capsys):
    first = migrate.run(scratch_dsn)
    assert first == ["001_schema.sql", "002_readonly_role.sql", "003_indexes.sql"]
    assert migrate.run(scratch_dsn) == []  # second run does nothing
    with psycopg.connect(scratch_dsn) as c:
        assert c.execute("SELECT count(*) FROM schema_migrations").fetchone()[0] == 3
        assert c.execute("SELECT to_regclass('public.audit_log_tender_id_idx') IS NOT NULL").fetchone()[0]


def test_adopts_a_database_that_predates_the_runner(scratch_dsn, capsys):
    with psycopg.connect(scratch_dsn, autocommit=True) as c:  # as the old docker-entrypoint did: raw files, no record
        c.execute((migrate.MIGRATIONS / "001_schema.sql").read_text())
        c.execute((migrate.MIGRATIONS / "002_readonly_role.sql").read_text())
    assert migrate.run(scratch_dsn) == ["003_indexes.sql"]  # 001 and 002 were adopted, not re-run (re-running 001 would fail)
    assert "adopted an existing database" in capsys.readouterr().out


def test_a_failing_migration_leaves_no_trace(scratch_dsn, tmp_path, monkeypatch):
    migrate.run(scratch_dsn)
    bad = tmp_path / "migrations"
    bad.mkdir()
    for p in migrate.MIGRATIONS.glob("*.sql"):
        (bad / p.name).write_text(p.read_text())
    (bad / "004_bad.sql").write_text("CREATE TABLE half_done (id int); SELECT 1/0;")
    monkeypatch.setattr(migrate, "MIGRATIONS", bad)
    with pytest.raises(psycopg.errors.DivisionByZero):
        migrate.run(scratch_dsn)
    with psycopg.connect(scratch_dsn) as c:
        assert c.execute("SELECT to_regclass('public.half_done') IS NULL").fetchone()[0]  # rolled back
        assert c.execute("SELECT count(*) FROM schema_migrations WHERE version='004_bad.sql'").fetchone()[0] == 0


def test_ro_password_can_be_set_from_the_environment(scratch_dsn, monkeypatch):
    monkeypatch.setenv("TENDER_DESK_RO_PASSWORD", "a-different-dev-password")
    migrate.run(scratch_dsn)
    host = DSN.rsplit("@", 1)[1].rsplit("/", 1)[0]
    name = scratch_dsn.rsplit("/", 1)[1]
    with psycopg.connect(f"postgresql://tender_ro:a-different-dev-password@{host}/{name}") as c:
        assert c.execute("SELECT 1").fetchone()[0] == 1
    # put the shared development role back, other tests rely on it
    with psycopg.connect(DSN, autocommit=True) as c:
        c.execute("ALTER ROLE tender_ro PASSWORD 'tender_ro'")
