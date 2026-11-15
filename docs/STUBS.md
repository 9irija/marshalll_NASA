# Stubs, proxies and gaps

No synthetic data reaches the product. Synthetic arrays exist only in tests (`tests/conftest.py`, named
`SYNTHETIC`). What is not a direct NASA measurement, or is missing, is listed here.

## Derived proxies (real NASA data, our processing)
| Item | What it is | Why |
|---|---|---|
| Rock hazard layer | 0.6 x DTM roughness + 0.4 x HiRISE orthoimage texture, normalised | No rock-abundance product at metre scale was downloadable for the AOI. THEMIS thermal inertia (100 m) and TES (3 km) are far coarser than a walking path. Labelled "proxy" in the UI and manifest. |
| Science value | Relative CRISM index (per-observation percentile normalisation) | Summary parameters are band depths, not abundances. |
| Habitat location | Flattest 2 m cell within 250 m of Perseverance's sol-13 localization | There is no habitat; the snap rule is documented in `aoi_resolved.json`. |
| Comms dead zones | Direct line of sight from an assumed 3 m habitat mast on the HiRISE DTM | No relay orbiter, rover repeater or diffraction modelled; antenna heights are team assumptions. |
| Night thermal layer | USGS controlled THEMIS night IR mosaic, stretched DN | Relative brightness, not calibrated temperature or thermal inertia; 100 m pixels (about 30 x 40 over the AOI). |
| Radiation | MSL RAD surface dose rate measured at Gale (Hassler et al. 2014) applied to Jezero | No Jezero-specific dose measurement exists in the public archive; no suit shielding credited. |
| ML terrain units / similar ground | Unsupervised (k-means) and nearest-neighbour search on real NASA layers | No labelled training data; validated against the USGS map it never sees (NMI 0.19, lift 1.7-5.1x; spatial hold-out NMI 0.16, lift 1.48x). Proposes sites only. |
| Target coordinates | Rover end-of-drive localization on or before each named sampling sol | Sample-site layer on MMGIS returns 403; names come from public NASA mission reporting. |

## Data not obtained
| Missing | Where it lives | Status |
|---|---|---|
| 12 NASA NTRS PDFs for the Flight Controller corpus (Surface EVA Architectural Drivers 20230014957, NASA/TP-2004-212068, EVA Tech Status 20110012989, ICES-2025 traverse model 20250001829, Apollo PLSS performance 19720019460, EVA HW & Ops 20140000238, In-Suit Nutrition 20220019344, HLS 20160006342, Sun et al. 2023 20230016431, Quantin-Nataf 2023 20230016434, MEDA SSR 2021 20210014064) and ALSJ 19790073512 (404) | URLs in `corpus/sources.yaml` | ntrs.nasa.gov returns HTTP 403 to this machine. Download them in a browser into `data/raw/corpus/<id>` (file name = the `id` in sources.yaml, no extension) and rerun `make corpus`. 9 of 21 sources (754 chunks) are indexed now. |
| MEDA dust opacity | MEDA PDS archive (Mars 2020 MEDA bundle) | The public feed has temperature and pressure only; `dust_opacity` is returned as `null`. |
| MEDA history for arbitrary sols | MEDA PDS archive | The public feed serves the latest 7 sols; `/conditions?sol=` returns the nearest available sol and says so. |
| REMS (Curiosity) | PDS Atmospheres node | Not needed for Jezero; not downloaded. |
| Minetti 2002 paper PDF | J Appl Physiol (publisher) | Coefficients used as widely reproduced; confirm against the paper (ASSUMPTIONS.md). |

## Features not built yet (brief tiers 3 / stretch)
- Illumination / SPICE shadows (tier 3). Comms dead zones are built (line of sight only).
- Mars-surface particle measurements: DONKI SEP detections are near Earth; Mars CME arrivals are WSA-ENLIL predictions.
- Flight Controller live mode is implemented but **not run** here: no `ANTHROPIC_API_KEY` in this
  environment. Offline mode and the verifier are tested; 5 of 12 evals need the live model.
- Deploys (Vercel / Fly.io) are configured but not executed: they need your accounts.
