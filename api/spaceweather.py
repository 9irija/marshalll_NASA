"""Space weather for a Mars EVA from NASA DONKI (Space Weather Database Of Notifications, Knowledge, Information).

What we use
  - WSA-ENLIL simulations: CCMC models every significant CME and lists predicted impacts per body; we keep the ones
    whose impactList names Mars (predicted shock arrival time at Mars).
  - SEP events and solar flares (last 30 days) for context. DONKI SEP detections are Earth/L1 and STEREO based;
    there is no real-time particle monitor at Mars in DONKI, which we state in the response.
Cached in data/raw/donki/ (refresh every 3 h). DEMO_MODE serves the cache only.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import time
import urllib.request

from pipeline.geo import RAW, load_yaml

BASE = "https://api.nasa.gov/DONKI"
CACHE = RAW / "donki"


def _get(kind: str, start: str, end: str, demo: bool) -> list:
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"{kind}.json"
    fresh = path.exists() and time.time() - path.stat().st_mtime < 3 * 3600
    if not demo and not fresh:
        key = os.getenv("NASA_API_KEY", "DEMO_KEY")
        try:
            with urllib.request.urlopen(f"{BASE}/{kind}?startDate={start}&endDate={end}&api_key={key}", timeout=15) as r:
                data = json.loads(r.read().decode("utf-8") or "[]")
            path.write_text(json.dumps({"fetched": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"), "start": start, "end": end,
                                        "data": data}))
        except Exception:
            pass
    if not path.exists():
        return []
    return json.loads(path.read_text())["data"] or []


def cache_info() -> dict:
    p = CACHE / "WSAEnlilSimulations.json"
    if not p.exists():
        return {}
    d = json.loads(p.read_text())
    return {"fetched": d["fetched"], "start": d["start"], "end": d["end"]}


def space_weather(days: int = 30, demo: bool = False) -> dict:
    end = dt.date.today()
    start = end - dt.timedelta(days=days)
    s, e = start.isoformat(), end.isoformat()
    sims = _get("WSAEnlilSimulations", s, e, demo)
    seps = _get("SEP", s, e, demo)
    flares = _get("FLR", s, e, demo)
    mars = {}
    for sim in sims:
        for imp in sim.get("impactList") or []:
            if "mars" in (imp.get("location") or "").lower():
                cme = (sim.get("cmeInputs") or [{}])[0]
                key = cme.get("CMEID") or sim["simulationID"]
                mars[key] = {"cme_id": cme.get("CMEID"), "cme_start": cme.get("cmeStartTime"), "speed_kms": cme.get("speed"),
                             "predicted_arrival_at_mars": imp.get("arrivalTime"), "glancing_blow": imp.get("isGlancingBlow"),
                             "model_run": sim.get("modelCompletionTime"), "link": sim.get("link")}
    impacts = sorted(mars.values(), key=lambda x: x["predicted_arrival_at_mars"] or "")
    now = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%MZ")
    upcoming = [i for i in impacts if (i["predicted_arrival_at_mars"] or "") >= now]
    big = [f for f in flares if (f.get("classType") or "")[:1] in ("M", "X")]
    rad = load_yaml("model.yaml")["radiation"]
    status = "watch" if upcoming else "quiet"
    return {
        "window": {"start": s, "end": e}, "cache": cache_info(), "status": status,
        "mars_cme_impacts": impacts[-8:], "upcoming_mars_impacts": upcoming,
        "sep_events": [{"id": x.get("sepID"), "time": x.get("eventTime"), "instruments": [i.get("displayName") for i in x.get("instruments", [])]}
                       for x in seps][-8:],
        "flares_m_or_x": [{"class": f.get("classType"), "peak": f.get("peakTime"), "region": f.get("activeRegionNum")} for f in big][-8:],
        "baseline": {"gcr_dose_msv_per_day": rad["gcr_dose_equivalent_msv_per_day"]["value"],
                     "source": "MSL RAD, Hassler et al. 2014 (Gale crater surface)"},
        "rule": f"On an SEP alert the crew heads for the habitat; every route reports the worst-case walking time to shelter "
                f"against a {rad['sep_shelter_warning_min']['value']} min planning rule.",
        "limits": "DONKI particle detections are made near Earth (and STEREO-A); Mars impacts are WSA-ENLIL model predictions, "
                  "not measurements at Mars.",
        "source": {"name": "NASA CCMC DONKI", "url": "https://kauai.ccmc.gsfc.nasa.gov/DONKI/", "api": BASE},
    }
