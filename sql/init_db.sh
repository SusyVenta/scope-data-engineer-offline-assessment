#!/usr/bin/env bash
# =============================================================================
# init_db.sh
# Runs once on first PostgreSQL container start (mounted into
# /docker-entrypoint-initdb.d/).  Creates two databases and one test schema:
#
#   airflow          – Airflow's internal metadata store. Owned by `airflow`.
#   corporate        – The pipeline's application database.
#     public         – Production schema (default). Written by the ETL DAG.
#     corporate_test – Integration-test schema. Same tables, isolated from prod.
# =============================================================================
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL

    -- ------------------------------------------------------------------
    -- Airflow metadata database
    -- ------------------------------------------------------------------
    DO \$\$
    BEGIN
        IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'airflow') THEN
            CREATE USER airflow WITH PASSWORD 'airflow';
        END IF;
    END
    \$\$;

    SELECT 'CREATE DATABASE airflow OWNER airflow'
    WHERE  NOT EXISTS (SELECT FROM pg_database WHERE datname = 'airflow')
    \gexec

    GRANT ALL PRIVILEGES ON DATABASE airflow TO airflow;

    -- ------------------------------------------------------------------
    -- Corporate ratings pipeline database
    -- ------------------------------------------------------------------
    DO \$\$
    BEGIN
        IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'corporate') THEN
            CREATE USER corporate WITH PASSWORD 'corporate';
        END IF;
    END
    \$\$;

    SELECT 'CREATE DATABASE corporate OWNER corporate'
    WHERE  NOT EXISTS (SELECT FROM pg_database WHERE datname = 'corporate')
    \gexec

    GRANT ALL PRIVILEGES ON DATABASE corporate TO corporate;

EOSQL

# Create the corporate_test schema inside the corporate database.
# Integration tests run the pipeline against this schema so the production
# public schema is never touched by test runs.
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "corporate" <<-EOSQL
    CREATE SCHEMA IF NOT EXISTS corporate_test AUTHORIZATION corporate;
    GRANT ALL ON SCHEMA corporate_test TO corporate;
EOSQL

echo "[init_db] Databases ready: 'airflow', 'corporate' (schemas: public, corporate_test)."
