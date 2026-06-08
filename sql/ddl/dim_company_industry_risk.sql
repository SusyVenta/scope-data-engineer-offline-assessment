-- Bridge: each company version is associated with one or more industry
-- risks, each with an assigned blending weight.
-- Grain: one row per (company version, industry risk).
-- Assumption: weights for a given company version sum to 1.0.
CREATE TABLE IF NOT EXISTS dim_company_industry_risk (
    company_id       INT           NOT NULL REFERENCES dim_company(company_id),
    industry_risk_name TEXT        NOT NULL,
    weight           NUMERIC(5,4)  NOT NULL CHECK (weight >= 0 AND weight <= 1),
    CONSTRAINT pk_company_industry_risk PRIMARY KEY (company_id, industry_risk_name)
);
