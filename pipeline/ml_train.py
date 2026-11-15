"""ML terrain units and the feature space used by "find similar ground".

Run: python -m pipeline.ml_train   (after pipeline.preprocess and pipeline.context)

What it learns, and why it is useful to a crew
  Each 8 m cell gets a feature vector of what the ground is made of and how it behaves: four CRISM mineral
  indices, THEMIS night and day IR (thermal behaviour: rock vs dust), HiRISE albedo, slope, roughness and local
  relief. Two models use it:
    1. k-means terrain units (unsupervised). Scored against the USGS SIM 3464 geologic map, which the model never
       sees, with normalised mutual information and per-unit purity.
    2. Similarity search (planner/ml.py): click a spot (e.g. where Perseverance cored organics-bearing mudstone)
       and get the most similar ground the crew can actually reach. ML proposes; the planner verifies every
       candidate with the full consumables model, so no safety number comes from the model.
  Validation of (2): for query cells drawn from each USGS unit, the fraction of the top-5 % most similar cells
  that fall in the same unit, against the unit's base rate (lift).
"""
from __future__ import annotations

import json
import sys
import time

import numpy as np
from rasterio.enums import Resampling
from scipy import ndimage
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.metrics import normalized_mutual_info_score

from pipeline.geo import PROCESSED, Grid, load_yaml
from pipeline.layers import render
from pipeline.preprocess import DTM, ORTHO, warp_to

FEATURES = [  # (name, group)
    ("olivine", "minerals"), ("fe_mg_smectite", "minerals"), ("carbonate", "minerals"), ("hydration", "minerals"),
    ("night_ir", "thermal"), ("day_ir", "thermal"), ("albedo", "albedo"),
    ("slope", "terrain"), ("roughness", "terrain"), ("relief", "terrain"),
]
UNIT_COLOURS = [(230, 159, 0), (86, 180, 233), (0, 158, 115), (240, 228, 66), (0, 114, 178), (213, 94, 0),
                (204, 121, 167), (200, 200, 200), (120, 90, 200), (90, 200, 160), (160, 100, 60), (250, 250, 250)]


