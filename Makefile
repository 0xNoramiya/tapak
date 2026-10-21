PY ?= .venv/bin/python
TAPAK ?= .venv/bin/tapak

.PHONY: setup samples test simulate table

setup:
	uv venv --python 3.12 .venv && uv pip install -e ".[dev]"

samples:
	$(PY) -m tapak.samplegen

test:
	$(PY) -m pytest -q

simulate:
	$(TAPAK) simulate --n 100 --c 3 --eps 1e-6 --trials 1000 --json docs/results/simulate_n100_c3.json

table:
	$(TAPAK) simulate --table
