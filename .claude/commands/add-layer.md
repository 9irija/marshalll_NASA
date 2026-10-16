---
description: Add a new NASA data layer end to end (download, reproject, tiles, provenance, UI, test)
argument-hint: <dataset name or product id>
---
Add the dataset "$ARGUMENTS" as a Marswalk layer. Follow the rules in CLAUDE.md (never invent data,
Mars 2000 sphere, east-positive longitudes, windowed reads only, ask before downloading > 2 GB total).

1. **Find the product.** Locate the exact product in a NASA archive (PDS node, ODE REST API
   `https://oderest.rsl.wustl.edu/live2/`, Mars Trek search `https://trek.nasa.gov/mars/TrekServices/ws/index/eq/searchItems`).
   Report product ID, URL, size, resolution, acquisition date. If it cannot be downloaded from here,
   stop and tell the user exactly which file to fetch and where to put it (`data/raw/<group>/`).
2. **Download.** Add the URL to `FILES` in `pipeline/download.py` and run `python -m pipeline.download`.
3. **Reproject + clip.** Add a function in `pipeline/layers/` that warps the source onto the working grid
   with `pipeline.preprocess.warp_to` (rasterio WarpedVRT, never a full read) using `Grid.from_config()`.
   Respect the source CRS from its label; if the label CRS is wrong, document the override.
4. **COG + web asset.** In `pipeline/preprocess.py`: `write_cog(...)` to `data/processed/cog/<id>.tif`,
   add a ramp in `pipeline/layers/render.py` and write `data/processed/web/<id>.png`; add it to `layers.json`.
5. **Provenance.** Add an entry to `write_manifest()` (mission, instrument, product_id, url, resolution_m,
   acquired, units, processing steps). Every layer must have one.
6. **Register in the web app.** Add `{ id, name, alpha }` to `OVERLAYS` in `web/src/main.ts` and a name in
   `api/service.py:layers()`. If the planner should use it, extend `planner/site.py` and the cost model
   (new parameters go in `config/model.yaml` with a `source`).
7. **Test.** Add a test in `tests/test_geo_and_layers.py` (value range, CRS, coverage of the AOI) and a
   value check through `GET /layers/<id>/value` in `tests/test_api.py`.
8. Run `make pipeline`, `make test`, `make demo`, then screenshot the web app
   (`cd web && node scripts/screenshot.mjs`) and confirm the layer sits on the right terrain.
