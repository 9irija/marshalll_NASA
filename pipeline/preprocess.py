"""Build every processed layer for the AOI from the raw NASA products.

Run: python -m pipeline.preprocess   (after python -m pipeline.download)

Outputs in data/processed/:
  cog/*.tif            Cloud-optimised GeoTIFFs on the working grid (local eqc, Mars 2000 sphere)
  web/*.png            Colourised overlays, exact lon/lat rectangle in web/layers.json
  web/terrain_*.u16    Height grids for the Cesium custom terrain provider
  web/traverse.json    Perseverance traverse clipped to the AOI
  grid.npz             Planner inputs (elevation, slope, roughness, hazard, science)
  aoi_resolved.json    Habitat snapped to safe ground, targets with elevations
  science_hotspots.json
and data/manifest.json (provenance).
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.enums import Resampling
from rasterio.vrt import WarpedVRT
from scipy import ndimage

from pipeline.geo import GEOGRAPHIC_CRS, PROCESSED, RAW, ROOT, Grid, load_yaml
from pipeline.layers import render, science, terrain

DTM = RAW / "hirise" / "DTEEC_002387_1985_003798_1985_A01.IMG"
ORTHO = RAW / "hirise" / "PSP_002387_1985_RED_C_01_ORTHO.JP2"
CRISM_CUBES = sorted((RAW / "crism").glob("*_su*_mtr3.img"))
TRAVERSE = RAW / "m20" / "M20_traverse.json"


def warp_to(path: Path, grid_crs: CRS, transform, shape, resampling: Resampling, src_crs=None, src_transform=None,
            src_nodata=None) -> np.ndarray:
    """Windowed warp through a WarpedVRT: only the source blocks under the AOI are read."""
    with rasterio.open(path) as src:
        kw = {}
        if src_crs is not None:
            kw.update(src_crs=src_crs, src_transform=src_transform)
        nodata = src_nodata if src_nodata is not None else src.nodata
        with WarpedVRT(src, crs=grid_crs, transform=transform, width=shape[1], height=shape[0],
                       resampling=resampling, src_nodata=nodata, nodata=np.nan, dtype="float32", **kw) as vrt:
            return vrt.read(1)


def write_cog(path: Path, a: np.ndarray, grid: Grid, units: str, description: str) -> None:
    profile = dict(driver="COG", width=a.shape[1], height=a.shape[0], count=1, dtype="float32", crs=grid.crs,
                   transform=grid.transform, nodata=np.nan, compress="DEFLATE", blocksize=512)
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(a.astype(np.float32), 1)
        dst.update_tags(units=units, description=description)


def geographic_grid(bounds: dict, res_m: float):
    """Regular lon/lat grid (Mars 2000 sphere) covering bounds at ~res_m."""
    from pipeline.geo import MARS_RADIUS_M

    dlat = np.degrees(res_m / MARS_RADIUS_M)
    clat = 0.5 * (bounds["south"] + bounds["north"])
    dlon = dlat / np.cos(np.radians(clat))
    w = int(np.floor((bounds["east"] - bounds["west"]) / dlon))
    h = int(np.floor((bounds["north"] - bounds["south"]) / dlat))
    t = rasterio.transform.from_origin(bounds["west"], bounds["north"], dlon, dlat)
    out = {"west": bounds["west"], "north": bounds["north"], "east": bounds["west"] + w * dlon,
           "south": bounds["north"] - h * dlat}
    return t, (h, w), out


def resolve_sites(aoi: dict, grid: Grid, slope: np.ndarray, hazard: np.ndarray, elev: np.ndarray, max_slope: float):
    hab = aoi["habitat"]
    r0, c0 = grid.lonlat_to_rc(hab["seed_lon"], hab["seed_lat"])
    rad = int(hab["search_radius_m"] / grid.res_m)
    flat = ndimage.uniform_filter(np.nan_to_num(slope, nan=90), 9) + 10 * ndimage.uniform_filter(np.nan_to_num(hazard, nan=1), 9)
    rr, cc = np.mgrid[-rad:rad + 1, -rad:rad + 1]
    disk = rr ** 2 + cc ** 2 <= rad ** 2
    best, best_rc = np.inf, (r0, c0)
    for dr, dc in zip(rr[disk], cc[disk]):
        r, c = r0 + dr, c0 + dc
        if grid.in_bounds(r, c) and flat[r, c] < best:
            best, best_rc = flat[r, c], (r, c)
    lon, lat = grid.rc_to_lonlat(*best_rc)
    habitat = {"name": hab["name"], "lat": float(lat), "lon": float(lon), "row": int(best_rc[0]), "col": int(best_rc[1]),
               "elev_m": float(elev[best_rc]), "seed": {"lat": hab["seed_lat"], "lon": hab["seed_lon"]},
               "snap_note": f"Flattest/lowest-hazard 2 m cell within {hab['search_radius_m']} m of the sol-13 landing localisation."}

    passable = np.isfinite(slope) & (slope <= max_slope)
    dist, (ir, ic) = ndimage.distance_transform_edt(~passable, return_indices=True)
    targets = []
    for t in aoi["targets"]:
        r, c = grid.lonlat_to_rc(t["lon"], t["lat"])
        if not grid.in_bounds(r, c):
            print(f"  ! target {t['id']} outside AOI, skipped")
            continue
        sr, sc = int(ir[r, c]), int(ic[r, c])
        lon2, lat2 = grid.rc_to_lonlat(sr, sc)
        targets.append({**t, "lat": float(lat2), "lon": float(lon2), "row": sr, "col": sc, "elev_m": float(elev[sr, sc]),
                        "snapped_m": float(dist[r, c] * grid.res_m), "source_lat": t["lat"], "source_lon": t["lon"]})
    return habitat, targets


def science_hotspots(sci: np.ndarray, slope: np.ndarray, grid: Grid, max_slope: float, n: int, spacing_m: float):
    smooth = ndimage.gaussian_filter(np.nan_to_num(sci), 3)
    ok = np.isfinite(slope) & (slope <= max_slope) & np.isfinite(sci)
    size = max(3, int(spacing_m / grid.res_m))
    peaks = (smooth == ndimage.maximum_filter(smooth, size)) & ok & (smooth > 0.05)
    rr, cc = np.nonzero(peaks)
    order = np.argsort(-smooth[rr, cc])
    chosen = []
    for i in order:
        r, c = rr[i], cc[i]
        if all((r - a) ** 2 + (c - b) ** 2 >= (spacing_m / grid.res_m) ** 2 for a, b, _ in chosen):
            chosen.append((r, c, float(smooth[r, c])))
        if len(chosen) >= n:
            break
    out = []
    for k, (r, c, v) in enumerate(chosen):
        lon, lat = grid.rc_to_lonlat(r, c)
        out.append({"id": f"hs{k:02d}", "row": int(r), "col": int(c), "lat": float(lat), "lon": float(lon), "value": round(v, 4)})
    return out


def clip_traverse(grid: Grid) -> dict:
    data = json.loads(TRAVERSE.read_text(encoding="utf-8"))
    b = grid.bounds_deg
    feats = []
    for f in data["features"]:
        coords = [c for c in f["geometry"]["coordinates"] if b["west"] <= c[0] <= b["east"] and b["south"] <= c[1] <= b["north"]]
        if len(coords) >= 2:
            feats.append({"type": "Feature", "properties": {"sol": f["properties"]["sol"], "length_m": f["properties"]["length"]},
                          "geometry": {"type": "LineString", "coordinates": [[round(c[0], 7), round(c[1], 7), round(c[2], 2)] for c in coords]}})
    return {"type": "FeatureCollection", "features": feats}


def main() -> int:
    t0 = time.time()
    aoi, model = load_yaml("aoi.yaml"), load_yaml("model.yaml")
    grid = Grid.from_config(aoi)
    max_slope = model["terrain"]["max_slope_deg"]["value"]
    cog, web = PROCESSED / "cog", PROCESSED / "web"
    cog.mkdir(parents=True, exist_ok=True)
    web.mkdir(parents=True, exist_ok=True)
    print(f"AOI grid {grid.shape} at {grid.res_m} m, CRS {grid.crs.to_proj4()}")

    # --- elevation / slope / roughness -----------------------------------------------------------
    with rasterio.open(DTM) as src:
        dtm_crs, dtm_transform, dtm_shape = src.crs, src.transform, src.shape
    elev = warp_to(DTM, grid.crs, grid.transform, grid.shape, Resampling.bilinear)
    elev[(elev < -9000) | (elev > 30000)] = np.nan
    print(f"  elevation {np.nanmin(elev):.1f}..{np.nanmax(elev):.1f} m, nan {np.isnan(elev).mean():.2%}")
    slope = terrain.slope_deg(elev, grid.res_m)
    rough = terrain.roughness_m(elev, grid.res_m, model["terrain"]["roughness_window_m"]["value"])

    # orthoimage texture at native 1 m, then averaged to the working grid. The JP2 GML header
    # carries a malformed CRS, so we georeference it with the DTM label (same 1.0096 m grid).
    fine_t = grid.transform * rasterio.Affine.scale(0.5)
    fine_shape = (grid.shape[0] * 2, grid.shape[1] * 2)
    ortho_fine = warp_to(ORTHO, grid.crs, fine_t, fine_shape, Resampling.bilinear, src_crs=dtm_crs,
                         src_transform=dtm_transform, src_nodata=0)
    tex_fine = terrain.local_std(ortho_fine - ndimage.uniform_filter(np.nan_to_num(ortho_fine), 9), 5)
    tex = tex_fine.reshape(grid.shape[0], 2, grid.shape[1], 2).mean(axis=(1, 3))
    ortho = np.nanmean(ortho_fine.reshape(grid.shape[0], 2, grid.shape[1], 2), axis=(1, 3))
    hazard = terrain.rock_hazard(rough, tex)

    # --- CRISM science ---------------------------------------------------------------------------
    minerals = science.mineral_layers(CRISM_CUBES, grid)
    sci, norm = science.science_value(minerals, model["science"]["weights"]["value"])
    print(f"  science coverage {np.isfinite(sci).mean():.1%}")

    # --- COGs ------------------------------------------------------------------------------------
    write_cog(cog / "elevation.tif", elev, grid, "m", "HiRISE DTM elevation (areoid)")
    write_cog(cog / "slope.tif", slope, grid, "deg", "Slope from HiRISE DTM")
    write_cog(cog / "roughness.tif", rough, grid, "m", "Local std of detrended elevation")
    write_cog(cog / "hazard.tif", hazard, grid, "0-1", "Rock hazard proxy")
    write_cog(cog / "science.tif", sci, grid, "0-1", "CRISM weighted science value")
    for k, v in norm.items():
        write_cog(cog / f"{k}.tif", v, grid, "0-1", f"CRISM {science.PARAMS[k]} normalised")
    np.savez_compressed(PROCESSED / "grid.npz", elev=elev, slope=slope, roughness=rough, hazard=hazard, science=sci,
                        **{f"min_{k}": v for k, v in norm.items()})

    # --- web overlays ----------------------------------------------------------------------------
    bounds = grid.bounds_deg
    layer_meta = {"bounds": bounds, "layers": {}}
    overlays = {"slope": np.clip(slope / max_slope, 0, 1.0001), "hazard": hazard, "science": sci, **norm}
    for k, v in overlays.items():
        rgba = render.colourise(v, k)
        if k == "slope":
            rgba[slope > max_slope] = (150, 20, 40, 235)   # impassable cells
        render.write_png(web / f"{k}.png", rgba)
        layer_meta["layers"][k] = f"{k}.png"
    o8 = np.nan_to_num(terrain.normalise(ortho, 0.5, 99.5) * 255).astype(np.uint8)
    render.write_png(web / "ortho.png", np.stack([o8, np.where(np.isfinite(ortho), 255, 0).astype(np.uint8)], -1))
    layer_meta["layers"]["ortho"] = "ortho.png"
    (web / "layers.json").write_text(json.dumps(layer_meta, indent=1))

    # terrain heights: AOI at 4 m, plus the full DTM footprint at 12 m for context
    t_aoi, s_aoi, b_aoi = geographic_grid(bounds, 4.0)
    render.write_heights(web / "terrain_aoi.u16", warp_to(DTM, GEOGRAPHIC_CRS, t_aoi, s_aoi, Resampling.average), b_aoi)
    with rasterio.open(DTM) as src:
        from rasterio.warp import transform_bounds
        w, s, e, n = transform_bounds(src.crs, GEOGRAPHIC_CRS, *src.bounds)
    t_ctx, s_ctx, b_ctx = geographic_grid({"west": w, "south": s, "east": e, "north": n}, 12.0)
    ctx = warp_to(DTM, GEOGRAPHIC_CRS, t_ctx, s_ctx, Resampling.average)
    ctx[(ctx < -9000) | (ctx > 30000)] = np.nan
    render.write_heights(web / "terrain_context.u16", ctx, b_ctx)

    (web / "traverse.json").write_text(json.dumps(clip_traverse(grid)))

    # --- sites -----------------------------------------------------------------------------------
    habitat, targets = resolve_sites(aoi, grid, slope, hazard, elev, max_slope)
    hotspots = science_hotspots(sci, slope, grid, max_slope, model["science"]["candidate_count"]["value"],
                                model["science"]["min_spacing_m"]["value"])
    resolved = {"name": aoi["name"], "grid": {"shape": list(grid.shape), "res_m": grid.res_m, "crs": grid.crs.to_proj4(),
                "transform": list(grid.transform)[:6], "bounds": bounds},
                "habitat": habitat, "targets": targets, "dtm_footprint": {"west": w, "south": s, "east": e, "north": n}}
    (PROCESSED / "aoi_resolved.json").write_text(json.dumps(resolved, indent=1))
    (PROCESSED / "science_hotspots.json").write_text(json.dumps(hotspots, indent=1))
    print(f"  habitat {habitat['lat']:.5f}N {habitat['lon']:.5f}E, {len(targets)} targets, {len(hotspots)} hotspots")

    write_manifest(grid, dtm_shape)
    print(f"done in {time.time() - t0:.1f} s")
    return 0


def write_manifest(grid: Grid, dtm_shape) -> None:
    steps_common = [f"warped with GDAL (rasterio WarpedVRT) to local eqc on Mars 2000 sphere, {grid.res_m} m/px",
                    "clipped to config/aoi.yaml bounds"]
    hirise_dtm = {"mission": "Mars Reconnaissance Orbiter", "instrument": "HiRISE",
                  "product_id": "DTEEC_002387_1985_003798_1985_A01",
                  "url": "https://hirise-pds.lpl.arizona.edu/PDS/DTM/PSP/ORB_002300_002399/PSP_002387_1985_PSP_003798_1985/",
                  "resolution_m": 1.01, "acquired": "2007, MRO primary science phase (orbits 2387 and 3798; exact times not in the DTM label)",
                  "reference": "McEwen et al. 2007; HiRISE stereo DTM, PDS release"}
    crism = {"mission": "Mars Reconnaissance Orbiter", "instrument": "CRISM",
             "product_id": "FRT000047A3_07_SU166J_MTR3, FRT00005C5E_07_SU166J_MTR3",
             "url": "https://pds-geosciences.wustl.edu/mro/mro-m-crism-5-rdr-mptargeted-v1/mrocr_4001/mtrdr/",
             "resolution_m": 18, "acquired": "2007 DOY 057 (FRT000047A3), 2007 DOY 139 (FRT00005C5E), from PDS archive paths",
             "reference": "Seelos et al. MTRDR; summary parameters per Viviano-Beck et al. 2014, JGR Planets"}
    trek = "https://trek.nasa.gov/tiles/Mars/EQ/{label}/1.0.0/WMTSCapabilities.xml"
    entries = [
        {"id": "elevation", **hirise_dtm, "units": "m", "processing": steps_common + ["bilinear resampling"]},
        {"id": "slope", **hirise_dtm, "units": "deg", "processing": steps_common + ["central-difference gradient, atan(|grad|)"]},
        {"id": "roughness", **hirise_dtm, "units": "m", "processing": steps_common + ["std of DTM minus 6 m box mean, 6 m window"]},
        {"id": "hazard", "mission": "Mars Reconnaissance Orbiter", "instrument": "HiRISE (DTM + RED orthoimage)",
         "product_id": "DTEEC_002387_1985_003798_1985_A01 + PSP_002387_1985_RED_C_01_ORTHO",
         "url": hirise_dtm["url"], "resolution_m": grid.res_m, "acquired": "2007 (orbit 2387)", "units": "0-1",
         "processing": steps_common + ["DERIVED PROXY: 0.6 x normalised roughness + 0.4 x normalised ortho texture (local std, 1 m)",
                                       "not a rock-count product; see docs/STUBS.md"]},
        {"id": "science", **crism, "units": "0-1",
         "processing": steps_common + ["OLINDEX3, D2300, MIN2295_2480, BD1900_2 normalised per observation to AOI 50th-99th pct, floored at 0",
                                       "max across the two observations (after per-observation normalisation)",
                                       "weighted sum, weights in config/model.yaml"]},
        *[{"id": k, **crism, "product_id": f"{crism['product_id']} band {b}", "units": "0-1",
           "processing": steps_common + [f"{b} normalised to AOI 50th-99th percentile"]} for k, b in science.PARAMS.items()],
        {"id": "ortho", "mission": "Mars Reconnaissance Orbiter", "instrument": "HiRISE",
         "product_id": "PSP_002387_1985_RED_C_01_ORTHO", "url": hirise_dtm["url"], "resolution_m": 1.01,
         "acquired": "2007 (orbit 2387)", "units": "DN", "processing": steps_common + ["georeferenced with the DTM label grid"]},
        {"id": "hirise_mosaic", "mission": "Mars Reconnaissance Orbiter", "instrument": "HiRISE",
         "product_id": "JEZ_hirise_soc_006_orthoMosaic_25cm_Eqc_latTs0_lon0_first_dd",
         "url": trek.format(label="JEZ_hirise_soc_006_orthoMosaic_25cm_Eqc_latTs0_lon0_first_dd"), "resolution_m": 0.25,
         "acquired": "Mars 2020 landing-site controlled HiRISE mosaic (Fergason et al. 2020)", "units": "DN",
         "processing": ["streamed from NASA Mars Trek WMTS, geographic tiling"]},
        {"id": "ctx_mosaic", "mission": "Mars Reconnaissance Orbiter", "instrument": "CTX",
         "product_id": "JEZ_ctx_B_soc_008_orthoMosaic_6m_Eqc_latTs0_lon0",
         "url": trek.format(label="JEZ_ctx_B_soc_008_orthoMosaic_6m_Eqc_latTs0_lon0"), "resolution_m": 6,
         "acquired": "Mars 2020 landing-site controlled CTX mosaic (Fergason et al. 2020)", "units": "DN",
         "processing": ["streamed from NASA Mars Trek WMTS"]},
        {"id": "viking_global", "mission": "Viking Orbiter", "instrument": "VIS (MDIM 2.1 colour)",
         "product_id": "Mars_Viking_MDIM21_ClrMosaic_global_232m",
         "url": trek.format(label="Mars_Viking_MDIM21_ClrMosaic_global_232m"), "resolution_m": 232, "acquired": "1976-1980",
         "units": "RGB", "processing": ["streamed from NASA Mars Trek WMTS (global base)"]},
        {"id": "traverse", "mission": "Mars 2020", "instrument": "Perseverance localization",
         "product_id": "M20_traverse.json / M20_waypoints.json", "url": "https://mars.nasa.gov/mmgis-maps/M20/Layers/json/",
         "resolution_m": None, "acquired": "sols 13-1006 inside the DTM", "units": "lon/lat/elev",
         "processing": ["clipped to AOI"]},
        {"id": "conditions", "mission": "Mars 2020", "instrument": "MEDA",
         "product_id": "Mars 2020 weather feed", "url": "https://mars.nasa.gov/rss/api/?feed=weather&category=mars2020&feedtype=json",
         "resolution_m": None, "acquired": "latest 7 sols published by the feed", "units": "degC, Pa", "processing": ["parsed as-is"]},
    ]
    (ROOT / "data" / "manifest.json").write_text(json.dumps({"layers": entries, "dtm_shape": list(dtm_shape)}, indent=1))


if __name__ == "__main__":
    sys.exit(main())
