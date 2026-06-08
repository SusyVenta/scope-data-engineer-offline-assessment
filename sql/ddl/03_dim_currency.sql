CREATE TABLE IF NOT EXISTS dim_currency (
    currency_id   SERIAL   PRIMARY KEY,
    currency_code CHAR(3)  NOT NULL,
    CONSTRAINT uq_dim_currency_code UNIQUE (currency_code),
    CONSTRAINT chk_currency_code CHECK (currency_code ~ '^[A-Z]{3}$')
);
