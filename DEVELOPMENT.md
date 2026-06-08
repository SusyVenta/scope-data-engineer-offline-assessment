# DEVELOPMENT.md — Corporate Credit Rating Data Pipeline

This file tracks all milestones and tasks for the corporate ratings pipeline project.
Status markers: `[ ]` pending · `[~]` in progress · `[x]` complete

---

## Architecture Overview

### What changes vs. the existing repo

| Component | Old (retail CSV) | New (corporate Excel) |
|---|---|---|
| Input | `retails.csv` | 4 `.xlsm` files in `data/input_files/` |
| Processing engine | Apache Spark (PySpark) | Pure Python (pandas + openpyxl) |
| Orchestration | Airflow DAG (5 tasks) | Airflow DAG (4 tasks: extract/validate/transform/load) |
| Database | `retail` DB, retail schema | `corporate` DB, dimensional schema |
| API | None | FastAPI on port 8000 |
| Docker services | postgres, spark-master, spark-worker, airflow | postgres, airflow, api |

### New pipeline DAG

```
extract_sheets ──► validate_data ──► transform_data ──► load_to_warehouse
```

### New dimensional model (star schema)

```
                     ┌─────────────────┐
                     │  dim_company    │ (SCD Type 2)
                     └────────┬────────┘
                              │
┌──────────────┐    ┌─────────▼────────┐    ┌──────────────────┐
│  dim_sector  │◄───│ fact_rating_     │───►│  upload_log      │
└──────────────┘    │    snapshot      │    └──────────────────┘
                    └─────────┬────────┘
┌──────────────┐              │
│  dim_country │◄─────────────┤
└──────────────┘              │
┌──────────────┐              │
│ dim_currency │◄─────────────┘
└──────────────┘

pipeline_run_state  (tracks last DAG run, for incremental loading)
```

### Incremental loading logic

1. On each DAG run, record `run_started_at` in `pipeline_run_state`
2. For each file in `data/input_files/`: compare `os.path.getmtime()` to the last successful run's `completed_at`
3. Files modified after last run → staged for processing
4. For each staged file: compute SHA-256 hash of extracted data
5. If hash already exists in `upload_log` → **skip with WARNING, exit successfully**
6. Otherwise → extract → validate → transform → load with `loaded_at_utc = now()`

---

## File Structure (after changes)

```
.
├── airflow/
│   └── Dockerfile                    # Remove Java/PySpark; add pandas, openpyxl, psycopg2
├── api/
│   ├── Dockerfile                    # NEW: FastAPI container
│   ├── __init__.py
│   ├── db.py                         # NEW: DB connection / session
│   ├── main.py                       # NEW: FastAPI app entry point
│   ├── models.py                     # NEW: Pydantic request/response models
│   └── routers/
│       ├── __init__.py
│       ├── companies.py              # NEW: /companies endpoints
│       ├── snapshots.py              # NEW: /snapshots endpoints
│       └── uploads.py                # NEW: /uploads endpoints
├── corporate_pipeline/
│   ├── __init__.py                   # NEW
│   ├── extractor.py                  # NEW: Excel MASTER sheet extraction
│   ├── validator.py                  # NEW: data quality checks
│   ├── transformer.py                # NEW: key-value → structured records
│   └── loader.py                     # NEW: incremental load, dedup, PG write
├── dags/
│   └── corporate_ratings_dag.py      # NEW (replaces retail_pipeline_dag.py)
├── data/
│   ├── extracted_sheets/             # NEW: intermediate CSVs per file
│   │   └── .gitkeep
│   └── input_files/                  # Existing .xlsm files (unchanged)
├── sql/
│   ├── ddl/
│   │   ├── dim_company.sql           # NEW
│   │   ├── dim_sector.sql            # NEW
│   │   ├── dim_country.sql           # NEW
│   │   ├── dim_currency.sql          # NEW
│   │   ├── fact_rating_snapshot.sql  # NEW
│   │   ├── upload_log.sql            # NEW
│   │   └── pipeline_run_state.sql    # NEW
│   └── init_db.sh                    # MODIFIED: retail → corporate
├── tests/
│   ├── conftest.py                   # MODIFIED: remove Spark; add DB/file fixtures
│   ├── unit/
│   │   ├── __init__.py
│   │   ├── test_extractor.py         # NEW
│   │   ├── test_validator.py         # NEW
│   │   ├── test_transformer.py       # NEW
│   │   └── test_loader.py            # NEW
│   └── integration/
│       ├── __init__.py
│       ├── test_pipeline_integration.py  # NEW (replaces test_integration.py)
│       └── test_api_integration.py       # NEW
├── docker-compose.yml                # MODIFIED: remove Spark, add api service
├── pyproject.toml                    # MODIFIED: update deps/testpaths
└── README.md                         # MODIFIED: full new instructions
```

