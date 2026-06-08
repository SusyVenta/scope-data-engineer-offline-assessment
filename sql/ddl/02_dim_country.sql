CREATE TABLE IF NOT EXISTS dim_country (
    country_id   SERIAL      PRIMARY KEY,
    country_name TEXT        NOT NULL,
    CONSTRAINT uq_dim_country_name UNIQUE (country_name)
);
