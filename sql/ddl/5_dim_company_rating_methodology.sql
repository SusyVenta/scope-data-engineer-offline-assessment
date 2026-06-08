-- Bridge: each company version can be assessed under one or more rating
-- methodologies. Grain: one row per (company version, rating methodology).
-- Designed to support N methodologies per company (not just 1 or 2).
CREATE TABLE IF NOT EXISTS dim_company_rating_methodology (
    company_id     INT NOT NULL REFERENCES dim_company(company_id),
    rating_methodology_name TEXT   NOT NULL,
    CONSTRAINT pk_company_methodology PRIMARY KEY (company_id, rating_methodology_name)
);
