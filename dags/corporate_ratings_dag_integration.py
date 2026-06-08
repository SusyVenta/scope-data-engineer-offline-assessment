"""
corporate_ratings_dag_integration.py
-------------------------------------
Integration-test variant of the corporate ratings pipeline DAG.

Identical pipeline logic; separate dag_id so integration test runs are
isolated in Airflow history and cleanup never touches production DAG runs.

Triggered by the integration test suite with conf={"conn_id": "postgres_corporate_test"},
which routes all DB writes to the corporate_test schema.
"""

from corporate_ratings_dag import build_dag

dag = build_dag("corporate_ratings_pipeline_integration", extra_tags=["integration-test"])
