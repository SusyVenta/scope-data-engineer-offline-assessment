Interactive Swagger UI is available at **http://localhost:8000/docs**. All examples below were captured against a live stack with the four sample `.xlsm` files loaded.

---

#### 1. `GET /health`

```bash
curl http://localhost:8000/health
```

```json
{
    "status": "ok"
}
```

---

#### 2. `GET /companies` — list all companies (current version)

```bash
curl http://localhost:8000/companies
```

```json
[
    {
        "company_id": 2,
        "entity_name": "Company A",
        "sector": "Personal & Household Goods",
        "country": "Federal Republic of Germany",
        "currency": "EUR",
        "accounting_principles": "IFRS",
        "business_year_end_month": 12,
        "valid_from": "2026-06-08T19:04:57.884512Z",
        "loaded_at_utc": "2026-06-08T19:04:57.884448Z"
    },
    {
        "company_id": 4,
        "entity_name": "Company B",
        "sector": "Automobiles & Parts",
        "country": "Swiss Confederation",
        "currency": "CHF",
        "accounting_principles": "IFRS",
        "business_year_end_month": 3,
        "valid_from": "2026-06-08T19:04:57.892343Z",
        "loaded_at_utc": "2026-06-08T19:04:57.892278Z"
    }
]
```

---

#### 3. `GET /companies/{entity_name}` — get current record for one company

```bash
curl 'http://localhost:8000/companies/Company%20A'
```

```json
{
    "company_id": 2,
    "entity_name": "Company A",
    "sector": "Personal & Household Goods",
    "country": "Federal Republic of Germany",
    "currency": "EUR",
    "accounting_principles": "IFRS",
    "business_year_end_month": 12,
    "valid_from": "2026-06-08T19:04:57.884512Z",
    "valid_to": null,
    "is_current": true,
    "loaded_at_utc": "2026-06-08T19:04:57.884448Z"
}
```

---

#### 4. `GET /companies/{entity_name}/versions` — all SCD-2 versions

```bash
curl 'http://localhost:8000/companies/Company%20A/versions'
```

```json
[
    {
        "company_id": 1,
        "entity_name": "Company A",
        "sector": "Personal & Household Goods",
        "country": "Federal Republic of Germany",
        "currency": "EUR",
        "accounting_principles": "IFRS",
        "business_year_end_month": 12,
        "valid_from": "2026-06-08T19:04:57.877622Z",
        "valid_to": "2026-06-08T19:04:57.884512Z",
        "is_current": false,
        "loaded_at_utc": "2026-06-08T19:04:57.877258Z"
    },
    {
        "company_id": 2,
        "entity_name": "Company A",
        "sector": "Personal & Household Goods",
        "country": "Federal Republic of Germany",
        "currency": "EUR",
        "accounting_principles": "IFRS",
        "business_year_end_month": 12,
        "valid_from": "2026-06-08T19:04:57.884512Z",
        "valid_to": null,
        "is_current": true,
        "loaded_at_utc": "2026-06-08T19:04:57.884448Z"
    }
]
```

Two versions because `corporates_A_2.xlsm` changed an industry risk score, triggering a new SCD-2 row.

---

#### 5. `GET /companies/{entity_name}/history` — Scope Credit Metrics time-series

Returns all rows from `fact_scope_credit_hist`: one row per (metric, year, upload). The full response for Company A contains 120 rows across 6 metrics and multiple years (actuals + estimates). A representative sample is shown below.

```bash
curl 'http://localhost:8000/companies/Company%20A/history'
```

```json
[
    {
        "scope_credit_id": 51,
        "company_id": 1,
        "upload_id": 1,
        "entity_name": "Company A",
        "metric_name": "Liquidity (time-series)",
        "year": "2018",
        "metric_value": "4.862",
        "loaded_at_utc": "2026-06-08T19:04:57.877622Z"
    },
    {
        "scope_credit_id": 111,
        "company_id": 2,
        "upload_id": 2,
        "entity_name": "Company A",
        "metric_name": "Liquidity (time-series)",
        "year": "2018",
        "metric_value": "4.862",
        "loaded_at_utc": "2026-06-08T19:04:57.884512Z"
    },
    {
        "scope_credit_id": 1,
        "company_id": 1,
        "upload_id": 1,
        "entity_name": "Company A",
        "metric_name": "Scope-adjusted EBITDA interest cover",
        "year": "2018",
        "metric_value": "2.5",
        "loaded_at_utc": "2026-06-08T19:04:57.877622Z"
    },
    "... (120 rows total — 6 metrics × years 2018–2027E × 2 uploads)"
]
```

Available metrics: `Liquidity (time-series)`, `Scope-adjusted debt/EBITDA`, `Scope-adjusted EBITDA interest cover`, `Scope-adjusted FFO/debt`, `Scope-adjusted FOCF/debt`, `Scope-adjusted loan/value`.

---

#### 6. `GET /companies/compare` — side-by-side comparison of two companies

```bash
curl 'http://localhost:8000/companies/compare?entity_names=Company%20A,Company%20B'
```

