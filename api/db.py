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
    """Yield a psycopg2 connection with RealDictCursor from the pool."""
    pool = _get_pool()
    conn = pool.getconn()
    try:
        yield conn
    finally:
        pool.putconn(conn)
