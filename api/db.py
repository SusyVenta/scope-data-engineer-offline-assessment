"""
db.py
-----
Database connection management for the FastAPI service.
Uses a simple psycopg2 connection pool via psycopg2.pool.SimpleConnectionPool.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Generator

import psycopg2
import psycopg2.extras
import psycopg2.pool

_pool: psycopg2.pool.SimpleConnectionPool | None = None


def _get_pool() -> psycopg2.pool.SimpleConnectionPool:
    global _pool
    if _pool is None:
        schema = os.getenv("POSTGRES_SCHEMA", "public")
        options = f"-csearch_path={schema},public" if schema != "public" else None
        pool_kwargs: dict = dict(
            minconn=1,
            maxconn=10,
            host=os.getenv("POSTGRES_HOST", "postgres"),
            port=int(os.getenv("POSTGRES_PORT", "5432")),
            dbname=os.getenv("POSTGRES_DB", "corporate"),
            user=os.getenv("POSTGRES_USER", "corporate"),
            password=os.getenv("POSTGRES_PASSWORD", "corporate"),
        )
        if options:
            pool_kwargs["options"] = options
        _pool = psycopg2.pool.SimpleConnectionPool(**pool_kwargs)
    return _pool


@contextmanager
def get_db() -> Generator[psycopg2.extensions.connection, None, None]:
    """Yield a psycopg2 connection from the pool.

    Before use, pings with SELECT 1 to detect stale connections (e.g. ones
    left idle-in-transaction from a previous session, or killed by PostgreSQL
    after a TRUNCATE lock wait).  A failed ping discards the whole pool so
    the next _get_pool() call creates fresh connections.  After every request,
    rollback() returns the connection to "idle" state so it doesn't hold locks
    that would block DDL on subsequent test runs.
    """
    global _pool
    pool = _get_pool()
    conn = pool.getconn()
    try:
        # Health-check: replace broken/stale connections before the caller hits them.
        try:
            conn.cursor().execute("SELECT 1")
            conn.rollback()
        except Exception:
            _pool = None
            try:
                pool.putconn(conn, close=True)
            except Exception:
                try:
                    conn.close()
                except Exception:
                    pass
            pool = _get_pool()
            conn = pool.getconn()
        yield conn
    finally:
        try:
            conn.rollback()
            pool.putconn(conn)
        except Exception:
            _pool = None
            try:
                conn.close()
            except Exception:
                pass