To compare at a specific point in time, add `&as_of_date=2026-06-08T20:00:00Z`.

```json
{
    "as_of_date": null,
    "companies": [
        {
            "snapshot_id": 2,
            "upload_id": 2,
            "company_id": 2,
            "entity_name": "Company A",
            "sector": "Personal & Household Goods",
            "country": "Federal Republic of Germany",
            "currency": "EUR",
            "business_risk_profile": "B",
            "financial_risk_profile": "CC",
            "blended_industry_risk_profile": "A",
            "competitive_positioning": "B+",
            "market_share": "B+",
            "diversification": "B+",
            "operating_profitability": "B",
            "sector_company_specific_factor_1": "B-",
            "sector_company_specific_factor_2": null,
            "leverage": "CCC",
            "interest_cover": "B-",
            "cash_flow_cover": "CCC",
            "liquidity": "-2 notches",
            "data_hash": "b38121183edc8221806789de43de6fc470678e525c10c9afe25883385c7c3020",
            "loaded_at_utc": "2026-06-08T19:04:57.884512Z"
        },
        {
            "snapshot_id": 4,
            "upload_id": 4,
            "company_id": 4,
            "entity_name": "Company B",
            "sector": "Automobiles & Parts",
            "country": "Swiss Confederation",
            "currency": "CHF",
            "business_risk_profile": "BBB-",
            "financial_risk_profile": "BB",
            "blended_industry_risk_profile": "A",
            "competitive_positioning": "A+",
            "market_share": "BBB+",
            "diversification": "A-",
            "operating_profitability": "BB+",
            "sector_company_specific_factor_1": "BBB+",
            "sector_company_specific_factor_2": null,
            "leverage": "BB+",
            "interest_cover": "BBB+",
            "cash_flow_cover": "A-",
            "liquidity": "+1 notch",
            "data_hash": "73e2ed7397759498b510865535fee3949ce104ea996df36ea4521116b6542984",
            "loaded_at_utc": "2026-06-08T19:04:57.892343Z"
        }
    ]
}
```

---

#### 7. `GET /snapshots/latest` — most recent snapshot per company

```bash
curl http://localhost:8000/snapshots/latest
```

Returns one row per entity (same shape as the compare response above, one object per company).

---

#### 8. `GET /snapshots` — filtered snapshot list

```bash
curl 'http://localhost:8000/snapshots?currency=EUR'
```

```json
[
    {
        "snapshot_id": 2,
        "upload_id": 2,
        "company_id": 2,
        "entity_name": "Company A",
        "sector": "Personal & Household Goods",
        "country": "Federal Republic of Germany",
        "currency": "EUR",
        "business_risk_profile": "B",
        "financial_risk_profile": "CC",
        "blended_industry_risk_profile": "A",
        "competitive_positioning": "B+",
        "market_share": "B+",
        "diversification": "B+",
        "operating_profitability": "B",
        "sector_company_specific_factor_1": "B-",
        "sector_company_specific_factor_2": null,
        "leverage": "CCC",
        "interest_cover": "B-",
        "cash_flow_cover": "CCC",
        "liquidity": "-2 notches",
        "data_hash": "b38121183edc8221806789de43de6fc470678e525c10c9afe25883385c7c3020",
        "loaded_at_utc": "2026-06-08T19:04:57.884512Z"
    },
    {
        "snapshot_id": 1,
        "upload_id": 1,
        "company_id": 1,
        "entity_name": "Company A",
        "sector": "Personal & Household Goods",
        "country": "Federal Republic of Germany",
        "currency": "EUR",
        "business_risk_profile": "B+",
        "financial_risk_profile": "C",
        "blended_industry_risk_profile": "A",
        "competitive_positioning": "B+",
        "market_share": "BB-",
        "diversification": "B+",
        "operating_profitability": "BB-",
        "sector_company_specific_factor_1": "B-",
        "sector_company_specific_factor_2": null,
        "leverage": "CCC",
        "interest_cover": "B-",
        "cash_flow_cover": "CCC",
        "liquidity": "-2 notches",
        "data_hash": "b8189ffc74352721bafaa2a0be9792d42adaff4cca489bf5ebba8d94cf58cc9a",
        "loaded_at_utc": "2026-06-08T19:04:57.877622Z"
    }
]
```

Other supported filters: `company_id`, `from_date`, `to_date`, `sector`, `country`.

---

#### 9. `GET /snapshots/{snapshot_id}` — single snapshot

```bash
curl http://localhost:8000/snapshots/1
```

