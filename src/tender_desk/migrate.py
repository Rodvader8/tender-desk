"""Apply the SQL files in migrations/ in order, once each.

  uv run tender-migrate

Applied versions are recorded in schema_migrations. A lock stops two runners colliding. A database created before
this runner existed (it already has price_items but no record) is adopted: 001 and 002 are marked applied, not re-run.
Set TENDER_DESK_RO_PASSWORD to give the read-only role a password other than the development default.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import psycopg
from psycopg import sql

from .db import DSN

MIGRATIONS = Path(__file__).parent / "migrations"
LOCK_ID = 727_274  # arbitrary constant: "tender" on a phone keypad, near enough


def pending(conn: psycopg.Connection) -> list[Path]:
    done = {r[0] for r in conn.execute("SELECT version FROM schema_migrations").fetchall()}
    return [p for p in sorted(MIGRATIONS.glob("*.sql")) if p.name not in done]


def run(dsn: str | None = None, out=None) -> list[str]:
    out = out or sys.stdout  # looked up at call time so redirected output is respected
    applied: list[str] = []
    with psycopg.connect(dsn or DSN, autocommit=True) as conn:
        conn.execute("SELECT pg_advisory_lock(%s)", (LOCK_ID,))
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations (version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
            )
            legacy = conn.execute("SELECT to_regclass('public.price_items') IS NOT NULL").fetchone()[0]  # type: ignore[index]
            if legacy and not conn.execute("SELECT 1 FROM schema_migrations LIMIT 1").fetchone():
                for name in ("001_schema.sql", "002_readonly_role.sql"):
                    conn.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (name,))
                print("adopted an existing database: marked 001 and 002 as applied", file=out)
            for path in pending(conn):
                with conn.transaction():
                    conn.execute(path.read_text())
                    conn.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (path.name,))
                applied.append(path.name)
                print(f"applied {path.name}", file=out)
            password = os.environ.get("TENDER_DESK_RO_PASSWORD")
            if password:
                conn.execute(sql.SQL("ALTER ROLE tender_ro PASSWORD {}").format(sql.Literal(password)))
                print("set the read-only role's password from TENDER_DESK_RO_PASSWORD", file=out)
            if not applied:
                print("database is up to date", file=out)
        finally:
            conn.execute("SELECT pg_advisory_unlock(%s)", (LOCK_ID,))
    return applied


def main() -> None:
    run()


if __name__ == "__main__":
    main()
