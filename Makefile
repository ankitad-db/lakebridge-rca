.PHONY: help install test lint format sync check-sync validate

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install:  ## Install the engine with dev + optional extras (editable)
	pip install -e ".[dev,code,databricks]"

test:  ## Run the deterministic unit test suite (no workspace needed)
	pytest

lint:  ## Lint with ruff
	ruff check .

format:  ## Auto-format / fix imports with ruff
	ruff check . --fix
	ruff format .

sync:  ## Vendor rca_engine/ into the skill folder (local only, no workspace import)
	rm -rf skill/rca-recon/rca_engine
	rsync -a --exclude '__pycache__' --exclude '*.pyc' rca_engine/ skill/rca-recon/rca_engine/
	@echo "Vendored rca_engine -> skill/rca-recon/rca_engine"

check-sync:  ## Fail if the vendored skill engine is out of sync with rca_engine/
	@diff -rq --exclude='__pycache__' rca_engine skill/rca-recon/rca_engine \
		&& echo "Vendored engine is in sync." \
		|| (echo "Out of sync — run 'make sync'." && exit 1)

validate:  ## Run the integration harness vs the oracle (needs RECON_ID + WAREHOUSE_ID)
	python scripts/validate_scenarios.py --recon-id $(RECON_ID) --warehouse-id $(WAREHOUSE_ID)
