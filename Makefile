.PHONY: sync test lint typecheck check format format-check js-check synth deploy clean

sync:
	uv sync --all-groups

test:
	uv run --locked python -m pytest

lint:
	uv run --locked ruff check .

typecheck:
	uv run --locked pyright

check: lint format-check typecheck js-check test

format-check:
	uv run --locked ruff format --check .

js-check:
	node --check frontend/app.js
	node --check frontend/demo.js

format:
	uv run --locked ruff format .
	uv run --locked ruff check --fix .

synth:
	uv run --locked cdk synth

deploy:
	./scripts/deploy.sh

clean:
	rm -rf .pytest_cache .ruff_cache cdk.out cdk-outputs.json
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
