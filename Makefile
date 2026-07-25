.PHONY: sync test lint typecheck check format synth deploy clean

sync:
	uv sync --all-groups

test:
	uv run pytest

lint:
	uv run ruff check .

typecheck:
	uv run pyright

check: lint typecheck test

format:
	uv run ruff format .
	uv run ruff check --fix .

synth:
	uv run python app.py

deploy:
	./scripts/deploy.sh

clean:
	rm -rf .pytest_cache .ruff_cache cdk.out cdk-outputs.json
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
