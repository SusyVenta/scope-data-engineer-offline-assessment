-- Time-series financial metrics from the [Scope Credit Metrics] section.
-- Grain: one row per (upload, metric name, reporting year).
-- metric_value is TEXT to accommodate numeric values, "Locked", "No data",
-- and qualitative ratings like "adequate".
-- year is TEXT to accommodate estimated periods (e.g. "2025E").
CREATE TABLE IF NOT EXISTS fact_scope_credit_hist (
    scope_credit_id SERIAL      PRIMARY KEY,
    company_id      INT         NOT NULL REFERENCES dim_company(company_id),
    upload_id       INT         NOT NULL REFERENCES upload_log(upload_id),
    metric_name     TEXT        NOT NULL,
    year            TEXT        NOT NULL,
    metric_value    TEXT,
    loaded_at_utc   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_fact_scope_credit UNIQUE (upload_id, metric_name, year)
);
