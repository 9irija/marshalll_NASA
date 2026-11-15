"""Context layers on the working grid: geology, thermal, comms line of sight, ML terrain units.

Run: python -m pipeline.context   (after python -m pipeline.preprocess)

Sources
  USGS SIM 3464 (Sun & Stack 2020) geologic map of Jezero crater, file geodatabase, Mars 2000 sphere MTM 77.5E,
  with the USGS THEMIS day / night IR controlled mosaics (100 m) shipped in the same package.

Outputs in data/processed/:
  context.npz            geo_unit (int16, -1 = unmapped), night_ir, day_ir (DN), comms (uint8 0/1) on the 2 m grid
  ml.npz, ml.json        8 m feature stack, ML terrain units, scaler, validation metrics (see pipeline/ml_train.py)
  web/geology.png, thermal_night.png, comms.png, ml_units.png  + entries in web/layers.json and data/manifest.json
"""
from __future__ import annotations

import json
import sys
import time

import numpy as np
import pyogrio.raw
from numba import njit, prange
from rasterio.crs import CRS
from rasterio.enums import Resampling
from rasterio.features import rasterize
from rasterio.warp import transform_bounds, transform_geom
from shapely import from_wkb
from shapely.geometry import mapping

from pipeline.geo import MARS_RADIUS_M, PROCESSED, RAW, ROOT, Grid, load_yaml
from pipeline.layers import render
from pipeline.layers.terrain import normalise
from pipeline.preprocess import warp_to

USGS = RAW / "usgs" / "sim3464_JezeroNili_FINAL"
GDB = USGS / "Geodatabase" / "Nili.gdb"
THEMIS = USGS / "Rasters" / "USGS_THEMIS_IR_controlled_mosaic_oct2018"

# Categorical colours for the geologic units (distinct on grey HiRISE, colour-blind checked in pairs that touch).
UNIT_COLOURS = {
    "Njf": (214, 140, 69), "NHjf1": (102, 178, 255), "NHjf2": (61, 120, 220), "Aeb": (240, 220, 120),
    "su": (170, 170, 170), "Nue": (200, 120, 200), "Nle": (150, 90, 170), "Nrb": (240, 240, 240),
    "cr": (230, 90, 70), "ce": (250, 150, 120), "ci": (120, 70, 50), "Nnp1": (120, 200, 120),
    "Nnp2": (70, 150, 90), "Hnpf": (60, 200, 200),
}


def geology(grid: Grid) -> tuple[np.ndarray, list[dict]]:
    """Rasterise USGS SIM 3464 GeoUnits onto the working grid (polygons reprojected by GDAL/OGR)."""
    info = pyogrio.read_info(GDB, layer="GeoUnits_v1")
    src_crs = CRS.from_wkt(info["crs"]) if info["crs"].lstrip().startswith(("PROJCS", "PROJCRS")) else CRS.from_user_input(info["crs"])
    h, w = grid.shape
    t = grid.transform
    bbox = transform_bounds(grid.crs, src_crs, t.c, t.f + h * t.e, t.c + w * t.a, t.f, densify_pts=21)
    pad = 500.0
    meta, _, geoms, fields = pyogrio.raw.read(GDB, layer="GeoUnits_v1", bbox=(bbox[0] - pad, bbox[1] - pad, bbox[2] + pad, bbox[3] + pad))
    names = dict(zip(meta["fields"], fields))
    symbols = [str(s) for s in names["symbol"]]
    unit_names = [str(n).replace("Crater riim", "Crater rim") for n in names["name"]]
    legend_syms = sorted(set(symbols))
    sym_id = {s: i for i, s in enumerate(legend_syms)}
    shapes = []
    for g, s in zip(geoms, symbols):
        if g is None:
            continue
        gj = transform_geom(src_crs, grid.crs, mapping(from_wkb(g)))
        shapes.append((gj, sym_id[s]))
    units = rasterize(shapes, out_shape=grid.shape, transform=grid.transform, fill=-1, dtype="int16")
    area = {s: float((units == i).mean()) for s, i in sym_id.items()}
    legend = [{"id": sym_id[s], "symbol": s, "name": unit_names[symbols.index(s)], "colour": list(UNIT_COLOURS.get(s, (200, 200, 200))),
               "aoi_fraction": round(area[s], 4)} for s in legend_syms]
    return units, legend


