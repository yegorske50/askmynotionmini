.PHONY: help install install-py install-frontend dev dev-api dev-worker ingest seed test test-fast lint typecheck build-frontend clean clean-cache

PY ?= python3
PIP ?= $(PY) -m pip
UV ?= uv
NPM ?= npm

help:
	@echo "AskMyNotion — make targets"
	@echo "  make install         install python deps (and frontend deps + build dist/)"
	@echo "  make install-py      python deps only"
	@echo "  make install-frontend install + build the static frontend"
	@echo "  make dev             start API + worker (foreground)"
	@echo "  make dev-api         start API only"
	@echo "  make dev-worker      start worker only"
	@echo "  make ingest          enqueue an ingest job using current .env"
	@echo "  make seed            load the demo corpus (no real creds needed)"
	@echo "  make test            run pytest (downloads embed model on first run)"
	@echo "  make test-fast       run pytest with mock providers only (no downloads)"
	@echo "  make lint            ruff check"
	@echo "  make typecheck       mypy"
	@echo "  make build-frontend  build web/dist (requires node 20+)"
	@echo "  make clean           remove caches and local data"
	@echo "  make clean-cache     remove only transcript/audio cache"

install: install-py install-frontend

install-py:
	$(PIP) install -e ".[dev]"
	@if [ "$$EMBED_PRELOAD" = "1" ]; then $(PY) -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('intfloat/multilingual-e5-small')"; fi

install-frontend:
	cd web && $(NPM) install
	cd web && $(NPM) run build

dev:
	@echo "Starting API on http://$${HOST:-127.0.0.1}:$${PORT:-8000}"
	@trap 'kill 0' INT TERM EXIT; \
	  $(PY) -m app.worker & \
	  $(PY) -m uvicorn app.main:app --host $${HOST:-127.0.0.1} --port $${PORT:-8000} --reload

dev-api:
	$(PY) -m uvicorn app.main:app --host $${HOST:-127.0.0.1} --port $${PORT:-8000} --reload

dev-worker:
	$(PY) -m app.worker

ingest:
	$(PY) -m app.cli ingest

seed:
	$(PY) -m scripts.seed_demo

test:
	$(PY) -m pytest -q

test-fast:
	TEST_FAST=1 $(PY) -m pytest -q

lint:
	$(PY) -m ruff check app tests scripts

typecheck:
	$(PY) -m mypy app

build-frontend:
	cd web && $(NPM) run build

clean:
	rm -rf data/*.db data/*.db-* .pytest_cache .ruff_cache .mypy_cache web/dist/.vite
	rm -rf web/node_modules

clean-cache:
	rm -rf media_cache audio_cache