def block_mean(a: np.ndarray, k: int) -> np.ndarray:
    h, w = (a.shape[0] // k) * k, (a.shape[1] // k) * k
    with np.errstate(invalid="ignore"):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            return np.nanmean(a[:h, :w].reshape(h // k, k, w // k, k), axis=(1, 3))


def block_mode(a: np.ndarray, k: int) -> np.ndarray:
    h, w = (a.shape[0] // k) * k, (a.shape[1] // k) * k
    b = a[:h, :w].reshape(h // k, k, w // k, k).transpose(0, 2, 1, 3).reshape(h // k, w // k, k * k)
    vals = np.sort(b, axis=-1)
    return vals[..., (k * k) // 2]          # median class; contacts are rare inside an 8 m block


def build_features(grid: Grid, k: int) -> tuple[np.ndarray, np.ndarray, dict]:
    g = np.load(PROCESSED / "grid.npz")
    c = np.load(PROCESSED / "context.npz")
    elev = g["elev"]
    with np.errstate(invalid="ignore"):
        relief = elev - ndimage.uniform_filter(np.nan_to_num(elev, nan=np.nanmean(elev)), 101)
    ft = grid.transform * grid.transform.scale(k)
    shape = (grid.shape[0] // k, grid.shape[1] // k)
    with __import__("rasterio").open(DTM) as src:
        dtm_crs, dtm_transform = src.crs, src.transform
    albedo = warp_to(ORTHO, grid.crs, ft, shape, Resampling.average, src_crs=dtm_crs, src_transform=dtm_transform, src_nodata=0)
    raw = {
        "olivine": g["min_olivine"], "fe_mg_smectite": g["min_fe_mg_smectite"], "carbonate": g["min_carbonate"],
        "hydration": g["min_hydration"], "night_ir": c["night_ir"], "day_ir": c["day_ir"], "slope": g["slope"],
        "roughness": g["roughness"], "relief": relief,
    }
    stack = {n: block_mean(a.astype(np.float64), k) for n, a in raw.items()}
    stack["albedo"] = albedo[: stack["slope"].shape[0], : stack["slope"].shape[1]]
    X = np.stack([stack[n] for n, _ in FEATURES], -1)
    valid = np.all(np.isfinite(X), -1)
    return X, valid, {"shape": list(X.shape[:2]), "crism_coverage": float(np.isfinite(stack["olivine"]).mean())}


def main() -> int:
    t0 = time.time()
    aoi, model = load_yaml("aoi.yaml"), load_yaml("model.yaml")
    grid = Grid.from_config(aoi)
    m = model["ml"]
    k = int(m["feature_res_m"]["value"] / grid.res_m)
    X, valid, info = build_features(grid, k)
    print(f"  features {X.shape}, valid {valid.mean():.1%} (CRISM coverage {info['crism_coverage']:.1%})")

    # robust standardisation (median / IQR), then group weights so each group counts as one block
    Xv = X[valid]
    med = np.median(Xv, 0)
    iqr = np.subtract(*np.percentile(Xv, [75, 25], 0))
    iqr[iqr == 0] = 1
    gw = m["feature_weights"]["value"]
    groups = [grp for _, grp in FEATURES]
    w = np.array([gw[grp] / np.sqrt(groups.count(grp)) for grp in groups])
    Z = np.clip((X - med) / iqr, -6, 6) * w
    Z[~valid] = np.nan

    rng = np.random.default_rng(0)
    Zv = Z[valid]
    fit_idx = rng.choice(len(Zv), size=min(60000, len(Zv)), replace=False)
    pca = PCA(n_components=6, random_state=0).fit(Zv[fit_idx])
    E = np.full(Z.shape[:2] + (6,), np.nan, np.float32)
    E[valid] = pca.transform(Zv)
    km = KMeans(n_clusters=int(m["n_units"]["value"]), n_init=10, random_state=0).fit(E[valid][fit_idx])
    units = np.full(Z.shape[:2], -1, np.int16)
    units[valid] = km.predict(E[valid])

    # --- validation against the USGS geologic map (never used in training) --------------------------
    geo = block_mode(np.load(PROCESSED / "context.npz")["geo_unit"], k)[: units.shape[0], : units.shape[1]]
    legend = {u["id"]: u for u in json.loads((PROCESSED / "geology_legend.json").read_text())}
    both = valid & (geo >= 0)
    nmi = float(normalized_mutual_info_score(geo[both], units[both]))
    rand = rng.permutation(units[both])
    nmi_null = float(normalized_mutual_info_score(geo[both], rand))
    purity = []
    for u in range(int(m["n_units"]["value"])):
        sel = both & (units == u)
        if sel.sum() == 0:
            continue
        ids, cnt = np.unique(geo[sel], return_counts=True)
        top = ids[np.argmax(cnt)]
        purity.append({"ml_unit": u, "cells": int(sel.sum()), "majority_usgs": legend[int(top)]["name"],
                       "purity": round(float(cnt.max() / cnt.sum()), 3)})

    # similarity-search check: top 5 % most similar cells, same USGS unit vs base rate
    Ev = E[both]
    gv = geo[both]
    lifts = []
    for gid in np.unique(gv):
        base = float((gv == gid).mean())
        if base < 0.02:
            continue
        qs = rng.choice(np.nonzero(gv == gid)[0], size=min(25, int((gv == gid).sum())), replace=False)
        hits = []
        for q in qs:
            d = np.sum((Ev - Ev[q]) ** 2, 1)
            top = np.argpartition(d, int(0.05 * len(d)))[: int(0.05 * len(d))]
            hits.append(float((gv[top] == gid).mean()))
        lifts.append({"usgs_unit": legend[int(gid)]["name"], "base_rate": round(base, 3), "top5pct_same_unit": round(float(np.mean(hits)), 3),
                      "lift": round(float(np.mean(hits)) / base, 2)})
    print(f"  k-means units vs USGS map: NMI {nmi:.3f} (shuffled {nmi_null:.3f})")
    for p in purity:
        print(f"    ML unit {p['ml_unit']}: {p['cells']:6d} cells, {p['purity']:.0%} {p['majority_usgs']}")
    for L in lifts:
        print(f"    similar-ground search in {L['usgs_unit']}: {L['top5pct_same_unit']:.0%} same unit"
              f" vs base {L['base_rate']:.0%} (lift {L['lift']}x)")

    # --- outputs -------------------------------------------------------------------------------------
    np.savez_compressed(PROCESSED / "ml.npz", embedding=E, units=units, valid=valid)
    meta = {"features": [n for n, _ in FEATURES], "groups": groups, "median": med.tolist(), "iqr": iqr.tolist(), "weights": w.tolist(),
            "pca_explained": [round(float(x), 4) for x in pca.explained_variance_ratio_], "factor": k, "feature_res_m": k * grid.res_m,
            "shape": info["shape"], "crism_coverage": info["crism_coverage"], "valid_fraction": float(valid.mean()),
            "validation": {"nmi_vs_usgs": round(nmi, 4), "nmi_shuffled": round(nmi_null, 4), "purity": purity, "similarity_lift": lifts},
            "model": {"scaler": "median/IQR, clipped +-6", "pca_components": 6, "kmeans_k": int(m["n_units"]["value"]), "random_state": 0}}
    (PROCESSED / "ml.json").write_text(json.dumps(meta, indent=1))
    rgba = np.zeros(units.shape + (4,), np.uint8)
    for u in range(int(m["n_units"]["value"])):
        rgba[units == u, :3] = UNIT_COLOURS[u % len(UNIT_COLOURS)]
        rgba[units == u, 3] = 160
    render.write_png(PROCESSED / "web" / "ml_units.png", rgba)
    lay = json.loads((PROCESSED / "web" / "layers.json").read_text())
    lay["layers"]["ml_units"] = "ml_units.png"
    lay["ml_units_legend"] = [{"id": p["ml_unit"], "colour": list(UNIT_COLOURS[p["ml_unit"] % len(UNIT_COLOURS)]),
                               "majority_usgs": p["majority_usgs"], "purity": p["purity"]} for p in purity]
    # the 8 m grid is 4 x 4 blocks of the 2 m grid, trimmed at the south/east edge: give its exact bounds
    b = grid.bounds_deg
    h8, w8 = units.shape
    lay["ml_bounds"] = {"west": b["west"], "north": b["north"], "east": b["west"] + (b["east"] - b["west"]) * (w8 * k) / grid.shape[1],
                        "south": b["north"] - (b["north"] - b["south"]) * (h8 * k) / grid.shape[0]}
    (PROCESSED / "web" / "layers.json").write_text(json.dumps(lay, indent=1))
    print(f"done in {time.time() - t0:.1f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
