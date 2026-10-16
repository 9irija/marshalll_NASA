# Marswalk Mission Planner

NASA Space Apps 2026, "Interplanetary Survival Guide: Martian Map". A layered 3D planner for a suited
EVA at Jezero crater that computes on the layers to answer: **can I get there, do the science, and get
home alive?** Site: western delta + Maaz/Seitah floor, inside HiRISE DTM DTEEC_002387_1985_003798_1985_A01.

## Non-negotiable rules
- **The language model never produces a safety-critical number.** O2, battery, distance, time, slope,
  position and weather figures in a Flight Controller answer must come from a tool result (or the tool's
  input constraints) in the same turn. Enforced by `flight_controller/verifier.py`; never loosen it to make
  an eval pass.
- **Never invent data.** If a dataset cannot be downloaded from here, stop and say which file is needed and
  where it lives. Stubs must contain `SYNTHETIC` in the filename, show a red badge in the UI and be listed in
  `docs/STUBS.md`.
- **Every model assumption** is a named parameter with a `source` in `config/model.yaml`; bump `version`
  when a value changes. The UI assumptions drawer renders that file.
- **Never load a full DTM into memory.** Use rasterio windows / `WarpedVRT` at the AOI.
- Ask before: downloading > 2 GB total, adding a paid service, or changing the API contract
  (`docs/ARCHITECTURE.md`).

## Coordinate conventions (checked in tests/test_geo_and_layers.py)
- Mars 2000 IAU sphere, R = 3,396,190 m. Latitude planetocentric. Longitude **east-positive, -180..180**
  (`pipeline.geo.wrap_lon`).
- Working CRS: local equirectangular, `lat_ts` = AOI centre, `lat_0 = 0`, on the 3,396,190 m sphere, 2 m/px
  (`config/aoi.yaml`). It is a regular lon/lat grid, so web overlays map onto `Rectangle.fromDegrees`.
- Source CRSs come from product labels and are reprojected with GDAL (rasterio), never by hand. HiRISE and
  CRISM use local spheres (R = 3,394,839.8 m); geographic lat/lon is shared, so only the projection changes.
- The HiRISE JP2 orthoimage has a malformed GML CRS; it is georeferenced with the DTM label (same grid).
- Elevations are areoid heights (m). In Cesium they sit on the sphere: a constant vertical offset for the
  scene, consistent across terrain, routes and markers.

## Layout
```
config/            model.yaml (every parameter + source), aoi.yaml (bounds, habitat seed, targets)
pipeline/          download.py, preprocess.py, layers/{terrain,science,render}.py, build_corpus.py, geo.py
planner/           cost.py, graph.py (numba A*/Dijkstra), fields.py (cached habitat fields), routes.py,
                   envelope.py, science.py (Pareto + orienteering), validate.py, checklist.py, site.py
api/               main.py (FastAPI), service.py (shared by API + agent), schemas.py, demo.py, routers/
flight_controller/ agent.py (Claude tool loop + offline mode), tools.py, retrieval.py (BM25), verifier.py, prompts/
web/               Vite + TypeScript + CesiumJS app (src/main.ts, mars.ts, envelope.ts, scene.ts, charts.ts, drawers.ts)
corpus/            sources.yaml, chunks/
tests/             unit + API integration, route_cases.yaml
evals/             assistant_prompts.yaml, run_evals.py
scripts/           precompute_demo.py, check_routes.py
docs/              ARCHITECTURE, ASSUMPTIONS, STUBS, DEMO_SCRIPT, DESIGN, TECHNICAL
```

## Commands (Windows: Git Bash; `PYTHONUTF8=1` is set by the Makefile)
- `make setup` venv + npm install
- `make pipeline` download (~700 MB) and build every layer (~1 min)
- `make corpus` Flight Controller documents
- `make demo` precompute demo responses and sync to `web/public/data`
- `make test` pytest (unit + API integration)  ·  `make lint` ruff + tsc + eslint
- `make check-route` / `/check-route` fixed planner cases + Perseverance comparison
- `make evals` / `/eval-assistant` Flight Controller evals (live only with `ANTHROPIC_API_KEY`)
- `make dev` API on :8000 + web on :5173  ·  `cd web && node scripts/screenshot.mjs` visual check

## How to add a layer
Use `/add-layer <dataset>`; the steps are in `.claude/commands/add-layer.md`: find the exact NASA product,
download, warp to the working grid with `warp_to`, write COG + PNG, add a manifest entry, register it in
`web/src/main.ts` and `api/service.py`, add tests, regenerate the demo, screenshot.

## Notes for future sessions
- Performance budget: full-AOI Dijkstra (3 M cells) ~1.3 s warm; Pareto routes for a new target 1-2.5 s once
  `fields.py` and the science matrices are warm (API warm-up thread does this at start).
- NTRS (ntrs.nasa.gov) returns 403 from this machine; corpus PDFs from there must be fetched by hand into
  `data/raw/corpus/<id>` (see docs/STUBS.md).
- Frontend design rules: `.claude/skills/frontend-design/SKILL.md` and `docs/DESIGN.md`.