@njit(parallel=True, cache=True)
def viewshed(z, r0, c0, h_obs, h_tgt, res, radius):
    """Line of sight from (r0, c0) to every cell over a spherical body (curvature drop d^2 / 2R).

    Heights are areoid elevations. The sight line is straight in the observer's tangent plane; terrain and the
    target are lowered by their curvature drop. Nearest-cell sampling along the ray, one sample per cell step.
    """
    H, W = z.shape
    out = np.zeros((H, W), np.uint8)
    zo = z[r0, c0] + h_obs
    for r in prange(H):
        for c in range(W):
            if not np.isfinite(z[r, c]):
                continue
            dr = r - r0
            dc = c - c0
            n = max(abs(dr), abs(dc))
            if n <= 1:
                out[r, c] = 1
                continue
            D = np.sqrt(dr * dr + dc * dc) * res
            zt = z[r, c] + h_tgt - D * D / (2.0 * radius)
            vis = 1
            for k in range(1, n):
                f = k / n
                rr = int(round(r0 + f * dr))
                cc = int(round(c0 + f * dc))
                zk = z[rr, cc]
                if not np.isfinite(zk):
                    continue
                d = f * D
                if zk - d * d / (2.0 * radius) > zo + f * (zt - zo):
                    vis = 0
                    break
            out[r, c] = vis
    return out


