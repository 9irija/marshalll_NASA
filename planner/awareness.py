"""Situational context along a route: comms line of sight, geology underfoot, radiation, SEP shelter time.

All values are computed from data layers (pipeline/context.py) and named parameters in config/model.yaml.
"""
from __future__ import annotations

import json
from functools import lru_cache

import numpy as np

from pipeline.geo import PROCESSED, load_yaml
from planner import envelope
from planner.site import Site


@lru_cache(maxsize=1)
def layers() -> dict:
    c = np.load(PROCESSED / "context.npz")
    legend = json.loads((PROCESSED / "geology_legend.json").read_text(encoding="utf-8"))
    return {"geo_unit": c["geo_unit"], "comms": c["comms"], "night_ir": c["night_ir"], "legend": {u["id"]: u for u in legend}}


def available() -> bool:
    return (PROCESSED / "context.npz").exists()


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """[start, end) index runs where mask is True."""
    d = np.diff(np.concatenate([[0], mask.astype(np.int8), [0]]))
    return list(zip(np.nonzero(d == 1)[0], np.nonzero(d == -1)[0]))


def geology_at(r: int, c: int) -> dict | None:
    L = layers()
    u = int(L["geo_unit"][r, c])
    if u < 0:
        return None
    g = L["legend"][u]
    return {"symbol": g["symbol"], "name": g["name"]}


def route_context(site: Site, rows: np.ndarray, cols: np.ndarray, seg: dict, p, mode: str = "walk",
                  stop_index: list[int] | None = None) -> dict:
    """Comms dead zones, geologic units crossed, GCR dose and SEP time-to-shelter for a cell path."""
    if not available():
        return {}
    m = load_yaml("model.yaml")
    L = layers()
    t = seg["t_s"]
    dist = seg["dist_m"]
    los = L["comms"][rows, cols].astype(bool)
    dead = []
    for a, b in _runs(~los):
        b1 = min(b, len(t) - 1)
        if t[b1] - t[a] < 30:          # blips shorter than 30 s are within the radio's buffering
            continue
        lon, lat = site.grid.rc_to_lonlat(rows[a], cols[a])
        dead.append({"start_index": int(a), "end_index": int(b1), "t_start_s": round(float(t[a]), 1),
                     "duration_s": round(float(t[b1] - t[a]), 1), "lat": float(lat), "lon": float(lon)})
    los_frac = float(np.mean(los))

    units = L["geo_unit"][rows, cols]
    crossed = []
    start = 0
    for i in range(1, len(units) + 1):
        if i == len(units) or units[i] != units[start]:
            u = int(units[start])
            if u >= 0:
                d = float(dist[min(i, len(dist) - 1)] - dist[start])
                if crossed and crossed[-1]["symbol"] == L["legend"][u]["symbol"]:
                    crossed[-1]["distance_m"] += d
                elif d >= 20:
                    crossed.append({"symbol": L["legend"][u]["symbol"], "name": L["legend"][u]["name"],
                                    "t_start_s": round(float(t[start]), 1), "distance_m": d})
            start = i
    for c in crossed:
        c["distance_m"] = round(c["distance_m"], 1)

    rad = m["radiation"]
    rate = rad["gcr_dose_equivalent_msv_per_day"]["value"] / 86400.0
    duration = float(t[-1] - t[0])
    # time to shelter if an SEP alert arrives at each point: walking time home on the reverse field
    hf = envelope.home_field(site, p, (site.habitat["row"], site.habitat["col"]))
    shelter = hf.t[rows, cols]
    shelter = np.where(np.isfinite(shelter), shelter, np.nan)
    if mode == "rover":
        # riding home on the rover along the rest of the planned (round-trip) route, minus science stops still ahead
        after = np.zeros(len(t))
        for k in stop_index or []:
            after[:k] += p.stop_s
        shelter = np.minimum(shelter, t[-1] - t - after)
    k = int(np.nanargmax(shelter)) if np.isfinite(shelter).any() else 0
    warn_s = rad["sep_shelter_warning_min"]["value"] * 60.0
    lon, lat = site.grid.rc_to_lonlat(rows[k], cols[k])
    beyond = shelter > warn_s
    return {
        "comms": {"line_of_sight_fraction": round(los_frac, 4), "dead_zones": dead,
                  "time_out_of_contact_s": round(float(sum(z["duration_s"] for z in dead)), 1),
                  "longest_dead_zone_s": round(float(max((z["duration_s"] for z in dead), default=0.0)), 1),
                  "habitat_antenna_m": m["comms"]["habitat_antenna_m"]["value"], "suit_antenna_m": m["comms"]["suit_antenna_m"]["value"]},
        "geology": crossed,
        "radiation": {"gcr_dose_msv": round(rate * duration, 4), "dose_rate_msv_per_day": rad["gcr_dose_equivalent_msv_per_day"]["value"],
                      "career_limit_msv": rad["career_limit_msv"]["value"],
                      "career_fraction": round(rate * duration / rad["career_limit_msv"]["value"], 6),
                      "max_time_to_shelter_s": round(float(shelter[k]), 1), "max_shelter_lat": float(lat), "max_shelter_lon": float(lon),
                      "sep_warning_s": warn_s, "shelter_mode": "rover drive home" if mode == "rover" else "walk home",
                      "sep_shelter_ok": bool(not beyond.any()),
                      "time_beyond_shelter_s": round(float(np.sum(np.diff(t, prepend=t[0])[beyond])), 1)},
    }
