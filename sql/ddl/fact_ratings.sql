-- Rating assessments produced by each pipeline run.
-- Grain: one row per (company version, upload).
-- Assumption: data_hash uniquely identifies a rating assessment —
-- two uploads with identical content produce the same hash and only
-- the first is inserted (deduplication via upload_log).
--
-- business_risk_profile and financial_risk_profile are the top-level
-- composite ratings computed from the sub-scores below.
-- The sub-scores are company-specific metric ratings, not time-series;
-- time-series financial data lives in fact_scope_credit.
CREATE TABLE IF NOT EXISTS fact_ratings (
    rating_id                        SERIAL        PRIMARY KEY,
    upload_id                        INT           NOT NULL REFERENCES upload_log(upload_id),
    company_id                       INT           NOT NULL REFERENCES dim_company(company_id),
    sector_id                        INT           REFERENCES dim_sector(sector_id),

    -- Composite ratings (company-specific, derived from sub-scores)
    business_risk_profile            TEXT,
    financial_risk_profile           TEXT,

    -- Business risk sub-scores
    blended_industry_risk_profile    TEXT,
    competitive_positioning          TEXT,
    market_share                     TEXT,
    diversification                  TEXT,
    operating_profitability          TEXT,
    sector_company_specific_factor_1 TEXT,
    sector_company_specific_factor_2 TEXT,

    -- Financial risk sub-scores
    leverage                         TEXT,
    interest_cover                   TEXT,
    cash_flow_cover                  TEXT,
    liquidity                        TEXT,

    data_hash                        TEXT          NOT NULL,
    loaded_at_utc                    TIMESTAMPTZ   NOT NULL DEFAULT now(),

    UNIQUE (upload_id, company_id)
);