---

## Milestones & Tasks

---

### M0 — Project Cleanup & Infrastructure Setup
> Goal: strip old retail code; update containers, DB, and test config.

- [x] **M0.1** Remove `spark/` directory (clean_and_ingest.py, analysis.py, __init__ files)
- [x] **M0.2** Remove `dags/retail_pipeline_dag.py`
- [x] **M0.3** Remove retail DDL files (`sql/ddl/retail_*.sql`, `sql/ddl/sql_*.sql`)
- [x] **M0.4** Remove retail SQL queries (`sql/top_3_products_last_6m.sql`, `sql/rolling_3m_avg_australia.sql`)
- [x] **M0.5** Remove old unit tests (`tests/unit/test_cleaning.py`, `tests/unit/test_analysis.py`)
- [x] **M0.6** Update `airflow/Dockerfile`: remove OpenJDK + PySpark; add pandas, openpyxl, psycopg2, httpx
- [x] **M0.7** Update `sql/init_db.sh`: rename `retail` DB/user → `corporate`
- [x] **M0.8** Update `docker-compose.yml`: remove spark-master/spark-worker; update DB creds; add api service placeholder
- [x] **M0.9** Update `tests/conftest.py`: remove SparkSession; add psycopg2 / file fixtures
- [x] **M0.10** Update `pyproject.toml`: update test paths and add new dependencies
- [x] **M0.11** Create `data/extracted_sheets/.gitkeep` and `corporate_pipeline/__init__.py`

---

### M1 — Excel Extraction Module
> Goal: reliably extract the MASTER sheet from each `.xlsm` file and persist
> as a cleaned CSV in `data/extracted_sheets/`. Write thorough tests first.

- [x] **M1.1** Inspect all 4 `.xlsm` files: print row/column structure, actual key labels, value columns
- [x] **M1.2** Design `RawMasterRecord` dataclass (all parsed fields)
- [x] **M1.3** Implement `corporate_pipeline/extractor.py`:
  - `extract_master_sheet(filepath) → pd.DataFrame` (raw key-value frame)
  - `parse_master_sheet(df) → RawMasterRecord` (key-value → named fields)
  - `save_extracted_sheet(df, output_dir, filename)` (write CSV to `data/extracted_sheets/`)
  - `extract_all_files(input_dir, output_dir) → list[RawMasterRecord]`
- [x] **M1.4** Write `tests/unit/test_extractor.py`:
  - Sheet loads without error for all 4 files
  - Correct number of rows/columns
  - All expected keys present
  - Values extracted to correct fields
  - Leading/trailing whitespace stripped from all values
  - Entirely empty rows dropped
  - Separator handling (no issues with comma-like values in fields)
  - Output CSV saved to `data/extracted_sheets/`
  - Missing key returns `None` (not raises)
  - Two versions of same company differ on changed fields

---

### M2 — Database Schema (DDL)
> Goal: define precise SQL DDL for all corporate tables; apply via `create_tables` DAG task.

- [x] **M2.1** `sql/ddl/dim_company.sql` — SCD Type 2 company dimension
  - Columns: `company_id SERIAL PK`, `entity_name TEXT NOT NULL`, `sector_id INT FK`, `country_id INT FK`, `currency_id INT FK`, `accounting_principles TEXT`, `business_year_end_month SMALLINT`, `valid_from TIMESTAMPTZ NOT NULL`, `valid_to TIMESTAMPTZ`, `is_current BOOLEAN NOT NULL DEFAULT TRUE`, `source_upload_id INT FK`
  - Unique constraint: `(entity_name, valid_from)`
  - Check: `business_year_end_month BETWEEN 1 AND 12`
- [x] **M2.2** `sql/ddl/dim_sector.sql` — sector lookup
  - Columns: `sector_id SERIAL PK`, `sector_name TEXT NOT NULL UNIQUE`
- [x] **M2.3** `sql/ddl/dim_country.sql` — country lookup
  - Columns: `country_id SERIAL PK`, `country_name TEXT NOT NULL UNIQUE`, `iso2 CHAR(2)`, `iso3 CHAR(3)`
