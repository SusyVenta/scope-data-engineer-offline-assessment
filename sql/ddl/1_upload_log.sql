-- Tracks every file processed by the pipeline.
-- data_hash is a SHA-256 of the extracted record content — used for
-- deduplication: a file re-uploaded with identical content is skipped.
CREATE TABLE IF NOT EXISTS upload_log (
    upload_id        SERIAL        PRIMARY KEY,
    source_filename  TEXT          NOT NULL,
    file_modified_at TIMESTAMPTZ   NOT NULL,
    data_hash        TEXT          NOT NULL,
    dag_run_id       TEXT,
    rows_extracted   INT           DEFAULT 0,
    loaded_at_utc    TIMESTAMPTZ   NOT NULL DEFAULT now(),
    UNIQUE (source_filename, data_hash)
);
