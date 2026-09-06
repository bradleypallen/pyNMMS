.PHONY: test lint typecheck check bench bench-quick docs

test:
	pytest -q

lint:
	ruff check src/ tests/ bench/

typecheck:
	mypy src/

check: lint typecheck test

# Full benchmark run; writes a JSON record to bench/results/.
bench:
	python -m bench

# Reduced sizes for a fast sanity run (also writes a record).
bench-quick:
	python -m bench --quick

docs:
	cd docs && mkdocs build
