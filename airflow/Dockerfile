# =============================================================================
# airflow/Dockerfile
# Custom Airflow image for the corporate ratings pipeline.
# Adds: pandas, openpyxl, psycopg2-binary, requests, httpx, pytest
# =============================================================================

FROM apache/airflow:2.9.3

USER airflow

RUN pip install --no-cache-dir \
    "pandas==2.2.2" \
    "openpyxl==3.1.5" \
    "apache-airflow-providers-postgres==5.11.1" \
    "psycopg2-binary==2.9.9" \
    "requests==2.32.3" \
    "httpx==0.27.2" \
    "pytest==8.3.4" \
    "pytest-cov==6.0.0" \
    "fastapi==0.111.1" \
    "pydantic==2.7.4"