- [x] **M2.4** `sql/ddl/dim_currency.sql` — currency lookup
  - Columns: `currency_id SERIAL PK`, `currency_code CHAR(3) NOT NULL UNIQUE`
- [x] **M2.5** `sql/ddl/fact_rating_snapshot.sql` — one row per file upload
  - Columns: `snapshot_id SERIAL PK`, `upload_id INT FK`, `company_id INT FK`, `entity_name TEXT NOT NULL`, `sector TEXT`, `country TEXT`, `currency TEXT`, `accounting_principles TEXT`, `business_year_end_month SMALLINT`, `rating_methodology_1 TEXT`, `rating_methodology_2 TEXT`, `industry_risk_score_1 TEXT`, `industry_risk_score_2 TEXT`, `weight_1 NUMERIC(5,4)`, `weight_2 NUMERIC(5,4)`, `effective_date DATE`, `data_hash TEXT NOT NULL`, `loaded_at_utc TIMESTAMPTZ NOT NULL DEFAULT now()`
  - Unique constraint: `(data_hash)` — deduplication key
  - Check: `(weight_1 IS NULL OR weight_1 BETWEEN 0 AND 1)`
- [x] **M2.6** `sql/ddl/upload_log.sql` — file upload audit
  - Columns: `upload_id SERIAL PK`, `source_filename TEXT NOT NULL`, `file_modified_at TIMESTAMPTZ NOT NULL`, `data_hash TEXT NOT NULL`, `dag_run_id TEXT`, `rows_extracted INT`, `loaded_at_utc TIMESTAMPTZ NOT NULL DEFAULT now()`
  - Unique constraint: `(source_filename, data_hash)`
- [x] **M2.7** `sql/ddl/pipeline_run_state.sql` — tracks DAG run state for incremental loading
  - Columns: `run_id SERIAL PK`, `dag_run_id TEXT NOT NULL UNIQUE`, `started_at_utc TIMESTAMPTZ NOT NULL`, `completed_at_utc TIMESTAMPTZ`, `status TEXT NOT NULL`, `files_staged INT DEFAULT 0`, `files_loaded INT DEFAULT 0`, `files_skipped INT DEFAULT 0`
  - Check: `status IN ('running', 'success', 'failed')`

---

### M3 — Data Validation Module
> Goal: comprehensive data quality checks on extracted records; produce a quality report.

- [x] **M3.1** Design `ValidationResult` dataclass (field, rule, passed, message)
- [x] **M3.2** Implement `corporate_pipeline/validator.py`:
  - NOT NULL checks for required fields (entity_name, sector, country, currency)
  - Regex / value-set checks:
    - Currency: 3-character ISO code `^[A-Z]{3}$`
    - Business year-end month: integer 1–12
    - Weights: numeric, 0 ≤ w ≤ 1; sum of all weights ≈ 1.0 (±0.01)
    - Scores: allowed set (e.g. `{A, AA, AAA, B, BB, BBB, ...}`) or numeric range
    - Country: non-empty, stripped
    - Entity name: non-empty, stripped
    - Accounting principles: non-empty
  - Data type checks (numeric fields are numeric, dates parse correctly)
  - `validate_record(record) → list[ValidationResult]`
  - `generate_quality_report(results) → dict` (completeness %, validity %)
- [x] **M3.3** Write `tests/unit/test_validator.py`:
  - Valid record passes all checks
  - Invalid currency fails regex check
  - Weight > 1 fails range check
  - Weights not summing to 1 fails sum check
  - Missing required field fails NOT NULL check
  - Invalid month (0 or 13) fails range check
  - Report correctly computes completeness and validity rates
  - Trailing spaces in entity_name pass after strip
  - Numeric field with string value fails type check

---

### M4 — Transformation Module
> Goal: convert extracted key-value pairs into structured, typed `RatingRecord` objects ready for DB load.

- [x] **M4.1** Design `RatingRecord` dataclass (all normalized fields + metadata)
- [x] **M4.2** Implement `corporate_pipeline/transformer.py`:
  - `transform_record(raw, upload_metadata) → RatingRecord`
  - Strip all string fields of leading/trailing whitespace
  - Normalize currency to uppercase
  - Parse business year-end month (text month name → int, or int passthrough)
  - Parse weights as `Decimal` / `float`
  - Compute `data_hash = SHA-256(canonical JSON of all data fields)`
  - Populate `effective_date` from file metadata or extraction timestamp
  - `transform_all(records, metadata) → list[RatingRecord]`
