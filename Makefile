# TAPAK: common tasks. Everything runs offline after `make setup`.
PY ?= .venv/bin/python
TAPAK ?= .venv/bin/tapak
PHOTO_DATA ?= out/photos

.PHONY: setup samples samples-pindaian test test-fast simulate table photos bench demo web verify docker figures clean

setup:            ## create the virtualenv and install TAPAK (needs network once)
	uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -e ".[dev]"

samples:          ## regenerate the synthetic sample documents and recipient list
	$(PY) -m tapak.samplegen

samples-pindaian: ## fictional scanned variants of nota_dinas.pdf in samples/generated (not committed)
	$(PY) -m tapak.samplegen --pindaian

test:             ## full test suite (no GPU, no LLM model, no network)
	$(PY) -m pytest -q

test-fast:        ## skip the slow photo tests
	$(PY) -m pytest -q -m "not slow"

simulate:         ## Tardos collusion simulation (acceptance numbers)
	$(TAPAK) simulate --n 100 --c 3 --eps 1e-6 --trials 1000 --json docs/results/simulate_n100_c3.json

table:            ## code length / threshold table
	$(TAPAK) simulate --table

photos:           ## synthetic photo and screenshot degradation set in samples/photos
	@test -d $(PHOTO_DATA)/data/dokumen || $(TAPAK) --data $(PHOTO_DATA)/data --keys $(PHOTO_DATA)/keys \
		issue samples/nota_dinas.pdf samples/recipients.csv --no-registry --canary-domain ""
	$(PY) -m tapak.photos --issued "$$(ls -d $(PHOTO_DATA)/data/dokumen/*/salinan | head -1)" \
		--out samples/photos --seqs 13,7,1,20 --per-copy 2 --seed 2026

demo:             ## the 90-second scenario, non-interactive
	$(TAPAK) demo --workdir out/demo

web:              ## web UI on http://127.0.0.1:8000 (data in ./data, keys in ./keys)
	$(TAPAK) web --host 127.0.0.1 --port 8000

verify:           ## verify ./data/registry.db with the public key only
	.venv/bin/tapak-verify-registry data/registry.db --public-key keys/registry_signing.pub

docker:           ## build and start app + canary-dns
	docker compose up --build -d

figures:          ## README figures in docs/img (needs: uv pip install -e ".[figures]")
	$(PY) docs/figures/fig_alur.py
	$(PY) docs/figures/fig_kanal.py
	$(PY) docs/figures/fig_hasil.py

clean:
	rm -rf out samples/photos .pytest_cache

bench:            ## trace every image of the synthetic photo set (run make photos first)
	$(PY) -m tapak.benchmark --json docs/results/bench_photos.json
