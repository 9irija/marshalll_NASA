PY ?= .venv/Scripts/python
ifeq ($(OS),)
PY = .venv/bin/python
endif
export PYTHONUTF8 = 1

.PHONY: setup data pipeline corpus demo test check-route evals dev api web build screenshot lint

setup:            ## create venv, install Python + web deps
	python -m venv .venv && $(PY) -m pip install -r requirements-dev.txt
	cd web && npm install

data:             ## download raw NASA products (~700 MB)
	$(PY) -m pipeline.download

pipeline: data    ## reproject, derive layers, write COGs + web assets
	$(PY) -m pipeline.preprocess
	$(PY) -m pipeline.context
	$(PY) -m pipeline.ml_train
	$(PY) -m pipeline.pov

corpus:           ## download + chunk the Flight Controller document corpus
	$(PY) -m pipeline.build_corpus

demo:             ## precompute DEMO_MODE / static fallback responses and copy to the web app
	$(PY) -m scripts.precompute_demo
	cd web && npm run sync-data

test:             ## unit + integration tests
	$(PY) -m pytest -q

check-route:      ## fixed planner cases + Perseverance comparison
	$(PY) -m scripts.check_routes

evals:            ## Flight Controller evals (live if ANTHROPIC_API_KEY set)
	$(PY) -m evals.run_evals

lint:
	$(PY) -m ruff check .
	cd web && npm run typecheck && npm run lint

api:
	$(PY) -m uvicorn api.main:app --reload --port 8000

web:
	cd web && npm run dev

dev:              ## API + web together
	$(MAKE) -j2 api web

build:
	cd web && npm run build

screenshot:
	cd web && node scripts/screenshot.mjs http://localhost:5173/ ../docs/screenshot.png 30000
