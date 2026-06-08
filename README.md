# Corporate Credit Rating Data Pipeline

End-to-end data pipeline for corporate credit rating Excel files. Extracts, validates, transforms, and loads structured rating data into a PostgreSQL star schema, orchestrated with **Apache Airflow** and queryable via a **FastAPI** REST service — all in Docker Compose.

---

## Project structure

```
.
├── airflow/
│   └── Dockerfile                  # Custom Airflow image (pandas + openpyxl + providers)
├── api/
│   ├── Dockerfile                  # FastAPI service image
│   ├── main.py                     # App entry point; wires all routers
│   ├── db.py                       # psycopg2 connection pool
│   ├── models.py                   # Pydantic response models
│   └── routers/
│       ├── companies.py            # GET /companies (list, compare, versions, history)
│       ├── snapshots.py            # GET /snapshots (list, latest, by id)
│       └── uploads.py             # GET /uploads (list, details, stats)
├── corporate_pipeline/
│   ├── extractor.py                # Excel → pandas DataFrame + RawMasterRecord
│   ├── validator.py                # Data quality checks (NOT NULL, regex, value sets)
│   ├── transformer.py              # Normalise, hash, build RatingRecord
│   └── loader.py                   # SCD2 upserts, incremental load, duplicate detection
├── dags/
│   └── corporate_ratings_dag.py    # Airflow DAG (daily schedule, 5 tasks)
├── data/
│   ├── input_files/                # Place .xlsm rating files here
│   └── extracted_sheets/           # Auto-created: one CSV per extracted sheet
├── sql/
│   ├── ddl/
│   │   ├── 01_dim_sector.sql
│   │   ├── 04_upload_log.sql
│   │   ├── 05_pipeline_run_state.sql
│   │   ├── 06_dim_company.sql          # SCD Type 2 (valid_from/valid_to/is_current)
│   │   ├── 07_fact_ratings.sql         # Append-only rating scores, UNIQUE(data_hash)
│   │   ├── 08_dim_industry_risk.sql
│   │   ├── 09_company_industry_risk.sql  # Bridge: company ↔ industry risk + weight
│   │   ├── 10_dim_rating_methodology.sql
│   │   ├── 11_company_methodology.sql  # Bridge: company ↔ methodology
│   │   └── 12_fact_scope_credit.sql    # Time-series financial metrics by year
│   └── init_db.sh                      # Creates airflow + corporate databases on first start
├── tests/
│   ├── conftest.py                 # Shared fixtures + email notification hook
│   ├── unit/
│   │   ├── test_extractor.py       # 57 tests: Excel parsing, key-value extraction
│   │   ├── test_validator.py       # 45 tests: NOT NULL, regex, value-set checks
│   │   ├── test_transformer.py     # 40 tests: normalisation, SHA-256 hashing
│   │   └── test_loader.py          # 17 tests: SCD2, incremental load, deduplication
│   └── integration/
│       └── test_integration.py     # End-to-end DAG + API tests (requires full stack)
├── docker-compose.yml
└── README.md
```

---

## Prerequisites

### Install Docker

Download Docker Desktop from https://www.docker.com/products/docker-desktop/ and complete first-run setup.

```bash
docker --version            # Docker version 29.x.x
docker compose version      # Docker Compose version v2.x.x
```

---

## Quick start

### 1 — Start everything

**First time / production** — starts all services in the background and returns immediately:

```bash
docker compose up -d
```

Check status manually once started (≈ 60 s on first start):

```bash
docker compose ps   # all should show "healthy" or "exited (0)"
```

**Development (clean restart)** — removes all containers, **wipes all database volumes**, rebuilds images, starts fresh, and **blocks until every service is healthy** before returning:

```bash
make up
```

`make up` runs `docker compose down -v` first, which deletes the `postgres_data` volume — the database is fully empty on each restart. When the command returns, all services are confirmed healthy and the DB schemas have been re-initialised.

Either way, startup order is handled automatically:
1. **postgres** starts and passes its health check
2. **airflow-init** runs once to create the Airflow metadata schema and `admin` user, then exits
3. **airflow-webserver** and **airflow-scheduler** wait for init to complete, then start
4. **api** starts once postgres is healthy

| Service | URL | Credentials |
|---------|-----|-------------|
| Airflow UI | http://localhost:8091 | `admin` / `admin` |
| FastAPI docs | http://localhost:8000/docs | — |
| FastAPI ReDoc | http://localhost:8000/redoc | — |
| PostgreSQL | `localhost:5432` | superuser `postgres` / `postgres` |

---

### 2 — Place input files

Copy your `.xlsm` rating files into `data/input_files/`:

```bash
ls data/input_files/*.xlsm
```

---

### 4 — Trigger the pipeline

