# TAPAK: common tasks. Everything runs offline after `make setup`.
PY ?= .venv/bin/python
TAPAK ?= .venv/bin/tapak
PHOTO_DATA ?= out/photos
PHOTO_SET ?= samples/photos
PHOTO_SET_CETAK ?= samples/photos-cetak
BENCH_JSON ?= docs/results/bench_photos.json
BENCH_CHECK = out/bench-check
# Research seed of the benchmark issuance: the code secret and the copy ids are derived from
# it (tapak issue --benih-riset), so make photos, photos-cetak and bench reproduce
# docs/results/bench_photos.json byte for byte. The seed is public: research only.
BENIH_RISET = 2026
# Single-threaded math and OCR for the benchmark: results do not depend on thread scheduling.
ONE_THREAD = OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 OMP_THREAD_LIMIT=1
ISSUED_COPIES = "$$(ls -d $(PHOTO_DATA)/data/dokumen/*/salinan | head -1)"

.PHONY: setup samples samples-pindaian test test-fast simulate table photos photos-cetak photos-issued bench bench-check demo web verify docker docker-cek figures clean

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

photos-issued:    ## the issuance behind both photo sets: 20 copies, no registry, secret and copy ids from BENIH_RISET
	@if [ -d $(PHOTO_DATA)/data/dokumen ] && \
		[ "$$(head -n1 $(PHOTO_DATA)/keys/code_secret.riset 2>/dev/null)" != "$(BENIH_RISET)" ]; then \
		echo "$(PHOTO_DATA) memuat penerbitan lain (bukan benih riset $(BENIH_RISET)); hapus dulu: rm -rf $(PHOTO_DATA)" >&2; \
		exit 2; fi
	@test -d $(PHOTO_DATA)/data/dokumen || { rm -rf $(PHOTO_SET) $(PHOTO_SET_CETAK) && \
		$(ONE_THREAD) $(TAPAK) --data $(PHOTO_DATA)/data --keys $(PHOTO_DATA)/keys \
		issue samples/nota_dinas.pdf samples/recipients.csv --no-registry --canary-domain "" --workers 3 \
		--benih-riset $(BENIH_RISET); }

photos: photos-issued  ## synthetic photo and screenshot degradation set in samples/photos
	$(ONE_THREAD) $(PY) -m tapak.photos --issued $(ISSUED_COPIES) \
		--out $(PHOTO_SET) --seqs 13,7,1,20 --per-copy 2 --seed 2026

photos-cetak: photos-issued  ## phone photos of printed copies (simulated laser), pages 1 and 2, in samples/photos-cetak
	$(ONE_THREAD) $(PY) -m tapak.photos --issued $(ISSUED_COPIES) \
		--out $(PHOTO_SET_CETAK) --seqs 13,7,1,20 --angles 10,30 --per-copy 1 --all-pages \
		--no-screenshots --cetak laser --seed 2026

demo:             ## the 90-second scenario, non-interactive
	$(TAPAK) demo --workdir out/demo

web:              ## web UI on http://127.0.0.1:8000 (data in ./data, keys in ./keys)
	$(TAPAK) web --host 127.0.0.1 --port 8000

verify:           ## verify ./data/registry.db with the public key only
	.venv/bin/tapak-verify-registry data/registry.db --public-key keys/registry_signing.pub

docker:           ## build and start app + canary-dns
	docker compose up --build -d

docker-cek:       ## image end to end on its own tag, project and free ports (8797, 15353); removes only what it made
	$(PY) scripts/cek_docker.py

figures:          ## README figures in docs/img (needs: uv pip install -e ".[figures]")
	$(PY) docs/figures/fig_alur.py
	$(PY) docs/figures/fig_kanal.py
	$(PY) docs/figures/fig_hasil.py

clean:
	rm -rf out samples/photos samples/photos-cetak .pytest_cache

bench:            ## trace every image of the photo sets (make photos, optionally make photos-cetak); prints are reported separately
	$(ONE_THREAD) $(PY) -m tapak.benchmark --photos $(PHOTO_SET) --cetak $(PHOTO_SET_CETAK) \
		--data $(PHOTO_DATA)/data --keys $(PHOTO_DATA)/keys --json $(BENCH_JSON)

bench-check:      ## photos, photos-cetak and bench from scratch in out/bench-check; must equal docs/results/bench_photos.json byte for byte
	rm -rf $(BENCH_CHECK)
	$(MAKE) --no-print-directory photos photos-cetak bench PHOTO_DATA=$(BENCH_CHECK) \
		PHOTO_SET=$(BENCH_CHECK)/photos PHOTO_SET_CETAK=$(BENCH_CHECK)/photos-cetak \
		BENCH_JSON=$(BENCH_CHECK)/bench_photos.json
	cmp $(BENCH_CHECK)/bench_photos.json docs/results/bench_photos.json
	@echo "bench_photos.json terulang persis, byte demi byte"
