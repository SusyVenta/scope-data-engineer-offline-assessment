-- SCD Type 2 company dimension.
-- Each time a company's metadata changes a new row is inserted with
-- valid_from = load time, and the previous row's valid_to is set to
-- that same timestamp and is_current set to FALSE.
--
-- Assumption: entity_name is globally unique — the same legal entity
-- cannot appear under the same name in different countries or sectors.
-- Country and reporting currency are inlined here (no dim_country /
-- dim_currency snowflake) because they are simple text attributes that
-- do not benefit from normalisation at this data volume.
CREATE TABLE IF NOT EXISTS dim_company (
    company_id                          SERIAL        PRIMARY KEY,
    entity_name                         TEXT          NOT NULL,
    sector_name                         TEXT          NOT NULL,
    country                             TEXT,
    reporting_currency                  TEXT,
    accounting_principles               TEXT,
    business_year_end_month             SMALLINT 
        CHECK (business_year_end_month IS NULL
               OR business_year_end_month BETWEEN 1 AND 12),
    industry_risk_segmentation_criteria TEXT,
    valid_from                          TIMESTAMPTZ   NOT NULL,
    valid_to                            TIMESTAMPTZ,
    is_current                          BOOLEAN       NOT NULL DEFAULT TRUE,
    source_upload_id                    INT           REFERENCES upload_log(upload_id),
    loaded_at_utc                       TIMESTAMPTZ   NOT NULL DEFAULT now(),
    UNIQUE (entity_name, valid_from),
    CONSTRAINT chk_business_year_end_month
);

CREATE INDEX IF NOT EXISTS idx_dim_company_entity_current
    ON dim_company (entity_name, is_current);
