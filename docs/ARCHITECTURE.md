# Architecture

```
NASA archives ──download.py──> data/raw ──preprocess.py──> data/processed ──> planner (numba) ──> FastAPI ──> Cesium web app
 HiRISE PDS, PDS Geosciences       (~700 MB)   COGs, grid.npz,               cost.py, graph.py,       api/         3D Jezero, routes,
 (CRISM), Mars 2020 MMGIS,                     web PNGs, terrain u16,        envelope.py, science.py  service.py   GPU envelope, charts
 MEDA feed, Mars Trek WMTS                     manifest.json                                              │
                                                                                     Flight Controller ───┘ (same service layer as tools)
```

## Data flow
1. `pipeline/download.py` fetches the exact products listed in `data/manifest.json` (URLs found through the
   HiRISE PDS index, the PDS ODE REST API, Mars Trek search and the Mars 2020 MMGIS layer service).
2. `pipeline/preprocess.py` warps every source onto one working grid (local equirectangular, Mars 2000 sphere,
   2 m/px, 1482 x 2024 cells) through windowed `WarpedVRT` reads, derives slope, roughness, the rock-hazard proxy
   and CRISM mineral indices, snaps the habitat to safe ground, picks 40 science hotspots and writes COGs, web
   overlays, terrain height grids and provenance.
3. `planner/` loads `grid.npz` once per process. Searches are numba kernels on an 8-connected grid with
   directional edges.
4. `api/service.py` is the only path to the planner; HTTP routes and Flight Controller tools both call it.
5. `web/` renders Mars on a custom ellipsoid with a heightmap terrain provider built from the DTM, streams
   NASA Trek WMTS imagery, and animates the envelope in a fragment shader.

## Key algorithms
| Piece | Method | Where |
|---|---|---|
| Walking energy | Minetti et al. (2002) polynomial on directional gradient, scaled for Mars gravity, suit mass, suit penalty, terrain roughness | `planner/cost.py`, `graph._edge` |
| Walking speed | Tobler hiking function x suit factor x hazard factor | same |
| O2 / battery | energy / 20.1 kJ per L O2 x 1.429 kg/m3 + resting metabolism x time; suit power x time | same |
| Point to point | A* with admissible octile x min-cost-per-metre heuristic; windowed for short legs | `graph.astar`, `routes.leg` |
| Habitat legs | cached forward + reverse Dijkstra fields from the habitat (predecessor walk) | `planner/fields.py` |
| Cost to home | reverse Dijkstra on physically-directed edges (O2-optimal), tracking time and battery | `envelope.home_field` |
| Return envelope | per-cell deadline T(X) = min over O2, battery, EVA-limit of the last safe time; envelope(t) = {T >= t} | `envelope.deadline_field` |
| Point of no return | first route point whose next step leaves the envelope | `envelope.route_margins` |
| Most science | orienteering: coarse-grid (12 m) cost matrix, greedy value/O2 insertion, 2-opt, exact A* verification with repair | `planner/science.py` |
| Validation | mean point-to-line deviation + discrete Frechet distance vs Perseverance traverse | `planner/validate.py` |
| Number verification | regex extraction of number+unit, unit-aware match within 1 % or the written precision against tool inputs/outputs | `flight_controller/verifier.py` |

## API contract (implemented; OpenAPI at `/docs`)
```
GET  /layers                         -> [{id, name, type: overlay|wmts|terrain|vector, tile_url, bounds?, units, provenance_id}]
GET  /layers/{id}/value?lat&lon      -> {layer, lat, lon, value, units, provenance_id}
GET  /targets                        -> [{id, name, lat, lon, science_tags, note, waypoint_sol, elev_m, science_value}]
POST /route    {start?, end? | targets[], objective: safest|fastest|science|all, round_trip?, hazard?, params?}
               -> {routes: [{id, objective, label, geometry, segments: {dist_m[], elev_m[], slope_deg[], t_s[], o2_kg[],
                   batt_wh[], slack_s[]}, stops[], totals, point_of_no_return?, tightest_point?}], assumptions_version}
POST /envelope {route_id | route, timestep_s, reserve_margin?, polygons?}
               -> {frames: [{t_s, area_km2, polygon?}], point_of_no_return, tightest_point,
                   deadline_field: {url, bounds, t_max_s, encoding}}
POST /replan   {current_position, t_s, remaining: {o2_kg, batt_wh}, hazard?, objective, targets[]?, params?}
               -> same shape as /route; routes[0] is always "abort" (return home); + recommendation
GET  /conditions?sol                 -> {sol, temp_c: {min, max}, pressure_pa, dust_opacity: null, season, sunrise, sunset, source}
POST /validate {start?, end? | sol_from?, sol_to?} -> {planned, actual, mean_deviation_m, frechet_m, note, source}
POST /checklist {route_id}           -> printable HTML (also GET /checklist/{route_id})
POST /assistant {messages[], confirm_constraints?}
               -> {answer, citations[], tool_calls[], routes[], constraints, mode: live|offline,
                   verification: {passed, unverified[], verified_count}}
GET  /health, /assumptions, /manifest, /site
```
Additions to the brief's contract (backwards compatible): `slack_s[]`, `tightest_point`, `deadline_field`,
`area_km2`, `recommendation`, `mode`, `constraints`.

## Envelope rendering choice
The brief allowed mask tiles or polygons. We ship both: polygons per frame for the API and agent, and one
"deadline field" texture per route for the web app. Because envelope(t) = {T(X) >= t}, the browser animates any
t by changing one shader uniform: no per-frame network traffic, perfectly smooth scrubbing. Invalid (impassable)
cells are filled with their nearest valid deadline before upload so GPU filtering creates no false edges.

## Flight Controller
Manual Claude tool-use loop (`anthropic` SDK, model `CLAUDE_MODEL`, default `claude-sonnet-5-5`, server-side refusal
fallback enabled). Tools: `plan_route`, `get_envelope`, `replan`, `get_conditions`, `get_layer_value`,
`search_docs`. After the loop the verifier checks every number; on failure the model gets the list and one
retry; remaining failures are returned and highlighted in the UI. Without an API key an offline agent (regex
constraint parser + templated answer from tool results) keeps the feature demoable, clearly labelled.

Retrieval: BM25 over ~750 chunks (2,000 chars, 300 overlap) in memory. Chosen over FAISS / sqlite-vec with
sentence-transformers because the corpus is small, queries are keyword-heavy, exact lexical scoring is
< 5 ms, and torch has no wheels for Python 3.14 here. `retrieval.search()` is the seam for dense embeddings.

## Demo mode
`scripts/precompute_demo.py` writes route/envelope/validation responses for every named target (4 h EVA) to
`data/processed/demo/` (4 MB). The API serves them when `DEMO_MODE=1`; the web app copies them to
`public/data/demo` and falls back to them automatically when the API is unreachable (badge shown).

## Deploy
- Web: static build (`npm run build`) on Vercel; `web/vercel.json`. Set `VITE_API_URL`.
- API: container (`Dockerfile`, `fly.toml`) with `data/processed` baked in; `WEB_ORIGINS` for CORS.
