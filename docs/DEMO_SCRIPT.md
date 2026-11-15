# Demo script (4 beats, about 4 minutes)

Before: `make dev` (or open the deployed URL; with the API down the app falls back to demo data).
Let the API log "warm-up done" (about 20 s) so every plan returns in 1-2 s.

## 1. Plan a 4-hour EVA to the hydrated minerals on the delta (60 s)
- Open the app: the camera flies over Jezero's western delta, real HiRISE 25 cm imagery on the HiRISE DTM.
- Toggle **Science value (CRISM)** and **Hydration** to show where the minerals are. Open **Data sources**:
  every layer names its mission, instrument and product ID.
- Destination **Wildcat Ridge**, EVA limit **4 h**, **Plan routes**. Three routes appear:
  Safest 6.51 km / 2:47 h / 0.211 kg O2; Fastest 6.05 km; Most science picks up CRISM hotspots on the way.
- Say: "Cost is in kilograms of oxygen and watt-hours, not metres."

## 2. The shrinking envelope and the point of no return (60 s)
- Press play. The astronaut walks the route; the teal region is everywhere the crew can still get home from
  with reserve. Scrub to the end of the EVA: it closes on the habitat, the lost region turns red.
- Set the limit to **2 h** and plan again: the route is flagged not feasible and a red **point of no return**
  appears at T+1:03 on the way out. "Past this pin you cannot make it back."

## 3. Inject a dust storm and replan (60 s)
- Back to 4 h. Scrub to about T+0:55 (near the delta front), click **Inject dust storm now**.
- The planner replans from that position with the remaining O2 and battery: an abort route home and a
  continue option, with a recommendation. Battery now drains faster (dashed line).
- Open **Ask Flight Controller**: "A dust storm is coming. Can I still make it to Wildcat Ridge in 3 hours?"
  The answer shows the parsed constraints, the numbers (each verified against tool output, green check),
  and a citation to a real NASA document you can click.

## 4. Check against Perseverance (45 s)
- Click **Check against Perseverance**. Dashed white: the rover's real drive, sols 389 to 415 (3.26 km).
  Gold: our route for a walker between the same points (3.23 km). Mean deviation 106 m, Frechet 213 m.
- Close: "Every layer traces to a NASA product, every number traces to a tool call, and the plan holds up
  against where Perseverance actually drove."

## 5. New: comms, radiation, ML and the helmet view (60 s)
- Readout "On this route": radio line of sight on 14 % of the Wildcat walk (purple stretches), 67 min from shelter
  against the 30 min solar particle rule. Switch Travel to **Rover + walkback**: 70 min trip, envelope still assumes a walk home.
- **Find similar ground (ML)** > "Ground like Wildcat Ridge": yellow heat + numbered reachable candidates; the model
  card shows the check against the USGS map. **Plan route** on a candidate: the planner verifies it.
- **Helmet HUD**: walk the route at eye level with O2, power, next stop, return margin and comms on the visor.
- Scroll the readout: "What you will see" shows Perseverance's own photos from that stop.

Backup: **Print cuff checklist** opens the Apollo-style wrist card for the selected route.
