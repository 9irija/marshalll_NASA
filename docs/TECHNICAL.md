# Marswalk Mission Planner: technical overview

## The problem, restated
The challenge asks for a layered, integrated view of a Mars location that helps a human explorer plan and carry out
a Marswalk while doing science. Layers alone do not answer the astronaut's real question: **can I get there, do the
science, and get home alive?** Answering it needs what the layers do not give directly: what a route costs in life
support, how much margin is left at every moment, whether the crew can still talk to the habitat and reach shelter,
and what to do when conditions change. Marswalk computes those from NASA data, on real terrain, in one 3D view.

## What we built
| Capability | How it works | Where |
|---|---|---|
| 3D Jezero site | HiRISE DTM as Cesium terrain on a Mars-sized sphere; Trek HiRISE 25 cm / CTX / Viking imagery; 11 analysis layers | `web/src/mars.ts` |
| Consumables cost | Every 2 m step costs time, O2 (kg) and battery (Wh) from Minetti walking energy on the directional gradient | `planner/cost.py` |
| Three Pareto routes | Safest, fastest, most science (orienteering over CRISM hotspots) | `planner/science.py` |
| Return envelope + point of no return | Per-cell last safe moment from reverse Dijkstra; animated on the GPU | `planner/envelope.py` |
| Comms dead zones | Viewshed from the habitat mast over the DTM with Mars curvature; dead stretches marked on route, timeline and HUD | `pipeline/context.py`, `planner/awareness.py` |
| Radiation + space weather | Cosmic-ray dose from MSL RAD; live NASA DONKI CME arrivals at Mars; worst-case time to shelter for a solar particle event; "shelter now" replan | `api/spaceweather.py`, `awareness.py` |
| Geology underfoot | USGS SIM 3464 geologic map (Sun & Stack 2020) rasterised; units crossed per route | `pipeline/context.py` |
| Thermal layer | THEMIS night IR: warm at night = rock, cold = dust/sand | `pipeline/context.py` |
| Rover EVA + walkback | Riding EVA with rover slope limit; the envelope still assumes walking home (Apollo LRV walkback rule) | `planner/routes.py` |
| ML: find similar ground | Multi-scale 30-dimension embedding (10 measurements at 8, 40 and 120 m) + k-means units; nearest-neighbour search screened for reachability; spatial hold-out validation against the USGS map | `pipeline/ml_train.py`, `planner/ml.py` |
| Helmet HUD | First-person view on the route: heading tape, O2/power, next stop distance and ETA, return margin / PNR countdown, comms, geology | `web/src/hud.ts` |
| What you will see | Perseverance Navcam / Mastcam-Z / Hazcam raw frames from the sol the rover stood at each stop | `pipeline/pov.py` |
| Live replanning | Dust storm, suit leak or solar particle alert from the current position and remaining consumables | `api/service.replan` |
| Perseverance check | Same start and end as a real rover drive; mean deviation and Frechet distance | `planner/validate.py` |
| Flight Controller | Claude tool use over all of the above; every number verified in code; documents cited | `flight_controller/` |
| Provenance + cuff checklist | Every layer names product ID and processing; printable wrist card | `data/manifest.json`, `planner/checklist.py` |

## Data: eight NASA / USGS sources, real and traceable
- **Topographic:** HiRISE DTM `DTEEC_002387_1985_003798_1985_A01` (1.01 m), warped to a 2 m grid (1482 x 2024 cells).
- **Optical:** HiRISE orthoimage + Trek HiRISE 25 cm / CTX 6 m mosaics; Perseverance raw images at every stop.
- **Spectral:** CRISM MTRDR `FRT000047A3`, `FRT00005C5E`: olivine, Fe/Mg smectite, carbonate, hydration.
- **Thermal:** Mars Odyssey THEMIS day and night IR, USGS controlled mosaics (100 m).
- **Geologic:** USGS-NASA Planetary Geologic Mapping Program SIM 3464 (6 units in our area).
- **Atmospheric:** MEDA weather feed (temperature, pressure, sunrise/sunset).
- **Radiation / space weather:** MSL RAD surface dose (Hassler et al. 2014); NASA DONKI (CMEs modelled to Mars, SEPs, flares).
- **Ground truth:** 558 Perseverance drive segments and 706 localizations (MMGIS).

DTM vs 252 rover localizations: +3.1 m mean, 3.5 m std (horizontal registration holds). Gaps and proxies: `docs/STUBS.md`.

### How each challenge resource is used
| Resource named by the challenge | Used for |
|---|---|
| JPL Mars Trek | Streamed base imagery (HiRISE 25 cm, CTX 6 m, Viking) under every layer; Trek search found the product IDs |
| USGS-NASA Planetary Geologic Mapping Program | SIM 3464 geologic units: map layer, "geology underfoot" per route, HUD, and the independent check of the ML model |
| Curiosity route-map example | Inspiration for annotated routes with stops; our routes carry named stops, times and leave-by marks |
| NASA Worldview | Earth-only (no Mars layers), so not applicable; its role (current conditions) is filled by MEDA weather and DONKI space weather |
| Perseverance raw images | "What you will see": Navcam / Mastcam-Z / Hazcam frames from the sol the rover stood at each stop, in the panel and the HUD |

