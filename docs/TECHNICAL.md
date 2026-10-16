# Marswalk Mission Planner: technical overview

## The problem, restated
The challenge asks for a layered, integrated view of a Mars location that helps a human explorer plan and carry out
a Marswalk while doing science. Layers alone do not answer the astronaut's real question: **can I get there, do the
science, and get home alive?** Answering it needs three things the layers do not give directly: what a route costs in
life support, how much margin is left at every moment, and what to do when conditions change. Marswalk computes those
from NASA data, on real terrain, and shows them in one 3D view.

## What we built
| Capability | How it works | Where |
|---|---|---|
| 3D Jezero site | HiRISE DTM as a Cesium terrain on a Mars-sized sphere, NASA Trek HiRISE 25 cm / CTX / Viking imagery, 7 analysis layers | `web/src/mars.ts` |
| Consumables cost | Every 2 m step costs time, O2 (kg) and battery (Wh) from Minetti walking energy on the directional gradient, scaled for Mars | `planner/cost.py`, `graph._edge` |
| Three Pareto routes | Safest (hazard + slope weighted), fastest (time), most science (orienteering over CRISM hotspots) | `planner/science.py` |
| Return envelope | For each cell, the last moment the crew can still get home with reserve; drawn on the GPU as the clock runs | `planner/envelope.py`, `web/src/envelope.ts` |
| Point of no return | First route point whose next step leaves the envelope, pinned on the map and the timeline | `envelope.route_margins` |
| Live replanning | Dust storm / suit leak from the current position and remaining consumables: abort route, continue option, recommendation | `api/service.replan` |
| Perseverance check | Same start and end as a real rover drive; mean deviation and discrete Frechet distance | `planner/validate.py` |
| Flight Controller | Claude tool use over the planner; numbers verified in code; document claims cited | `flight_controller/` |
| Provenance | Mission, instrument, product ID, resolution, date and processing for every layer; source note for every parameter | `data/manifest.json`, `config/model.yaml` |
| Cuff checklist | Printable wrist card: stops, times, O2 and battery at each, leave-by times, abort triggers | `planner/checklist.py` |

## Data: real, exact, traceable
- **Terrain:** HiRISE DTM `DTEEC_002387_1985_003798_1985_A01` (1.01 m/px) covering the western delta and the
  Octavia E. Butler landing site. Reprojected with GDAL onto a 2 m working grid (1482 x 2024 cells, 3.0 x 4.0 km).
- **Minerals:** CRISM MTRDR summary products `FRT000047A3` and `FRT00005C5E`: olivine (OLINDEX3), Fe/Mg smectite (D2300),
  carbonate (MIN2295_2480), hydration (BD1900_2). Result: olivine across the crater floor and carbonate at the delta
  margin, matching published Jezero mineralogy.
- **Rover:** 558 drive segments and 706 localizations from the Mars 2020 MMGIS service; targets are real rover stops
  (Rochette, Seitah, Skinner Ridge, Wildcat Ridge, Three Forks depot).
- **Weather:** MEDA public feed (temperature, pressure, sunrise/sunset).
- **Check on georeferencing:** our DTM elevation at 252 Perseverance localizations differs by +3.1 m mean (3.5 m std),
  the expected offset between an uncontrolled 2007 DTM and controlled rover positions. Horizontal registration holds.

Every URL was discovered from the archive indexes (HiRISE PDS, PDS Geosciences ODE API, Mars Trek search, MMGIS). No
data is invented; proxies and gaps are listed in `docs/STUBS.md`.

## The model in one paragraph
Walking energy per metre is Minetti et al. (2002) `C(i)` on the gradient of each directed grid step, times walker +
suit mass (150 kg), a Mars gravity factor (0.55), a suit penalty (1.3) and a roughness term. Speed is Tobler's hiking
function scaled for a suited walker (2.8 km/h on flat ground). O2 = metabolic energy / 20.1 kJ per litre + 100 W resting
metabolism; battery = 100 W suit load x time. Slopes above 25 deg are impassable. Flat walking comes out near 306 W,
inside the range of Apollo EVA metabolic rates. Every value is a named, sourced parameter in `config/model.yaml`.

## Why the approach works
1. **The cost unit is the one that kills you.** Routes are ranked by O2 and battery, not metres. A short steep route can
   cost more than a long flat one, and uphill out is not downhill back: edges are directional, so the return home is
   costed for the direction you actually walk.