**Via the Airflow UI:**
1. Open http://localhost:8091 and log in with `admin` / `admin`
2. Unpause the `corporate_ratings_pipeline` DAG (toggle on the left).
3. Click **Trigger DAG** (play button ▶).

**Via the CLI:**

```bash
docker compose exec airflow-scheduler \
    airflow dags trigger corporate_ratings_pipeline
```

---

### 5 — Monitor execution

```bash
# Live scheduler logs
docker compose logs -f airflow-scheduler

# Task logs are in the Airflow UI:
# DAGs → corporate_ratings_pipeline → <run> → <task> → Logs
```

The DAG has five sequential steps:

```
create_tables >> extract_sheets >> validate_data >> transform_data >> load_to_warehouse
```

| Task | Description |
|------|-------------|
| `create_tables` | Applies all DDL files (`CREATE TABLE IF NOT EXISTS`) |
| `extract_sheets` | Reads each staged `.xlsm`, saves extracted CSV, pushes `RawMasterRecord` list via XCom |
| `validate_data` | NOT NULL, regex, value-set and weight checks; fails on any CRITICAL error |
| `transform_data` | Normalises fields, computes SHA-256 data hash, produces `RatingRecord` list |
| `load_to_warehouse` | SCD2 upserts to `dim_company`; populates bridge tables, `fact_ratings`, `fact_scope_credit`; skips duplicates with WARNING |

**Incremental loading:** only files modified after the last successful DAG run are staged. If a file is re-uploaded with identical content (hash match), it is skipped with a clear `WARNING` log and the run completes successfully.

---

### 6 — Explore the API

Interactive docs at http://localhost:8000/docs.

**Sample requests:**

```bash
# List current companies
curl http://localhost:8000/companies

# All SCD2 versions for company 1
curl http://localhost:8000/companies/1/versions

# Rating history (all snapshots) for company 1
curl http://localhost:8000/companies/1/history

# Latest snapshot per company
curl http://localhost:8000/snapshots/latest

# All snapshots for a company
curl "http://localhost:8000/snapshots?company_id=1"

# Compare two companies at a point in time
curl "http://localhost:8000/companies/compare?company_ids=1,2&as_of_date=2024-06-01T00:00:00"

# Upload stats
curl http://localhost:8000/uploads/stats

# Details for upload 1 (includes snapshots)
curl http://localhost:8000/uploads/1/details
```

---

### 7 — Inspect results in PostgreSQL

**Option A — psql (terminal):**

```bash
docker compose exec postgres \
    psql -U corporate -d corporate
```

Tip: run `\x auto` inside psql for automatic expanded display, or pass `-x` and a query directly:

```bash
docker compose exec postgres \
    psql -U corporate -d corporate -x -c "SELECT * FROM pipeline_run_state ORDER BY started_at_utc DESC;"
```

**Option B — VS Code SQLTools extension (optional, recommended for interactive querying):**

1. Install **SQLTools** and **SQLTools PostgreSQL/Cockroach Driver** from the VS Code Extensions panel.
2. Add a new connection with these settings:

| Field | Value |
|---|---|
| Host | `localhost` |
| Port | `5432` |
| Database | `corporate` |
| Username | `corporate` |
| Password | `corporate` |

You then get syntax highlighting, autocomplete, and results in a table view directly in the IDE.

Useful queries:

```sql
-- Pipeline run history
SELECT dag_run_id, status, files_staged, files_loaded, files_skipped, completed_at_utc
FROM pipeline_run_state
ORDER BY started_at_utc DESC;

-- All current companies with sector
SELECT dc.entity_name, ds.sector_name, dc.country, dc.reporting_currency,
       dc.accounting_principles, dc.valid_from
FROM dim_company dc
LEFT JOIN dim_sector ds ON ds.sector_id = dc.sector_id
WHERE dc.is_current = TRUE
ORDER BY dc.entity_name;

-- Industry risk weights per company (current version only)
SELECT dc.entity_name, dir.industry_risk_name, cir.weight
FROM company_industry_risk cir
JOIN dim_company      dc  ON dc.company_id       = cir.company_id
JOIN dim_industry_risk dir ON dir.industry_risk_id = cir.industry_risk_id
WHERE dc.is_current = TRUE
ORDER BY dc.entity_name, cir.weight DESC;

-- Methodologies applied per company (current version only)
SELECT dc.entity_name, drm.methodology_name
FROM company_methodology cm
JOIN dim_company          dc  ON dc.company_id    = cm.company_id
JOIN dim_rating_methodology drm ON drm.methodology_id = cm.methodology_id
WHERE dc.is_current = TRUE
ORDER BY dc.entity_name;

-- All rating scores
SELECT dc.entity_name, ds.sector_name,
       fr.business_risk_profile, fr.financial_risk_profile,
       fr.leverage, fr.liquidity, fr.loaded_at_utc
FROM fact_ratings fr
LEFT JOIN dim_company dc ON dc.company_id = fr.company_id
LEFT JOIN dim_sector  ds ON ds.sector_id  = fr.sector_id
ORDER BY fr.loaded_at_utc DESC;

-- Time-series scope credit metrics for a company
SELECT dc.entity_name, fsc.metric_name, fsc.year, fsc.metric_value
FROM fact_scope_credit fsc
JOIN dim_company dc ON dc.company_id = fsc.company_id
WHERE dc.entity_name = 'Acme Corp'
ORDER BY fsc.metric_name, fsc.year;

-- SCD2 history for a company
SELECT entity_name, valid_from, valid_to, is_current
FROM dim_company
WHERE entity_name = 'Acme Corp'
ORDER BY valid_from;

-- Upload log
SELECT source_filename, rows_extracted, data_hash, loaded_at_utc
FROM upload_log
ORDER BY loaded_at_utc DESC;
```

