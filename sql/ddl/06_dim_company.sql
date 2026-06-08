-- SCD Type 2 company dimension.
-- Each time a company's metadata changes a new row is inserted with
-- valid_from = load time, and the previous row's valid_to is set to
-- that same timestamp and is_current set to FALSE.
CREATE TABLE IF NOT EXISTS dim_company (
    company_id             SERIAL        PRIMARY KEY,
    entity_name            TEXT          NOT NULL,
    sector_id              INT           REFERENCES dim_sector(sector_id),
    country_id             INT           REFERENCES dim_country(country_id),
    currency_id            INT           REFERENCES dim_currency(currency_id),
    accounting_principles  TEXT,
    business_year_end_month SMALLINT,
    valid_from             TIMESTAMPTZ   NOT NULL,
    valid_to               TIMESTAMPTZ,
    is_current             BOOLEAN       NOT NULL DEFAULT TRUE,
    source_upload_id       INT           REFERENCES upload_log(upload_id),
    loaded_at_utc          TIMESTAMPTZ   NOT NULL DEFAULT now(),
    CONSTRAINT uq_dim_company_entity_valid_from UNIQUE (entity_name, valid_from),
    CONSTRAINT chk_business_year_end_month
        CHECK (business_year_end_month IS NULL
            OR business_year_end_month BETWEEN 1 AND 12)
);

CREATE INDEX IF NOT EXISTS idx_dim_company_entity_current
    ON dim_company (entity_name, is_current);