```json
{
    "snapshot_id": 1,
    "upload_id": 1,
    "company_id": 1,
    "entity_name": "Company A",
    "sector": "Personal & Household Goods",
    "country": "Federal Republic of Germany",
    "currency": "EUR",
    "business_risk_profile": "B+",
    "financial_risk_profile": "C",
    "blended_industry_risk_profile": "A",
    "competitive_positioning": "B+",
    "market_share": "BB-",
    "diversification": "B+",
    "operating_profitability": "BB-",
    "sector_company_specific_factor_1": "B-",
    "sector_company_specific_factor_2": null,
    "leverage": "CCC",
    "interest_cover": "B-",
    "cash_flow_cover": "CCC",
    "liquidity": "-2 notches",
    "data_hash": "b8189ffc74352721bafaa2a0be9792d42adaff4cca489bf5ebba8d94cf58cc9a",
    "loaded_at_utc": "2026-06-08T19:04:57.877622Z"
}
```

---

#### 10. `GET /uploads` — upload log

```bash
curl http://localhost:8000/uploads
```

```json
[
    {
        "upload_id": 4,
        "source_filename": "corporates_B_2.xlsm",
        "file_modified_at": "2026-06-08T09:25:18.218305Z",
        "data_hash": "73e2ed7397759498b510865535fee3949ce104ea996df36ea4521116b6542984",
        "dag_run_id": "manual__2026-06-08T19:04:52.613374+00:00",
        "rows_extracted": 1,
        "loaded_at_utc": "2026-06-08T19:04:57.892278Z"
    },
    {
        "upload_id": 3,
        "source_filename": "corporates_B_1.xlsm",
        "file_modified_at": "2026-06-08T09:25:15.591592Z",
        "data_hash": "861cee3eac72cc6d38b60f943a15ee215bfe1ee90fe0231d721277b02bb4fea5",
        "dag_run_id": "manual__2026-06-08T19:04:52.613374+00:00",
        "rows_extracted": 1,
        "loaded_at_utc": "2026-06-08T19:04:57.888584Z"
    },
    {
        "upload_id": 2,
        "source_filename": "corporates_A_2.xlsm",
        "file_modified_at": "2026-06-08T09:25:13.087557Z",
        "data_hash": "b38121183edc8221806789de43de6fc470678e525c10c9afe25883385c7c3020",
        "dag_run_id": "manual__2026-06-08T19:04:52.613374+00:00",
        "rows_extracted": 1,
        "loaded_at_utc": "2026-06-08T19:04:57.884448Z"
    },
    {
        "upload_id": 1,
        "source_filename": "corporates_A_1.xlsm",
        "file_modified_at": "2026-06-08T09:25:10.358468Z",
        "data_hash": "b8189ffc74352721bafaa2a0be9792d42adaff4cca489bf5ebba8d94cf58cc9a",
        "dag_run_id": "manual__2026-06-08T19:04:52.613374+00:00",
        "rows_extracted": 1,
        "loaded_at_utc": "2026-06-08T19:04:57.877258Z"
    }
]
```

---

#### 11. `GET /uploads/stats` — aggregate upload metrics

```bash
curl http://localhost:8000/uploads/stats
```

```json
{
    "total_uploads": 4,
    "unique_files": 4,
    "unique_companies": 4,
    "earliest_upload": "2026-06-08T19:04:57.877258Z",
    "latest_upload": "2026-06-08T19:04:57.892278Z"
}
```

---

#### 12. `GET /uploads/{upload_id}/details` — upload entry with its rating snapshots

```bash
curl http://localhost:8000/uploads/1/details
```

```json
{
    "upload_id": 1,
    "source_filename": "corporates_A_1.xlsm",
    "file_modified_at": "2026-06-08T09:25:10.358468Z",
    "data_hash": "b8189ffc74352721bafaa2a0be9792d42adaff4cca489bf5ebba8d94cf58cc9a",
    "dag_run_id": "manual__2026-06-08T19:04:52.613374+00:00",
    "rows_extracted": 1,
    "loaded_at_utc": "2026-06-08T19:04:57.877258Z",
    "snapshots": [
        {
            "snapshot_id": 1,
            "upload_id": 1,
            "company_id": 1,
            "entity_name": "Company A",
            "sector": "Personal & Household Goods",
            "country": "Federal Republic of Germany",
            "currency": "EUR",
            "business_risk_profile": "B+",
            "financial_risk_profile": "C",
            "blended_industry_risk_profile": "A",
            "competitive_positioning": "B+",
            "market_share": "BB-",
            "diversification": "B+",
            "operating_profitability": "BB-",
            "sector_company_specific_factor_1": "B-",
            "sector_company_specific_factor_2": null,
            "leverage": "CCC",
            "interest_cover": "B-",
            "cash_flow_cover": "CCC",
            "liquidity": "-2 notches",
            "data_hash": "b8189ffc74352721bafaa2a0be9792d42adaff4cca489bf5ebba8d94cf58cc9a",
            "loaded_at_utc": "2026-06-08T19:04:57.877622Z"
        }
    ]
}
```

---

#### 13. `GET /uploads/{upload_id}/file` — download original source file

```bash
curl -O http://localhost:8000/uploads/1/file
```

Returns the original `corporates_A_1.xlsm` file as a binary download.

```
HTTP 200
Content-Type: application/vnd.ms-excel.sheet.macroenabled.12
Content-Disposition: attachment; filename="corporates_A_1.xlsm"
Content-Length: 146963
```
