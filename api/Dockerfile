FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN pip install --no-cache-dir \
    "fastapi==0.111.1" \
    "uvicorn[standard]==0.30.3" \
    "psycopg2-binary==2.9.9" \
    "pydantic==2.7.4"

COPY . ./api/

ENV PYTHONPATH=/app

EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
