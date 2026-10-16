# Model assumptions

Every value lives in `config/model.yaml` (version `2026.10.16-1`) with a source note and is shown in the
web app's "Model assumptions" drawer. This page explains the physics and how far to trust it.

## Walking energy: Minetti et al. (2002)
Net metabolic cost of walking on a gradient `i` (rise over run):

`C(i) = 280.5 i^5 - 58.7 i^4 - 76.8 i^3 + 51.9 i^2 + 19.6 i + 2.5`  J kg^-1 m^-1

Minetti, Moia, Roi, Susta, Ferretti, "Energy cost of walking and running at extreme uphill and downhill
slopes", J Appl Physiol 93:1039-1046 (2002). Valid for about -0.45 <= i <= 0.45; we clamp outside. The
coefficients match the widely reproduced form of the paper's walking polynomial; the paper itself is
behind a publisher paywall from this environment, so the team should confirm them against the PDF.
Hand-computed checks are in `tests/test_cost.py` (C(0) = 2.5, C(0.1) = 4.899, C(-0.1) = 1.127).

Edges are directional: the gradient is computed from the source to the destination cell, so uphill
and downhill legs cost differently and the cost to return home differs from the cost to go out.

## Mars and suit scaling (approximations)
`J per metre = C(i) x (body 80 kg + suit 70 kg) x gravity factor 0.55 x suit penalty 1.3 x terrain`

- **Gravity factor 0.55.** Reduced-gravity walking studies (e.g. Farley & McMahon 1992) find cost falls
  less than proportionally with gravity. 0.55 at 0.38 g is a team assumption, not a fit.
- **Suit penalty 1.3.** Pressurised-suit joint torque and gait changes. Exposed for sensitivity tests.
- **Terrain** = 1 + 0.6 x normalised roughness (time and energy).
- Sanity check: flat ground gives about 306 W total (walking + 100 W rest), within the range of
  Apollo lunar EVA metabolic rates (the Apollo 12 surface operations plan in our corpus lists predicted
  crew rates per EVA).

## Speed: Tobler (1993)
`v = 6 exp(-3.5 |s + 0.05|) km/h x 0.55 (suit) x hazard multiplier`, floor 0.1 m/s. About 2.8 km/h on flat
ground, peak on a gentle downhill.

## Oxygen and battery
- O2 (kg) = metabolic energy / 20.1 kJ per litre x 1.429 kg/m3 + resting 100 W x time (+ leak, if any).
- Battery (Wh) = (90 W suit + 10 W comms + heater) x time.
- Science stop: 20 min at 200 W metabolic.
- Capacity: 0.60 kg O2, 800 Wh; reserve 15 % of each on arrival home. These are suit-class orders of
  magnitude chosen by the team, not a specific suit.

## Terrain safety
- Hard slope cutoff 25 deg (impassable above). 0.98 % of AOI cells are cut.
- Rock hazard is a **proxy**: 0.6 x normalised DTM roughness + 0.4 x normalised orthoimage texture.
  It is not a rock count; see STUBS.md.
- "Safest" objective = O2 x (1 + 4 x hazard) x (1 + 2 x (slope / cutoff)^2).

## Return envelope rules
A cell X is safe at EVA time t if, with the consumption so far c(t) and the O2-optimal walk home from X:
- O2: c_O2(t) + O2_home(X) <= 0.60 kg - reserve
- battery: c_batt(t) + batt_home(X) <= 800 Wh - reserve
- time: t + time_home(X) <= EVA time limit (be home before the planned EVA ends)

The consumption profile c(t) is the planned route's; after arrival home the crew is assumed at rest.
This is the standard reading ("given what you have used by now, where could you be and still get home")
but it assumes the crew would have consumed the same amount had they been elsewhere.

## Hazards (`hazards:` in model.yaml)
- Dust storm: speed x 0.7, +25 W power, +10 % reserve on both consumables.
- Suit fault: O2 leak 0.05 kg/h, +5 % O2 reserve.

## Science value
CRISM summary parameters OLINDEX3 (olivine), D2300 (Fe/Mg smectite), MIN2295_2480 (Mg carbonate),
BD1900_2 (hydration), per Viviano-Beck et al. (2014). Each observation is normalised to its own AOI
50th-99th percentile (floored at 0, since band depth <= 0 means no absorption), then max-merged, then weighted
(carbonate 1.5, smectite 1.2, olivine 1.0, hydration 1.0). The result is a relative 0..1 index for ranking
stops, not an abundance.
