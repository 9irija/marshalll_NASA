"""Planner view of the AOI: arrays the search kernels need, loaded once per process."""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

from pipeline.geo import PROCESSED, Grid, load_yaml
from pipeline.layers.terrain import normalise


@dataclass
class Site:
    grid: Grid
    elev: np.ndarray
    slope: np.ndarray
    rough_norm: np.ndarray
    hazard: np.ndarray
    science: np.ndarray
    minerals: dict[str, np.ndarray]
    habitat: dict
    targets: list[dict]
    hotspots: list[dict]

    def passable(self, max_slope_deg: float) -> np.ndarray:
        return np.isfinite(self.elev) & np.isfinite(self.slope) & (self.slope <= max_slope_deg)

    def slope_frac(self, max_slope_deg: float) -> np.ndarray:
        return np.clip(np.nan_to_num(self.slope, nan=90.0) / max_slope_deg, 0, 1).astype(np.float64)

    def rc(self, lat: float, lon: float) -> tuple[int, int]:
        r, c = self.grid.lonlat_to_rc(lon, lat)
        if not self.grid.in_bounds(r, c):
            raise ValueError(f"point {lat:.5f}N {lon:.5f}E is outside the AOI {self.grid.bounds_deg}")
        return int(r), int(c)

    def snap_passable(self, r: int, c: int, max_slope_deg: float, radius: int = 25) -> tuple[int, int]:
        ok = self.passable(max_slope_deg)
        if ok[r, c]:
            return r, c
        H, W = ok.shape
        r0, r1, c0, c1 = max(0, r - radius), min(H, r + radius + 1), max(0, c - radius), min(W, c + radius + 1)
        rr, cc = np.nonzero(ok[r0:r1, c0:c1])
        if rr.size == 0:
            raise ValueError("no passable ground within 50 m of the requested point")
        k = np.argmin((rr + r0 - r) ** 2 + (cc + c0 - c) ** 2)
        return int(rr[k] + r0), int(cc[k] + c0)

    def value(self, layer: str, lat: float, lon: float) -> float | None:
        arr = {"elevation": self.elev, "slope": self.slope, "hazard": self.hazard, "science": self.science,
               "roughness": self.rough_norm, **self.minerals}.get(layer)
        if arr is None:
            raise KeyError(layer)
        r, c = self.rc(lat, lon)
        v = float(arr[r, c])
        return v if np.isfinite(v) else None


def load_site(processed: Path = PROCESSED) -> Site:
    d = np.load(processed / "grid.npz")
    meta = json.loads((processed / "aoi_resolved.json").read_text(encoding="utf-8"))
    hotspots = json.loads((processed / "science_hotspots.json").read_text(encoding="utf-8"))
    aoi = load_yaml("aoi.yaml")
    grid = Grid.from_config(aoi)
    assert list(grid.shape) == meta["grid"]["shape"], "aoi.yaml changed since preprocessing; rerun make pipeline"
    rough = d["roughness"]
    return Site(grid=grid, elev=d["elev"].astype(np.float64), slope=d["slope"],
                rough_norm=np.nan_to_num(normalise(rough, 10, 99), nan=1.0).astype(np.float64),
                hazard=np.nan_to_num(d["hazard"], nan=1.0).astype(np.float64),
                science=np.nan_to_num(d["science"], nan=0.0),
                minerals={k[4:]: d[k] for k in d.files if k.startswith("min_")},
                habitat=meta["habitat"], targets=meta["targets"], hotspots=hotspots)


@lru_cache(maxsize=1)
def get_site() -> Site:
    return load_site()
