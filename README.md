# Marswalk Mission Planner

**Can I get there, do the science, and get home alive?** A 3D EVA planner for Jezero crater, Mars, built for the
2026 NASA Space Apps challenge *Interplanetary Survival Guide: Martian Map*. Most entries put NASA layers on a globe.
Marswalk computes on them: it turns HiRISE terrain and CRISM mineralogy into routes costed in kilograms of oxygen and
watt-hours, shows the region the astronaut can still return from shrinking as the EVA clock runs, and replans live
when a dust storm hits.

![Return envelope closing on the habitat near the end of a 4 h EVA](docs/screenshot-envelope.png)

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

## Data (all public NASA products)
| Layer | Product |
|---|---|
| Terrain, slope, roughness | MRO HiRISE DTM `DTEEC_002387_1985_003798_1985_A01` (1.01 m) |
| Orthoimage, texture | MRO HiRISE `PSP_002387_1985_RED_C_01_ORTHO` |
| Base imagery | NASA Mars Trek WMTS: Jezero HiRISE 25 cm and CTX 6 m controlled mosaics, Viking MDIM 2.1 |
| Minerals / science | MRO CRISM MTRDR summary products `FRT000047A3`, `FRT00005C5E` (OLINDEX3, D2300, MIN2295_2480, BD1900_2) |
| Rover traverse, targets | Mars 2020 MMGIS `M20_traverse.json`, `M20_waypoints.json` |
| Weather | Mars 2020 MEDA public weather feed |
Full provenance: `data/manifest.json` and the in-app "Data sources" drawer. Gaps and proxies: `docs/STUBS.md`.

## Run it
```bash
make setup        # Python venv + web deps (Python 3.11+, Node 20+)
make pipeline     # downloads ~700 MB of NASA data, builds layers (~1 min)
make corpus demo  # Flight Controller corpus; precomputed demo results
make dev          # API http://localhost:8000 (docs at /docs), web http://localhost:5173
make test check-route evals
```
Set `ANTHROPIC_API_KEY` (and optionally `CLAUDE_MODEL`, default `claude-sonnet-5-5`) for the live Flight Controller;
without it the assistant runs in a labelled offline mode. With the API down the web app uses precomputed demo data.

## Results (this build)
- 36 tests pass (cost model hand calculations, CRS round-trips, A* = Dijkstra, envelope monotonicity, all API endpoints,
  verifier). 6/6 route cases pass. Offline evals 7/7 (5 need a live model).
- Full-AOI Dijkstra on 3.0 M cells: 1.3 s. Three Pareto routes for a new target: 1.2 to 2.5 s warm.
- HiRISE DTM vs 252 Perseverance localizations: +3.1 m mean, 3.5 m std.

## Limitations
Suit, gravity and reserve parameters are documented approximations, not a certified suit model. Rock hazard is a
proxy from roughness and image texture. The envelope assumes the planned consumption profile. See
`docs/ASSUMPTIONS.md` and `docs/STUBS.md`.

Docs: [technical overview](docs/TECHNICAL.md) · [architecture & API](docs/ARCHITECTURE.md) ·
[assumptions](docs/ASSUMPTIONS.md) · [demo script](docs/DEMO_SCRIPT.md) · [design](docs/DESIGN.md)
