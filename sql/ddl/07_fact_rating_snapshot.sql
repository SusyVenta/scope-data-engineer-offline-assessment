-- One row per uploaded file / rating assessment.
-- Append-only — no updates. Temporal queries use loaded_at_utc.
-- data_hash (SHA-256 of the normalized record) enforces idempotency:
-- re-loading the same file content is rejected before insert.
CREATE TABLE IF NOT EXISTS fact_rating_snapshot (
    snapshot_id                  SERIAL        PRIMARY KEY,
    upload_id                    INT           NOT NULL REFERENCES upload_log(upload_id),
    company_id                   INT           REFERENCES dim_company(company_id),

    -- Core metadata (denormalized for query convenience)
    entity_name                  TEXT          NOT NULL,
    sector                       TEXT,
    country                      TEXT,
    currency                     TEXT,
    accounting_principles        TEXT,
    business_year_end_month      SMALLINT,

    -- Rating methodology (up to 2)
    methodology_1                TEXT,
    methodology_2                TEXT,

    -- Industry risk (up to 2 segments)
    industry_risk_1              TEXT,
    industry_risk_2              TEXT,
    industry_risk_score_1        TEXT,
    industry_risk_score_2        TEXT,
    industry_weight_1            NUMERIC(5, 4),
    industry_weight_2            NUMERIC(5, 4),
    segmentation_criteria        TEXT,

    -- Business risk sub-scores
    business_risk_profile        TEXT,
    blended_industry_risk_profile TEXT,
    competitive_positioning      TEXT,
    market_share                 TEXT,
    diversification              TEXT,
    operating_profitability      TEXT,
    sector_specific_factor_1     TEXT,
    sector_specific_factor_2     TEXT,

    -- Financial risk sub-scores
    financial_risk_profile       TEXT,
    leverage                     TEXT,
    interest_cover               TEXT,
    cash_flow_cover              TEXT,
    liquidity_adjustment         TEXT,

    -- Time-series credit metrics (stored as JSONB for flexibility)
    scope_credit_metrics         JSONB,

    -- Audit / lineage
    data_hash                    TEXT          NOT NULL,
    loaded_at_utc                TIMESTAMPTZ   NOT NULL DEFAULT now(),

    CONSTRAINT uq_fact_snapshot_data_hash UNIQUE (data_hash),
    CONSTRAINT chk_fact_snapshot_weight_1
        CHECK (industry_weight_1 IS NULL OR industry_weight_1 BETWEEN 0 AND 1),
    CONSTRAINT chk_fact_snapshot_weight_2
        CHECK (industry_weight_2 IS NULL OR industry_weight_2 BETWEEN 0 AND 1),
    CONSTRAINT chk_fact_snapshot_year_end_month
        CHECK (business_year_end_month IS NULL
            OR business_year_end_month BETWEEN 1 AND 12)
);

CREATE INDEX IF NOT EXISTS idx_fact_snapshot_entity
    ON fact_rating_snapshot (entity_name, loaded_at_utc DESC);

CREATE INDEX IF NOT EXISTS idx_fact_snapshot_upload
    ON fact_rating_snapshot (upload_id);