2. **The envelope turns a plan into a safety picture.** A reverse Dijkstra from the habitat gives the O2, battery and
   time needed to get home from every cell. Combined with consumption so far, each cell gets one number, its deadline
   T(X). The envelope at time t is simply {T >= t}. That makes the headline animation exact and cheap: the browser
   changes one shader uniform per frame, with no per-frame computation or download.
3. **The point of no return falls out of the same field.** It is the first route point whose deadline has passed when
   the crew reaches it. Example: Wildcat Ridge with a 2 h EVA limit puts it at T+63 min, on the way out.
4. **Pareto, not a single "best" route.** Safest, fastest and most-science routes expose the trade-off a crew would
   actually discuss. Most-science solves an orienteering problem over 40 CRISM hotspots under the O2, battery and time
   budget, then verifies the tour on the fine grid and drops stops until it fits.
5. **Replanning uses the same machinery.** A hazard changes parameters (dust: slower, +25 W, more reserve; leak:
   0.05 kg/h), and the planner reruns from the current position with what is left. The answer is a decision
   (abort or continue), not a map refresh.
6. **It checks itself against ground truth.** On the sols 389 to 415 drive (3.26 km), our walker route between the same
   points is 3.23 km with 106 m mean deviation and 213 m Frechet distance. On sols 340 to 415 the rover drove 8.6 km
   around the Seitah dunes that a walker crosses in about 2.6 km; the difference is real, and the tool shows it.
7. **The language model is never trusted with a safety number.** The Flight Controller plans through tools; a verifier
   extracts every number + unit from the answer and matches it (unit-aware, 1 % or written precision) against that
   turn's tool inputs and outputs. Failures trigger one rewrite, then are highlighted in red in the UI. It rejects
   invented values and the model's own arithmetic. Document claims must cite a passage retrieved that turn.

## Performance
| Operation | Time |
|---|---|
| Preprocess all layers from raw products | 50 s |
| Full-AOI Dijkstra, 3.0 M cells (numba) | 1.3 s |
| Three Pareto routes, new target (warm caches) | 1.2 to 2.5 s |
| Envelope deadline texture + 49 frame areas (web path) | 1.1 s |
| Same with 49 GeoJSON polygon frames (API / agent path) | 4.0 s |
| Envelope animation in the browser | one uniform update per frame |

Speed comes from numba kernels that release the GIL (objectives run in parallel threads), cached forward and reverse
Dijkstra fields from the habitat (habitat legs become a predecessor walk), windowed A* for short legs, and per-node
caching of the coarse orienteering cost matrix.

## Verification
- 36 automated tests: cost model against hand calculations, slope of a known plane, CRS round trip vs pyproj, windowed
  reads, A* equals Dijkstra, directional edges, envelope monotonic shrinkage, PNR position, every API endpoint on the
  real data, verifier acceptance and rejection cases.
- 6 fixed route cases plus the Perseverance comparison (`make check-route`): all pass, including two that must be
  infeasible.
- Flight Controller evals: 12 prompts (normal plans, impossible requests, abort scenarios, attempts to make the model
  estimate O2). Offline mode 7/7; the 5 prompts that need a live model run when `ANTHROPIC_API_KEY` is set.
- Visual checks with Playwright screenshots at each UI milestone (layers on the right terrain, envelope edge, mobile).

## Interface
One full-bleed 3D view with three quiet panels: plan (destination, EVA limit, conditions, routes, layers), readout
(status, totals, elevation profile, consumables remaining with the reserve line) and the EVA clock (play, scrub, stops,
point of no return, safe-area and margin readouts). Colours were checked for colour-blind separation and contrast.
With the API offline, the app falls back to precomputed results for every named target.

## Limits we state up front
- Suit mass, gravity factor, suit penalty, capacities and reserves are documented approximations, not a certified suit.
- Rock hazard is a proxy from DTM roughness and image texture, not a rock count.
- The envelope assumes the planned consumption profile up to time t.
- 12 NTRS documents could not be downloaded from our environment (HTTP 403); the corpus has 9 sources and 754 passages.
- Not built yet: comms viewshed and illumination/shadow (tier 3).

## Stack
Python 3.14, GDAL 3.12 via rasterio, numpy/scipy/numba/shapely/pyproj, FastAPI, Anthropic Python SDK; Vite + TypeScript
+ CesiumJS 1.123 + uPlot; deployable as a static site (Vercel) plus a container API (Fly.io).
