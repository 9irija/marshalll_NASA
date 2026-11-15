# Marswalk Mission Planner

**Can I get there, do the science, and get home alive?** A 3D EVA planner for Jezero crater, Mars, built for the
2026 NASA Space Apps challenge *Interplanetary Survival Guide: Martian Map*. Most entries put NASA layers on a globe.
Marswalk computes on them: it turns HiRISE terrain and CRISM mineralogy into routes costed in kilograms of oxygen and
watt-hours, shows the region the astronaut can still return from shrinking as the EVA clock runs, and replans live
when a dust storm hits.

![Return envelope closing on the habitat near the end of a 4 h EVA](docs/screenshot-envelope.png)

**Live demo:** https://9irija.github.io/marshalll_NASA/ (precomputed plans for all five targets; run `make dev` for live planning)

## What it does
- **Layered 3D site view.** HiRISE DTM terrain under NASA Trek HiRISE 25 cm / CTX / Viking imagery, with toggleable
  slope, rock-hazard, science value and four CRISM mineral layers.
- **Consumables cost model.** Minetti walking energy on the directional gradient, scaled for Mars and a pressurised
  suit; every route reports O2 (kg), battery (Wh), time and slope along its length.
- **Return envelope + point of no return.** Per-cell "last safe moment" from reverse Dijkstra; the envelope is
  animated on the GPU and the point where return becomes impossible is pinned on the route.
- **Pareto routes.** Safest, fastest and most-science (orienteering over CRISM hotspots) between habitat and target.
- **Provenance.** Every layer names mission, instrument, product ID, resolution and date; every assumption has a source.
- **Live replanning.** Inject a dust storm or suit leak mid-EVA: abort route home + continue option + recommendation.
- **Perseverance validation.** Our walker route vs the rover's real drive (sols 389 to 415): 106 m mean deviation.
- **Flight Controller.** Plain-language planning with Claude tool use; every number is verified against tool output
  in code and every claim from a document is cited.
- **Cuff checklist.** Printable Apollo-style wrist card per route.
- **Comms dead zones.** Radio line of sight to the habitat mast over the DTM (Mars curvature included), marked on the
  route, the timeline and the HUD.
- **Radiation and space weather.** Cosmic-ray dose per EVA (MSL RAD), live NASA DONKI CME arrivals at Mars, worst-case
  time to shelter for a solar particle event, and a "shelter now" replan.
- **Geology and thermal.** USGS SIM 3464 geologic units underfoot; THEMIS night IR (rock vs dust).
- **Rover EVAs with the walkback rule.** Ride out, but the return envelope assumes walking home if the rover fails.
- **ML: find similar ground.** Pick a science site; a learned embedding of minerals, thermal, brightness and terrain
  finds the most similar reachable ground. Validated against the USGS map it never sees; the planner verifies every
  candidate before any number is shown.
- **Mission map.** A printable annotated route sheet in the style of NASA's Curiosity route maps.
- **Helmet HUD.** First-person view along the route with O2, power, next stop, return margin, comms and geology.
- **What you will see.** Perseverance raw images from the sol the rover stood at each stop.

## Data (all public NASA products)
| Layer | Product |
|---|---|
| Terrain, slope, roughness | MRO HiRISE DTM `DTEEC_002387_1985_003798_1985_A01` (1.01 m) |
| Orthoimage, texture | MRO HiRISE `PSP_002387_1985_RED_C_01_ORTHO` |
| Base imagery | NASA Mars Trek WMTS: Jezero HiRISE 25 cm and CTX 6 m controlled mosaics, Viking MDIM 2.1 |
| Minerals / science | MRO CRISM MTRDR summary products `FRT000047A3`, `FRT00005C5E` (OLINDEX3, D2300, MIN2295_2480, BD1900_2) |
| Rover traverse, targets | Mars 2020 MMGIS `M20_traverse.json`, `M20_waypoints.json` |
| Weather | Mars 2020 MEDA public weather feed |
| Geology | USGS-NASA Planetary Geologic Mapping Program SIM 3464 (Sun & Stack 2020) |
| Thermal | Mars Odyssey THEMIS day / night IR, USGS controlled mosaics |
| Radiation, space weather | MSL RAD surface dose (Hassler et al. 2014); NASA CCMC DONKI |
| Point-of-view images | Mars 2020 raw images (Navcam, Mastcam-Z, Hazcam) |
Full provenance: `data/manifest.json` and the in-app "Data sources" drawer. Gaps and proxies: `docs/STUBS.md`.

## Run it
```bash
make setup        # Python venv + web deps (Python 3.11+, Node 20+)
make pipeline     # downloads ~1 GB of NASA/USGS data, builds layers, trains the ML model (~2 min)
make corpus demo  # Flight Controller corpus; precomputed demo results
make dev          # API http://localhost:8000 (docs at /docs), web http://localhost:5173
make test check-route evals
```
The Flight Controller works with two language-model providers, and the same planner tools and number verifier
apply to both:
- **Claude (default):** set `ANTHROPIC_API_KEY` (optionally `CLAUDE_MODEL`, default `claude-sonnet-5-5`).
- **Gemini:** set `LLM_PROVIDER=gemini` and `GEMINI_API_KEY` (a free-tier key from Google AI Studio works; optionally
  `GEMINI_MODEL`, default `gemini-2.5-flash`). No extra package is needed; it calls the Gemini REST API.

Without a key the assistant runs in a labelled offline mode. Keys stay on the server: never put one in the web app,
because a static site exposes everything it ships. The hosted demo (GitHub Pages) has no server, so its chat answers the
suggested questions with answers precomputed by the same planner and verifier. With the API down the web app uses
precomputed demo data.

## Results (this build)
- 52 tests pass (cost model, CRS round-trips, A* = Dijkstra, envelope monotonicity, viewshed, rover walkback, ML search,
  all API endpoints, verifier). 6/6 route cases pass. Offline evals 7/7 (5 need a live model).
- Wildcat Ridge on foot: radio line of sight on 14 % of the route, up to 67 min from shelter; by rover 70 min total.
- ML similar-ground search: 1.7-5.1x more likely than chance to land in the same USGS geologic unit; 1.48x on a
  spatial hold-out half of the site it was not tuned on.
- Full-AOI Dijkstra on 3.0 M cells: 1.3 s. Three Pareto routes for a new target: 1.2 to 2.5 s warm.
- HiRISE DTM vs 252 Perseverance localizations: +3.1 m mean, 3.5 m std.

## Limitations
Suit, gravity and reserve parameters are documented approximations, not a certified suit model. Rock hazard is a
proxy from roughness and image texture. The envelope assumes the planned consumption profile. See
`docs/ASSUMPTIONS.md` and `docs/STUBS.md`.

Docs: [technical overview](docs/TECHNICAL.md) · [architecture & API](docs/ARCHITECTURE.md) ·
[assumptions](docs/ASSUMPTIONS.md) · [demo script](docs/DEMO_SCRIPT.md) · [design](docs/DESIGN.md)