def comms(grid: Grid, elev: np.ndarray, habitat: dict, model: dict) -> np.ndarray:
    """Direct radio line of sight to the habitat antenna, computed at 4 m and expanded to 2 m."""
    c = model["comms"]
    h, w = (elev.shape[0] // 2) * 2, (elev.shape[1] // 2) * 2
    z4 = np.nanmean(elev[:h, :w].reshape(h // 2, 2, w // 2, 2), axis=(1, 3))
    vis4 = viewshed(z4.astype(np.float64), habitat["row"] // 2, habitat["col"] // 2, float(c["habitat_antenna_m"]["value"]),
                    float(c["suit_antenna_m"]["value"]), grid.res_m * 2, MARS_RADIUS_M)
    out = np.zeros(elev.shape, np.uint8)
    out[:h, :w] = np.repeat(np.repeat(vis4, 2, 0), 2, 1)
    out[:h, w:] = out[:h, w - 1:w]
    out[h:, :] = out[h - 1:h, :]
    out[~np.isfinite(elev)] = 0
    return out


def write_legend_png(units: np.ndarray, legend: list[dict], path) -> None:
    rgba = np.zeros(units.shape + (4,), np.uint8)
    for u in legend:
        m = units == u["id"]
        rgba[m, :3] = u["colour"]
        rgba[m, 3] = 170
    # unit contacts drawn darker so the map reads like a geologic map
    edge = np.zeros(units.shape, bool)
    edge[1:, :] |= units[1:, :] != units[:-1, :]
    edge[:, 1:] |= units[:, 1:] != units[:, :-1]
    rgba[edge & (units >= 0)] = (20, 20, 25, 230)
    render.write_png(path, rgba)


def main() -> int:
    t0 = time.time()
    aoi, model = load_yaml("aoi.yaml"), load_yaml("model.yaml")
    grid = Grid.from_config(aoi)
    resolved = json.loads((PROCESSED / "aoi_resolved.json").read_text(encoding="utf-8"))
    g = np.load(PROCESSED / "grid.npz")
    elev = g["elev"]
    web = PROCESSED / "web"

    units, legend = geology(grid)
    print(f"  geology: {len(legend)} units in AOI, mapped {np.mean(units >= 0):.1%}: "
          + ", ".join(f"{u['symbol']} {u['aoi_fraction']:.0%}" for u in sorted(legend, key=lambda u: -u["aoi_fraction"])))
    write_legend_png(units, legend, web / "geology.png")

    night = warp_to(THEMIS / "nili_THEMIS_NightIR_Controlled_oct2018.tif", grid.crs, grid.transform, grid.shape, Resampling.bilinear, src_nodata=0)
    day = warp_to(THEMIS / "nili_THEMIS_DayIR_Controlled_oct2018.tif", grid.crs, grid.transform, grid.shape, Resampling.bilinear, src_nodata=0)
    print(f"  THEMIS night IR DN {np.nanmin(night):.0f}..{np.nanmax(night):.0f}, day IR DN {np.nanmin(day):.0f}..{np.nanmax(day):.0f}")
    n01 = normalise(night, 1, 99)
    rgba = np.zeros(night.shape + (4,), np.uint8)
    # cold (dust, sand) dark blue -> warm at night (rock, bedrock) orange-white
    ramp = np.array([(30, 60, 160), (90, 140, 200), (240, 200, 120), (255, 240, 220)], np.float32)
    xs = np.linspace(0, 1, len(ramp))
    v = np.nan_to_num(n01)
    for k in range(3):
        rgba[..., k] = np.interp(v, xs, ramp[:, k]).astype(np.uint8)
    rgba[..., 3] = np.where(np.isfinite(n01), 175, 0)
    render.write_png(web / "thermal_night.png", rgba)

    vis = comms(grid, elev, resolved["habitat"], model)
    print(f"  comms: {vis[np.isfinite(elev)].mean():.1%} of the AOI in direct line of sight of the habitat antenna")
    shadow = np.zeros(vis.shape + (4,), np.uint8)
    shadow[(vis == 0) & np.isfinite(elev)] = (120, 40, 160, 150)   # dead zones only; LOS stays clear
    render.write_png(web / "comms.png", shadow)

    np.savez_compressed(PROCESSED / "context.npz", geo_unit=units, night_ir=night.astype(np.float32), day_ir=day.astype(np.float32), comms=vis)
    (PROCESSED / "geology_legend.json").write_text(json.dumps(legend, indent=1))

    meta = json.loads((web / "layers.json").read_text())
    meta["layers"].update({"geology": "geology.png", "thermal_night": "thermal_night.png", "comms": "comms.png"})
    meta["geology_legend"] = legend
    (web / "layers.json").write_text(json.dumps(meta, indent=1))
    add_manifest(grid, model)
    print(f"done in {time.time() - t0:.1f} s")
    return 0


def add_manifest(grid: Grid, model: dict) -> None:
    path = ROOT / "data" / "manifest.json"
    man = json.loads(path.read_text())
    steps = [f"warped with GDAL (rasterio WarpedVRT) to local eqc on Mars 2000 sphere, {grid.res_m} m/px", "clipped to config/aoi.yaml bounds"]
    sim = {"url": "https://pubs.usgs.gov/sim/3464/",
           "reference": "Sun, V., and Stack, K., 2020, USGS Scientific Investigations Map 3464, doi:10.3133/sim3464"}
    c = model["comms"]
    new = [
        {"id": "geology", "mission": "USGS-NASA Planetary Geologic Mapping Program", "instrument": "Photogeologic map on CTX + HiRISE",
         "product_id": "SIM 3464 GeoUnits_v1 (Nili.gdb)", **sim, "resolution_m": None, "acquired": "published 2020, map scale 1:75,000",
         "units": "geologic unit",
         "processing": ["polygons reprojected from MTM 77.5E (Mars 2000 sphere) with GDAL/OGR", "rasterised onto the working grid",
                        "USGS readme: map was drawn on a semi-controlled CTX mosaic,"
                        " so contacts can be offset 100-200 m from the controlled mosaic"]},
        {"id": "thermal_night", "mission": "Mars Odyssey", "instrument": "THEMIS IR (night)",
         "product_id": "nili_THEMIS_NightIR_Controlled_oct2018 (USGS controlled mosaic, in SIM 3464 package)", **sim, "resolution_m": 100,
         "acquired": "USGS controlled mosaic, Oct 2018", "units": "DN (relative brightness temperature, stretched)",
         "processing": steps + ["bilinear resampling from 100 m (coarse: ~30 x 40 pixels over the AOI)",
                                "relative, not calibrated temperature: warm at night = rock / high thermal inertia, cold = dust / fine sand"]},
        {"id": "comms", "mission": "Mars Reconnaissance Orbiter", "instrument": "HiRISE DTM (derived)",
         "product_id": "DTEEC_002387_1985_003798_1985_A01", "url": "https://hirise-pds.lpl.arizona.edu/PDS/DTM/", "resolution_m": 4,
         "acquired": "2007", "units": "line of sight 0/1",
         "processing": [f"viewshed from the habitat antenna ({c['habitat_antenna_m']['value']} m mast) to a suit antenna at "
                        f"{c['suit_antenna_m']['value']} m, on the DTM averaged to 4 m",
                        "Mars curvature included (drop d^2 / 2R, R = 3,396,190 m)", "direct line of sight only; no relay, no diffraction"]},
    ]
    ids = {e["id"] for e in new}
    man["layers"] = [e for e in man["layers"] if e["id"] not in ids] + new
    path.write_text(json.dumps(man, indent=1))


if __name__ == "__main__":
    sys.exit(main())
