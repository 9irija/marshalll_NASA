"""Find similar ground (runtime side of pipeline/ml_train.py).

The crew picks a spot; we rank every 8 m cell by distance in the learned embedding (robust-scaled, group-weighted,
PCA) and return the closest matches the crew could plausibly reach. The model only proposes places: reachability
here is a screen (round trip ~ 2 x walking time home), and any candidate the crew chooses is planned and verified by
the full consumables planner before it is shown as feasible.
"""
from __future__ import annotations

import json
from functools import lru_cache

import numpy as np
from scipy import ndimage

from pipeline.geo import PROCESSED
from pipeline.layers.render import write_png
from planner import awareness, envelope
from planner.cost import CostParams
from planner.site import Site


@lru_cache(maxsize=1)
def model() -> dict:
    d = np.load(PROCESSED / "ml.npz")
    meta = json.loads((PROCESSED / "ml.json").read_text(encoding="utf-8"))
    return {"E": d["embedding"].astype(np.float32), "units": d["units"], "valid": d["valid"], "meta": meta}


def available() -> bool:
    return (PROCESSED / "ml.npz").exists()


def similar(site: Site, lat: float, lon: float, p: CostParams, k: int = 6, spacing_m: float = 120.0) -> dict:
    M = model()
    f = M["meta"]["factor"]
    E, valid = M["E"], M["valid"]
    r, c = site.rc(lat, lon)
    r8, c8 = min(r // f, E.shape[0] - 1), min(c // f, E.shape[1] - 1)
    if not valid[r8, c8]:
        raise ValueError("no ML features at that point (outside CRISM coverage or no data)")
    q = E[r8, c8]
    d = np.sqrt(np.nansum((E - q) ** 2, -1))
    d[~valid] = np.inf
    # similarity = 1 - percentile rank of the distance (1.0 = the query itself, 0.95 = top 5 % of the AOI)
    order = np.argsort(d, axis=None)
    rank = np.empty(d.size)
    rank[order] = np.arange(d.size)
    sim = (1.0 - rank / max(valid.sum() - 1, 1)).reshape(d.shape)
    sim[~valid] = 0

    hf = envelope.home_field(site, p, (site.habitat["row"], site.habitat["col"]))
    t_home = hf.t[: E.shape[0] * f, : E.shape[1] * f].reshape(E.shape[0], f, E.shape[1], f).min(axis=(1, 3))
    stop_s = p.stop_s
    round_trip = 2 * t_home + stop_s                                           # screening estimate only
    reachable = np.isfinite(round_trip) & (round_trip <= 0.85 * p.max_duration_s)
    smooth = ndimage.uniform_filter(np.where(valid, sim, 0), 3)
    spacing = max(3, int(spacing_m / M["meta"]["feature_res_m"]))
    peaks = (smooth == ndimage.maximum_filter(smooth, spacing)) & reachable & (smooth > 0.9)
    qmask = np.zeros_like(peaks)
    qr0, qr1, qc0, qc1 = max(0, r8 - spacing), r8 + spacing + 1, max(0, c8 - spacing), c8 + spacing + 1
    qmask[qr0:qr1, qc0:qc1] = True                                             # skip the query's own neighbourhood
    rr, cc = np.nonzero(peaks & ~qmask)
    best = np.argsort(-smooth[rr, cc])[:k]
    out = []
    for i in best:
        R, C = int(rr[i]) * f + f // 2, int(cc[i]) * f + f // 2
        R, C = site.snap_passable(R, C, p.max_slope_deg)
        lon2, lat2 = site.grid.rc_to_lonlat(R, C)
        g = awareness.geology_at(R, C) if awareness.available() else None
        out.append({"lat": float(lat2), "lon": float(lon2), "similarity": round(float(smooth[rr[i], cc[i]]), 3),
                    "est_round_trip_s": round(float(round_trip[rr[i], cc[i]]), 0),
                    "geology": g, "ml_unit": int(M["units"][rr[i], cc[i]]),
                    "science_value": round(float(site.science[R, C]), 3)})
    # explain the match: which feature groups make the query distinctive (largest |z| per group)
    meta = M["meta"]
    explain = _explain(site, r, c, meta)
    png = PROCESSED / "web" / "runtime" / f"similar_{r8}_{c8}.png"
    png.parent.mkdir(exist_ok=True)
    s = np.clip((sim - 0.8) / 0.2, 0, 1)
    rgba = np.zeros(sim.shape + (4,), np.uint8)
    rgba[..., 0] = (255 * s).astype(np.uint8)
    rgba[..., 1] = (200 * s + 30).astype(np.uint8)
    rgba[..., 2] = 60
    rgba[..., 3] = (np.where(sim > 0.8, 60 + 170 * s, 0)).astype(np.uint8)
    write_png(png, rgba)
    b = site.grid.bounds_deg
    h8, w8 = sim.shape
    bounds = {"west": b["west"], "north": b["north"], "east": b["west"] + (b["east"] - b["west"]) * (w8 * f) / site.grid.shape[1],
              "south": b["north"] - (b["north"] - b["south"]) * (h8 * f) / site.grid.shape[0]}
    return {"query": {"lat": lat, "lon": lon, "geology": awareness.geology_at(r, c) if awareness.available() else None,
                      "ml_unit": int(M["units"][r8, c8]), "distinctive": explain},
            "candidates": out, "similarity_map": {"url": f"/static/web/runtime/{png.name}", "bounds": bounds},
            "model": {**meta["model"], "features": meta["features"], "validation": meta["validation"]},
            "note": "ML proposes places that look alike in the data; plan a route to verify consumables before committing."}


def _explain(site: Site, r: int, c: int, meta: dict) -> list[dict]:
    """Features where the query cell stands out from the AOI median (robust z-score)."""
    g = np.load(PROCESSED / "grid.npz")
    ctx = np.load(PROCESSED / "context.npz")
    vals = {"olivine": g["min_olivine"], "fe_mg_smectite": g["min_fe_mg_smectite"], "carbonate": g["min_carbonate"],
            "hydration": g["min_hydration"], "night_ir": ctx["night_ir"], "day_ir": ctx["day_ir"], "slope": g["slope"],
            "roughness": g["roughness"]}
    out = []
    for i, name in enumerate(meta["features"]):
        if name not in vals:
            continue
        a = vals[name][max(0, r - 2):r + 3, max(0, c - 2):c + 3]
        v = float(np.nanmean(a)) if np.isfinite(a).any() else np.nan
        if not np.isfinite(v):
            continue
        z = (v - meta["median"][i]) / meta["iqr"][i]
        out.append({"feature": name, "robust_z": round(z, 2)})
    return sorted(out, key=lambda x: -abs(x["robust_z"]))[:4]