- [x] **M4.3** Write `tests/unit/test_transformer.py`:
  - Whitespace stripped from all string fields
  - Currency normalized to uppercase
  - Month name → integer conversion (e.g. "December" → 12)
  - Weight parsed as float
  - Data hash is deterministic (same input → same hash)
  - Different inputs → different hashes
  - effective_date populated

---

### M5 — Incremental Loading Module
> Goal: load records to PostgreSQL with duplicate detection, incremental file selection, and `loaded_at_utc`.

- [x] **M5.1** Implement `corporate_pipeline/loader.py`:
  - `get_last_successful_run(conn) → datetime | None`
  - `stage_modified_files(input_dir, last_run_at) → list[Path]` — files with mtime > last_run_at
  - `hash_already_loaded(conn, data_hash) → bool` — check `upload_log.data_hash`
  - `upsert_dim_sector(conn, sector_name) → int`
  - `upsert_dim_country(conn, country_name) → int`
  - `upsert_dim_currency(conn, currency_code) → int`
  - `insert_upload_log(conn, ...) → int`
  - `insert_fact_snapshot(conn, record, upload_id)`
  - `scd2_upsert_company(conn, record, upload_id)`
  - `load_record(conn, record) → str` — returns "loaded" | "skipped_duplicate"
  - `record_run_state(conn, dag_run_id, status, stats)`
- [x] **M5.2** Write `tests/unit/test_loader.py`:
  - `stage_modified_files` returns only files newer than last run
  - `stage_modified_files` returns all files when last_run is None
  - `hash_already_loaded` returns True when hash exists, False when not
  - Duplicate hash → load_record returns "skipped_duplicate"
  - New hash → load_record returns "loaded"
  - SCD2 inserts new row and closes previous when company data changes
  - SCD2 does not insert duplicate when company unchanged

---

### M6 — Airflow DAG
> Goal: orchestrate the 4-stage pipeline with proper state tracking and retry logic.

- [x] **M6.1** Create `dags/corporate_ratings_dag.py`:
  - `create_tables` (PythonOperator) — apply all DDL files idempotently
  - `extract_sheets` (PythonOperator) — call `extractor.extract_all_files()`; save to `data/extracted_sheets/`; push XCom with staged file list
  - `validate_data` (PythonOperator) — run validator on each extracted record; fail task if any critical errors; log quality report
  - `transform_data` (PythonOperator) — transform + hash all records; push XCom
  - `load_to_warehouse` (PythonOperator) — incremental load; log skipped duplicates as WARNING; update `pipeline_run_state`
  - `max_active_runs=1`; `retries=2`; `retry_delay=5m`
  - `email_on_failure=True` when `ALERT_EMAIL` set
- [x] **M6.2** Wire dependencies: `create_tables >> extract_sheets >> validate_data >> transform_data >> load_to_warehouse`
- [x] **M6.3** Remove `dags/retail_pipeline_dag.py`

---

### M7 — FastAPI Service
> Goal: REST API exposing all required endpoints with Pydantic validation and OpenAPI docs.

- [x] **M7.1** `api/db.py` — psycopg2 connection pool; `get_db()` dependency
- [x] **M7.2** `api/models.py` — Pydantic response models (CompanyOut, SnapshotOut, UploadOut, etc.)
- [x] **M7.3** `api/routers/companies.py`:
  - `GET /companies` — list all companies (latest version)
  - `GET /companies/{company_id}` — company details + latest snapshot
  - `GET /companies/{company_id}/versions` — all SCD2 versions
  - `GET /companies/{company_id}/history` — time-series snapshots
  - `GET /companies/compare?company_ids=...&as_of_date=...` — point-in-time compare
- [x] **M7.4** `api/routers/snapshots.py`:
  - `GET /snapshots` — list with filters (company_id, from_date, to_date, sector, country, currency)
  - `GET /snapshots/{snapshot_id}` — specific snapshot
  - `GET /snapshots/latest` — latest per company
- [x] **M7.5** `api/routers/uploads.py`:
  - `GET /uploads` — list all uploads
  - `GET /uploads/{upload_id}/details` — upload details
  - `GET /uploads/stats` — upload statistics
