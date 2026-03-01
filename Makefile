.PHONY: install lint format test contracts check docker-up docker-down help

help:
	@echo "Available targets:"
	@echo "  install      Install package in editable mode with dev extras"
	@echo "  lint         Run ruff linter"
	@echo "  format       Run ruff formatter"
	@echo "  test         Run unit tests"
	@echo "  contracts    Run contract tests and contrib structure check"
	@echo "  check        Run lint + test + contracts"
	@echo "  docker-up    Start local dev stack (docker compose)"
	@echo "  docker-down  Stop local dev stack"

install:
	pip install -e ".[dev]"

lint:
	ruff check src tests

format:
	ruff format src tests

test:
	pytest -q

contracts:
	pytest -q tests/test_contract_evidence_bundle.py tests/test_contract_mcp_tools.py
	python scripts/validate_contrib.py

check: lint test contracts

docker-up:
	docker compose up -d

docker-down:
	docker compose down
