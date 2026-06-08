.PHONY: up down test test-unit test-integration coverage

# Development: tear down, rebuild, start fresh, and wait until all services are healthy.
up:
	docker compose down -v --remove-orphans
	docker compose up -d --build --remove-orphans --wait

# Stop and remove all containers and volumes.
down:
	docker compose down -v --remove-orphans

# Run all tests (unit + integration). Starts all required services automatically.
test:
	docker compose --profile all-tests run --rm all-tests

# Run unit tests only (no stack required).
test-unit:
	docker compose --profile test run --rm tests

# Run integration tests only. Starts all required services automatically.
test-integration:
	docker compose --profile integration-test run --rm integration-tests

# Run unit tests with coverage. Prints term-missing report and writes HTML to coverage_html/.
coverage:
	docker compose --profile test run --rm tests \
		python -m pytest tests/unit \
			--cov=corporate_pipeline \
			--cov=api \
			--cov-report=term-missing \
			--cov-report=html:coverage_html \
			-q