### Every downloaded dataset has a job
| Dataset | Planner | Map | ML | Checks |
|---|---|---|---|---|
| HiRISE DTM | cost, slope limit, envelope, comms viewshed | 3D terrain, slope, roughness | slope, roughness, relief | rover elevations (+3.1 m) |
| HiRISE orthoimage | rock-hazard proxy | offline imagery | albedo | |
| CRISM MTRDR x2 | most-science objective, hotspots | 4 mineral layers, science value | 4 mineral features | |
| THEMIS day / night IR | | night thermal layer | 2 thermal features | |
| USGS SIM 3464 | geology per route | geologic units | never used in training | ML validation |
| MEDA weather | | conditions panel, Flight Controller | | |
| MSL RAD + DONKI | dose, SEP shelter rule, replan | space-weather card | | |
| Perseverance traverse + images | targets on real stops | traverse, POV photos | | route validation (106 m) |

Shipped in the USGS package but not used: CTX 20 m DTMs and HRSC (the 1 m HiRISE DTM supersedes them inside the site).

## Why the approach works
1. **The cost unit is the one that kills you.** Routes are ranked by O2 and battery, on directional edges, so uphill out
   is not downhill back.
2. **The envelope turns a plan into a safety picture.** One reverse Dijkstra gives every cell a deadline T(X); the
   envelope at time t is {T >= t}, so the animation is one shader uniform per frame. The point of no return falls out
   of the same field (Wildcat Ridge with a 2 h limit: T+63 min).
3. **It surfaces the risks a map hides.** On the 4 h Wildcat Ridge walk the crew has radio line of sight to the habitat
   on only 14 % of the route (2.4 h out of contact) and is up to 67 min from shelter against a 30 min solar particle
   rule. The same trip by rover takes 70 min and its walkback envelope still holds. Those are decisions a crew makes
   before stepping out.
4. **ML proposes, physics decides.** The similarity search finds ground like a chosen science site in about a second;
   a candidate becomes a plan only after the planner costs it. Each 8 m cell has 10 measurements (CRISM x4, THEMIS
   day/night, HiRISE albedo, slope, roughness, relief) plus their neighbourhood means at 40 m and 120 m, robust-scaled
   and compressed by PCA. The feature set was chosen on the **west half** of the site only and scored on the **east
   half** (spatial hold-out). Against the USGS map, which the model never sees:
   - Similar-ground search: the top 5 % most similar ground is **1.7x to 5.1x** more likely than chance to be in the
     same geologic unit (whole site); **1.48x** on the held-out east half.
   - k-means terrain units: NMI **0.19** (shuffled labels 0.00); **0.16** on the held-out half.
   - Supervised transfer check (gradient boosting, trained on one half, tested on the other): balanced accuracy
     **0.68 vs 0.33 chance** west to east, **0.32 vs 0.20** east to west.
   Agreement is partial by design: the map is 1:75,000 with 100-200 m contact offsets, and the two halves are
   different terrains (delta front vs crater floor).
5. **Replanning uses the same machinery.** Dust (slower, +25 W, more reserve), leak (0.05 kg/h) or a solar particle
   alert (shelter now, with the walk time against the warning rule).
6. **It checks itself against ground truth.** Sols 389 to 415: our walker route is 3.23 km vs the rover's 3.26 km,
   106 m mean deviation, 213 m Frechet.
7. **The language model is never trusted with a safety number.** A verifier matches every number + unit (now including
   radiation dose) against that turn's tool results; failures are rewritten once, then highlighted.

## Performance
| Operation | Time |
|---|---|
| Preprocess all layers from raw products | 50 s, + 15 s context layers, + ~8 min ML training with hold-out checks |
| Full-AOI Dijkstra, 3.0 M cells (numba) | 1.3 s |
| Comms viewshed, 750 k cells at 4 m (numba parallel) | ~5 s, once |
| Three Pareto routes, new target (warm caches) | 1.2 to 2.5 s |
| ML similar-ground search over 187 k cells | ~1 s |

## Verification
- 47 automated tests: cost model, CRS round trip vs PROJ, windowed reads, A* = Dijkstra, envelope monotonicity, PNR,
  viewshed (flat plane, wall shadow, curvature horizon), route context, rover walkback, ML search, SEP shelter
  replan, space-weather parsing, ML validation, every API endpoint, verifier acceptance/rejection (incl. dose).
- 6 fixed route cases plus the Perseverance comparison: all pass. Offline evals 7/7; 5 need a live model.
- Visual checks with Playwright screenshots (map, similar ground, HUD, readout).

## Limits we state up front
- Suit, gravity, rover and reserve parameters are documented approximations, not a certified model.
- Rock hazard is a proxy; THEMIS IR is relative and coarse; comms is direct line of sight only (no relay).
- Radiation uses Gale measurements; DONKI Mars arrivals are model predictions, not measurements at Mars.
- 12 NTRS documents could not be downloaded (HTTP 403). Illumination/shadows not built.

## Stack
Python 3.14, GDAL 3.12 via rasterio and pyogrio, numpy/scipy/numba/shapely, scikit-learn, FastAPI, Anthropic Python
SDK; Vite + TypeScript + CesiumJS 1.123 + uPlot; Playwright. Deployable as a static site plus a container API.
