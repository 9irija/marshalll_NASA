# Marswalk Mission Planner: Space Apps 2026 submission

Challenge: **Interplanetary Survival Guide: Martian Map**

- Demo (7 slides, PDF): [`Marswalk_demo.pdf`](Marswalk_demo.pdf)
  Public link once pushed: https://github.com/9irija/marshalll_NASA/blob/main/submission/Marswalk_demo.pdf
- Code: https://github.com/9irija/marshalll_NASA
- Technical overview: [`../docs/TECHNICAL.md`](../docs/TECHNICAL.md)

---

## Summary (182 words)

Marswalk Mission Planner is a layered 3D map of Jezero crater, the Perseverance landing site, built for the first
astronauts who will walk there. It doesn't just display NASA data: it computes on it to answer the crew's real
question, "Can I get there, do the science, and get home alive?" It combines eight NASA and USGS datasets: HiRISE
terrain and imagery, CRISM minerals, THEMIS thermal, the USGS geologic map, MEDA weather, MSL RAD radiation, DONKI
space weather and Perseverance's own traverse and photos. With them it plans routes priced in kilograms of oxygen and
watt-hours of battery. It shows the area the astronaut can still return from shrinking as the EVA clock runs. It flags
radio dead zones and distance from shelter for solar storms, and it replans live when a dust storm, suit leak or
solar particle alert hits. A machine-learning search finds more ground like the best science site, and a helmet HUD
guides the walk. Every safety number traces to NASA data and to tested code, and our routes match Perseverance's real
drive to within about 100 m.

---

## Project details

**What it does and how it works.** We picked a real site, the western delta and crater floor of Jezero, and a science
goal: sampling the delta mudstones where Perseverance found organic signatures. A Python pipeline downloads the NASA
products and reprojects them with GDAL onto one 2 m grid, about 3 million cells.
- **Routes.** Every step on the HiRISE terrain is priced in time, oxygen and battery, using a published model of
  walking energy on slopes, scaled for Mars gravity and a pressurised suit. A fast graph search (numba) returns the
  safest, fastest and most-science routes.
- **Return envelope.** A reverse search from the habitat gives every cell a "last safe moment". The safe area is drawn
  on the GPU and shrinks as the EVA clock runs. The point of no return is pinned on the route.
- **Safety layers.**
  - A line-of-sight model (with Mars curvature) finds radio dead zones.
  - The MSL RAD surface dose and NASA DONKI space weather give the radiation exposure.
  - Each route reports the worst-case time to shelter if a solar particle alert arrives.
  - A rover mode follows the Apollo "walkback" rule: never drive farther than you could walk home.
- **Machine learning.** It turns minerals, temperature, brightness and terrain into a 10-feature embedding. Click a
  site and it returns the most similar ground the crew can reach. It was validated against the USGS geologic map,
  which it never saw: 1.7 to 3.9 times better than chance.
- **In the field.** A helmet HUD shows O2, power, the next stop, the return margin and comms status. Perseverance's own
  photos show what each stop looks like. An AI Flight Controller (Claude) plans in plain language, but every number it
  says is checked by code against the planner's output.

**Benefits and intended impact.** Today's Mars maps (Mars Trek, USGS) are regional. Ours works at the scale of a walk
and produces a decision rather than a picture: go, go by rover, or don't go, and why. For example, the 4-hour walk to
Wildcat Ridge has radio contact on only 14% of the route and is up to 67 minutes from shelter. The same trip by rover
takes 70 minutes and still meets the walkback rule. Mission planners can test assumptions, which are all editable and
sourced. The same pipeline works for any site with a HiRISE terrain model.

**Tools.**
- Python: GDAL/rasterio, pyogrio, numpy, scipy, numba, scikit-learn, FastAPI.
- TypeScript, Vite, CesiumJS (3D on a Mars-sized globe), uPlot.
- The Anthropic Claude API with tool use, and Playwright for visual tests.
- No special hardware: everything runs on a laptop.

**Creativity.**
- Pricing a map in oxygen instead of distance.
- A return envelope animated by changing one GPU parameter per frame.
- An ML model that proposes science sites while physics decides whether they are safe.
- A helmet HUD built from the same plan.
- Checking our own routes against where Perseverance actually drove.

**What we considered.**
- **Astronaut safety first.** Reserves, the walkback rule, comms, radiation, shelter time.
- **Honesty about data.** Nothing is invented. Proxies and gaps are listed, and every layer names its NASA product ID.
- **AI safety.** The language model is never allowed to produce a safety-critical number.
- **Validation.** 47 automated tests, fixed route cases, a comparison with the rover's real drive (106 m mean
  deviation), and the ML checked against an independent geologic map.
- **Usability.** One 3D view, colour-blind-checked palette, a printable Apollo-style cuff checklist, and a mobile
  layout.

---

## Data sources (all public)
NASA PDS (HiRISE DTM `DTEEC_002387_1985_003798_1985_A01`, CRISM MTRDR `FRT000047A3` / `FRT00005C5E`), NASA Mars Trek
(HiRISE 25 cm, CTX, Viking mosaics), USGS SIM 3464 geologic map with THEMIS IR mosaics (Sun & Stack 2020), Mars 2020
MMGIS traverse and waypoints, Mars 2020 MEDA weather and raw images, MSL RAD (Hassler et al. 2014), NASA CCMC DONKI.
Images: NASA/JPL-Caltech/University of Arizona.

The slide deck is `deck.html`, rendered with `node web/scripts/deck-pdf.mjs`.
