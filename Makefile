.PHONY: lint format typecheck check test clean

lint:
	uv run ruff check src/haven/

format:
	uv run ruff format src/haven/

typecheck:
	uv run mypy src/haven/

test:
	uv run pytest tests/ -q

cov:
	uv run pytest tests/ --cov=haven --cov-report=term -q

check: lint typecheck test
	@echo "All checks passed."

clean:
	@echo "Cleaning..."
	rm -rf .mypy_cache .ruff_cache .pytest_cache htmlcov
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
