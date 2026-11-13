import os

import psycopg
from pgvector.psycopg import register_vector

DSN = os.environ.get("TENDER_DESK_DB", "postgresql://tender:tender@127.0.0.1:54329/tender")


def connect(dsn: str | None = None) -> psycopg.Connection:
    conn = psycopg.connect(dsn or DSN, autocommit=True)
    register_vector(conn)
    return conn