---

## Running tests

### All tests (unit + integration) — single command

No prior `make up` is needed. This command starts all required services from scratch (or reuses running ones), then runs all tests:

```bash
make test
```

Expected output:

```
222 passed in ~40s
```

The command handles everything automatically:
- Builds images if not already built
- Starts postgres, Airflow init, webserver, scheduler, and a test-isolated API instance
- Truncates the `corporate_test` schema before the integration run so tests always start clean
- Tears down the run container when done (long-running services remain up)

Integration tests write to the `corporate_test` schema — the production `public` schema is never touched.

---

### Unit tests only

```bash
make test-unit
```

Expected: `159 passed`

**Coverage report:**

```bash
docker compose --profile test run --rm tests \
    python -m pytest tests/unit --cov=corporate_pipeline --cov-report=term-missing
```

---

### Integration tests only

```bash
make test-integration
```

Expected: `63 passed`

The integration test suite:
1. Truncates the `corporate_test` schema and clears prior DAG runs
2. Triggers the `corporate_ratings_pipeline_integration` DAG (using the test Airflow connection)
3. Polls every 15 s until success (timeout 15 min)
4. Verifies all 5 tasks succeeded and checks every DB table including bridge tables and `fact_scope_credit`
5. Re-triggers and verifies idempotency (`files_loaded=0`)
6. Exercises all `/companies`, `/snapshots`, and `/uploads` API endpoints

---

## Data model

### Conceptual model

```
                      ┌──────────────────────────────────────┐
                      │           dim_sector                 │
                      │  sector_id PK, sector_name UNIQUE    │
                      └───────────────┬──────────────────────┘
                                      │ FK sector_id
                      ┌───────────────▼──────────────────────┐
                      │           dim_company  (SCD Type 2)  │
                      │  company_id PK                        │
                      │  entity_name + valid_from UNIQUE      │
                      │  country, reporting_currency (inline) │
                      │  industry_risk_segmentation_criteria  │
                      └──┬──────────────────────┬────────────┘
                         │                      │
          ┌──────────────▼──────┐  ┌────────────▼────────────────────┐
          │ company_industry_   │  │    company_methodology           │
          │ risk (bridge)       │  │    (bridge)                      │
          │ (company_id,        │  │    (company_id, methodology_id)  │
          │  industry_risk_id,  │  └────────────┬────────────────────┘
          │  weight)            │               │ FK methodology_id
          └──────────┬──────────┘  ┌────────────▼───────────────────┐
                     │ FK          │    dim_rating_methodology       │
          ┌──────────▼──────────┐  │    methodology_id PK           │
          │  dim_industry_risk  │  │    methodology_name UNIQUE      │
          │  industry_risk_id PK│  └────────────────────────────────┘
          │  industry_risk_name │
          │  UNIQUE             │
          └─────────────────────┘

upload_log ──► fact_ratings ◄── dim_company ──► dim_sector
upload_log ──► fact_scope_credit ◄── dim_company
```

### Tables

| Table | Grain | Description |
|-------|-------|-------------|
| `dim_sector` | 1 row per sector name | Lookup; `UNIQUE(sector_name)` |
| `dim_company` | 1 row per (entity, version) | SCD Type 2; `is_current=TRUE` is the active version; country and reporting_currency inlined |
| `dim_industry_risk` | 1 row per risk name | Lookup; `UNIQUE(industry_risk_name)` |
| `company_industry_risk` | 1 row per (company version, risk) | Bridge with blending weight; `PK(company_id, industry_risk_id)` |
| `dim_rating_methodology` | 1 row per methodology name | Lookup; `UNIQUE(methodology_name)` |
| `company_methodology` | 1 row per (company version, methodology) | Bridge; `PK(company_id, methodology_id)` |
| `fact_ratings` | 1 row per upload | Rating scores per upload; `UNIQUE(data_hash)` prevents duplicates |
| `fact_scope_credit` | 1 row per (upload, metric, year) | Time-series financial metrics from [Scope Credit Metrics]; `UNIQUE(upload_id, metric_name, year)` |
| `upload_log` | 1 row per processed file | Filename, mtime, hash, row count |
| `pipeline_run_state` | 1 row per DAG run | Status, file counts, timestamps |

