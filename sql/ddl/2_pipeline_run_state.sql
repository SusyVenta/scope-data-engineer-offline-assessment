-- Records each DAG run for incremental-load state tracking.
-- The load task queries MAX(completed_at_utc) WHERE status = 'success'
-- to determine which files were modified after the last successful run.
CREATE TABLE IF NOT EXISTS pipeline_run_state (
    run_id           SERIAL       PRIMARY KEY,
    dag_run_id       TEXT         NOT NULL,
    started_at_utc   TIMESTAMPTZ  NOT NULL,
    completed_at_utc TIMESTAMPTZ,
    status           TEXT         NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'success', 'failed')),
    files_staged     INT          NOT NULL DEFAULT 0,
    files_loaded     INT          NOT NULL DEFAULT 0,
    files_skipped    INT          NOT NULL DEFAULT 0,
    UNIQUE (dag_run_id)
);
