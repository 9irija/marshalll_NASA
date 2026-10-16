"""CRISM summary-parameter science layers (Viviano-Beck et al. 2014 parameter set)."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import rasterio
from rasterio.warp import Resampling, reproject

from pipeline.geo import Grid
from pipeline.layers.terrain import normalise

# mineral key -> CRISM MTRDR summary parameter (band name in the SU cube)
PARAMS = {
    "olivine": "OLINDEX3",          # olivine index
    "fe_mg_smectite": "D2300",      # Fe/Mg phyllosilicate 2.3 um drop
    "carbonate": "MIN2295_2480",    # Mg-carbonate doublet
    "hydration": "BD1900_2",        # H2O combination band (hydrated minerals)
}


def reproject_band(path: Path, band_name: str, grid: Grid) -> np.ndarray:
    with rasterio.open(path) as src:
        idx = list(src.descriptions).index(band_name) + 1
        out = np.full(grid.shape, np.nan, dtype=np.float32)
        reproject(
            source=rasterio.band(src, idx),
            destination=out,
            src_nodata=src.nodata,
            dst_nodata=np.nan,
            dst_transform=grid.transform,
            dst_crs=grid.crs,
            resampling=Resampling.bilinear,
        )
    out[(out > 1e3) | (out < -1e3)] = np.nan   # guard against residual fill values
    return out


def mineral_layers(cubes: list[Path], grid: Grid) -> dict[str, np.ndarray]:
    """Per-mineral 0..1 index. Each observation is normalised on its own (AOI 50th..99th
    percentile, floored at 0) before the max-merge, so calibration offsets between
    observations do not leave seams at footprint edges."""
    layers = {}
    for key, band in PARAMS.items():
        stack = np.stack([normalise(reproject_band(p, band, grid), 50, 99, floor=0.0) for p in cubes])
        with np.errstate(all="ignore"):
            merged = np.nanmax(np.where(np.isfinite(stack), stack, -np.inf), axis=0)
        merged[~np.isfinite(merged)] = np.nan
        layers[key] = merged
    return layers


def science_value(minerals: dict[str, np.ndarray], weights: dict[str, float]) -> tuple[np.ndarray, dict]:
    """Weighted 0..1 science value from the normalised mineral indices: 0 means 'typical for the
    site or absent', 1 means 'among the strongest detections in the AOI'. Relative, not an abundance."""
    norm = minerals
    total = sum(weights.values())
    acc = np.zeros(next(iter(norm.values())).shape, dtype=np.float32)
    covered = np.zeros_like(acc, dtype=bool)
    for k, w in weights.items():
        n = norm[k]
        covered |= np.isfinite(n)
        acc += w * np.nan_to_num(n)
    val = acc / total
    val[~covered] = np.nan
    return val.astype(np.float32), norm