### Key design decisions and assumptions

**`entity_name` is globally unique.** The same legal entity name cannot appear in different sectors or countries. This is enforced by `UNIQUE(entity_name, valid_from)` in `dim_company` and drives the SCD2 lookup.

**Country and currency are inlined into `dim_company`.** `dim_country` and `dim_currency` would add a snowflake join with no analytical benefit at this data volume, since country and currency are attributes of a company version, not shared lookup tables.

**SCD2 triggers on any metadata change**, including changes to industry risk weights or applied methodologies. When any of the following change — sector, country, reporting_currency, accounting_principles, business_year_end_month, industry_risk_segmentation_criteria, industry risk assignments or weights, or methodologies — a new company version is inserted with a fresh `company_id` and the previous version is closed (`valid_to` set, `is_current=FALSE`).

**Bridge tables are versioned through `company_id`.** Because `company_industry_risk` and `company_methodology` reference `company_id` (a specific SCD2 version, not the entity), changing a risk weight automatically creates a new company version, preserving the full history.

**`business_risk_profile` and `financial_risk_profile`** are composite rating scores computed from the sub-scores in the same `fact_ratings` row. They represent the analyst's overall assessment of business risk and financial risk respectively, derived from:
- Business: `blended_industry_risk_profile`, `competitive_positioning`, `market_share`, `diversification`, `operating_profitability`, `sector_company_specific_factor_1/2`
- Financial: `leverage`, `interest_cover`, `cash_flow_cover`, `liquidity`

**`fact_scope_credit`** stores the time-series financial data from the [Scope Credit Metrics] Excel section. Each metric (e.g. "Operating Revenue", "EBITDA", "Total Debt") × year × upload is one row. `metric_value` is TEXT to accommodate numeric values, estimated periods like "2025E", and qualitative entries like "adequate" (for Liquidity).

---

## Incremental loading and deduplication

- **File-level incremental**: `stage_modified_files` compares each file's `mtime` against the last successful run timestamp from `pipeline_run_state`. Files not modified since the last run are skipped entirely.
- **Content-level deduplication**: a SHA-256 hash of all business fields (excluding filename and mtime) is computed at transform time. Before inserting, `hash_already_loaded` queries `upload_log`. If the hash exists, the file is skipped with a `WARNING` log and the run exits successfully — no duplicate rows are ever written to `fact_ratings` or `fact_scope_credit`.

---

## Email notifications

Notifications are disabled by default. Set `ALERT_EMAIL` to enable them.

All SMTP settings live in `docker-compose.yml` under `x-airflow-common`:

```yaml
AIRFLOW__SMTP__SMTP_HOST: "smtp.gmail.com"
AIRFLOW__SMTP__SMTP_PORT: "587"
AIRFLOW__SMTP__SMTP_STARTTLS: "true"
AIRFLOW__SMTP__SMTP_USER: "you@gmail.com"
AIRFLOW__SMTP__SMTP_PASSWORD: "your-app-password"
AIRFLOW__SMTP__SMTP_MAIL_FROM: "you@gmail.com"
ALERT_EMAIL: "alerts@yourteam.com"    # set "" to disable
```

| Event | Mechanism |
|-------|-----------|
| Any Airflow task fails (after retries) | Airflow built-in `email_on_failure` |
| Any unit or integration test fails | `pytest_sessionfinish` hook in `tests/conftest.py` |

> **Security:** avoid committing real SMTP credentials. Use a `.env` file (add to `.gitignore`) or a secrets manager in production.

---

## Environment variables reference

| Variable | Default | Description |
|----------|---------|-------------|
| `INPUT_FILES_DIR` | `/opt/airflow/data/input_files` | Directory scanned for `.xlsm` files |
| `EXTRACTED_SHEETS_DIR` | `/opt/airflow/data/extracted_sheets` | Output directory for extracted CSVs |
| `POSTGRES_HOST` | `postgres` | PostgreSQL hostname |
| `POSTGRES_PORT` | `5432` | PostgreSQL port |
| `POSTGRES_DB` | `corporate` | Corporate database name |
| `POSTGRES_USER` | `corporate` | Database user |
| `POSTGRES_PASSWORD` | `corporate` | Database password |
| `ALERT_EMAIL` | `""` | Failure alert recipient; empty = disabled |

---

## Tear down

```bash
# Stop containers (keeps data)
docker compose down

# Stop and remove everything including volumes
make down
```
