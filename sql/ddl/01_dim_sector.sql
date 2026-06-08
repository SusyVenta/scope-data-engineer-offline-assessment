CREATE TABLE IF NOT EXISTS dim_sector (
    sector_id   SERIAL      PRIMARY KEY,
    sector_name TEXT        NOT NULL,
    CONSTRAINT uq_dim_sector_name UNIQUE (sector_name)
);