- [x] **M7.6** `api/main.py` — wire routers, health check endpoint `GET /health`
- [x] **M7.7** `api/Dockerfile` — lightweight Python image with uvicorn

---

### M8 — Docker Compose & Infrastructure
> Goal: working one-command startup; remove Spark; add FastAPI service.

- [x] **M8.1** Remove `spark-master` and `spark-worker` services from `docker-compose.yml`
- [x] **M8.2** Update all Airflow env vars: `retail` → `corporate` (DB name, user, password)
- [x] **M8.3** Update Airflow volumes: remove `spark/jobs` mount; add `corporate_pipeline` mount; add `data/extracted_sheets` mount
- [x] **M8.4** Add `api` service: build from `api/Dockerfile`, depends on postgres, port 8000, env vars
- [x] **M8.5** Update postgres init: mount `sql/init_db.sh`; creates `airflow` + `corporate` databases
- [x] **M8.6** Update `airflow/Dockerfile`: remove OpenJDK/PySpark; install pandas, openpyxl, psycopg2-binary, requests, httpx

---

### M9 — Integration Tests
> Goal: all unit and integration tests pass; no task marked complete until tests pass.

- [x] **M9.1** `tests/integration/test_pipeline_integration.py`:
  - Trigger DAG; wait for success
  - Assert all 5 tasks succeeded
  - Query DB: `fact_rating_snapshot` has 4 rows (one per file)
  - Query DB: `dim_company` has 2 current companies (A and B)
  - Query DB: `upload_log` has 4 rows
  - Re-trigger DAG: all 4 files skipped (same hash); `files_skipped=4`
  - Assert `pipeline_run_state` records runs correctly
- [x] **M9.2** `tests/integration/test_api_integration.py`:
  - `GET /health` returns 200
  - `GET /companies` returns 2 companies
  - `GET /companies/{id}` returns correct fields
  - `GET /companies/{id}/versions` returns 2 versions for company A
  - `GET /companies/compare?company_ids=...` returns both companies
  - `GET /snapshots/latest` returns one per company
  - `GET /uploads` returns 4 uploads
  - `GET /uploads/stats` returns correct counts
- [x] **M9.3** Run all unit tests (`docker compose --profile test run --rm tests`) — must pass before M9 complete
- [x] **M9.4** Run all integration tests (`docker compose --profile integration-test run --rm integration-tests`) — must pass before M9 complete

---

### M10 — Documentation & Sample Outputs
> Goal: updated README; sample outputs committed to repo.

- [x] **M10.1** Update `README.md`: new project overview, startup instructions, service URLs, test commands, env vars
- [x] **M10.2** Create `sample_outputs/api_calls.md` — 10+ API call examples with responses
- [x] **M10.3** Create `sample_outputs/data_quality_report.json` — example quality report
- [x] **M10.4** Create `sample_outputs/pipeline_log.txt` — example DAG task log

---

## Progress Log

| Date | Milestone | Notes |
|------|-----------|-------|
| 2026-06-08 | DEVELOPMENT.md created | Full plan drafted; M0 starting next |
| 2026-06-08 | M0 complete | Removed Spark/retail code; updated Dockerfile, docker-compose, conftest, init_db.sh |
| 2026-06-08 | M1 complete | extractor.py implemented; 57 unit tests passing |
| 2026-06-08 | M2 complete | All 7 DDL files created (dim_sector/country/currency/company, fact_rating_snapshot, upload_log, pipeline_run_state) |
| 2026-06-08 | M3 complete | validator.py implemented; 45 unit tests passing |
| 2026-06-08 | M4 complete | transformer.py implemented; 40 unit tests passing |
| 2026-06-08 | M5 complete | loader.py implemented; 17 unit tests passing |
| 2026-06-08 | M6 complete | corporate_ratings_dag.py — 5-task DAG with XCom, incremental load, duplicate detection |
| 2026-06-08 | M7 complete | FastAPI: api/main.py, db.py, models.py, routers/companies.py, routers/snapshots.py, routers/uploads.py, api/Dockerfile |
| 2026-06-08 | M8 complete | docker-compose.yml: removed Spark, added api service, updated all env vars |
| 2026-06-08 | M9 complete | tests/integration/test_integration.py: full DAG + API integration tests (pipeline + idempotency + API); 159 unit tests passing |
| 2026-06-08 | M10 complete | README.md fully rewritten with new architecture, quick start, API examples, schema docs |
