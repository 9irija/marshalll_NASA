"""Coordinate conventions shared by pipeline, planner and API.

Mars 2000 IAU sphere, R = 3,396,190 m. Latitudes planetocentric, longitudes
east-positive in -180..180. The working CRS is a local equirectangular projection
with lat_0 = 0, so the working grid is a regular lat/lon grid: every processed
raster maps exactly onto a Cesium Rectangle.fromDegrees.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

import numpy as np
import yaml
from affine import Affine
from rasterio.crs import CRS

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config"
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"

MARS_RADIUS_M = 3_396_190.0
GEOGRAPHIC_CRS = CRS.from_proj4(f"+proj=longlat +R={MARS_RADIUS_M:.0f} +no_defs")


def wrap_lon(lon: float | np.ndarray) -> float | np.ndarray:
    """Normalise longitude to the -180..180 east-positive convention."""
    return (np.asarray(lon) + 180.0) % 360.0 - 180.0


def load_yaml(name: str) -> dict:
    with open(CONFIG / name, encoding="utf-8") as f:
        return yaml.safe_load(f)


@dataclass(frozen=True)
class Grid:
    """Working grid of the AOI in the local equirectangular CRS."""

    min_lat: float
    max_lat: float
    min_lon: float
    max_lon: float
    res_m: float

    @classmethod
    def from_config(cls, aoi: dict | None = None) -> Grid:
        aoi = aoi or load_yaml("aoi.yaml")
        b = aoi["bounds"]
        return cls(b["min_lat"], b["max_lat"], wrap_lon(b["min_lon"]), wrap_lon(b["max_lon"]), aoi["working_res_m"])

    @property
    def center_lat(self) -> float:
        return 0.5 * (self.min_lat + self.max_lat)

    @property
    def center_lon(self) -> float:
        return 0.5 * (self.min_lon + self.max_lon)

    @cached_property
    def crs(self) -> CRS:
        return CRS.from_proj4(
            f"+proj=eqc +lat_ts={self.center_lat:.6f} +lat_0=0 +lon_0={self.center_lon:.6f} "
            f"+x_0=0 +y_0=0 +R={MARS_RADIUS_M:.0f} +units=m +no_defs"
        )

    @property
    def _kx(self) -> float:
        return MARS_RADIUS_M * np.cos(np.radians(self.center_lat)) * np.pi / 180.0

    @property
    def _ky(self) -> float:
        return MARS_RADIUS_M * np.pi / 180.0

    def lonlat_to_xy(self, lon, lat):
        lon = wrap_lon(lon)
        return (np.asarray(lon) - self.center_lon) * self._kx, np.asarray(lat) * self._ky

    def xy_to_lonlat(self, x, y):
        return wrap_lon(np.asarray(x) / self._kx + self.center_lon), np.asarray(y) / self._ky

    @cached_property
    def shape(self) -> tuple[int, int]:
        x0, y0 = self.lonlat_to_xy(self.min_lon, self.min_lat)
        x1, y1 = self.lonlat_to_xy(self.max_lon, self.max_lat)
        return int(round((y1 - y0) / self.res_m)), int(round((x1 - x0) / self.res_m))

    @cached_property
    def transform(self) -> Affine:
        x0, _ = self.lonlat_to_xy(self.min_lon, self.min_lat)
        _, y1 = self.lonlat_to_xy(self.max_lon, self.max_lat)
        return Affine(self.res_m, 0.0, float(x0), 0.0, -self.res_m, float(y1))

    @property
    def bounds_deg(self) -> dict:
        """Exact lon/lat bounds of the pixel grid (edges, not centres)."""
        h, w = self.shape
        t = self.transform
        lon0, lat1 = self.xy_to_lonlat(t.c, t.f)
        lon1, lat0 = self.xy_to_lonlat(t.c + w * t.a, t.f + h * t.e)
        return {"west": float(lon0), "south": float(lat0), "east": float(lon1), "north": float(lat1)}

    def lonlat_to_rc(self, lon, lat):
        x, y = self.lonlat_to_xy(lon, lat)
        col, row = ~self.transform @ (x, y)
        return np.floor(row).astype(int), np.floor(col).astype(int)

    def rc_to_lonlat(self, row, col):
        x, y = self.transform @ (np.asarray(col) + 0.5, np.asarray(row) + 0.5)
        return self.xy_to_lonlat(x, y)

    def in_bounds(self, row, col) -> bool:
        h, w = self.shape
        return bool(0 <= row < h and 0 <= col < w)


def resolved_aoi() -> dict:
    """AOI after preprocessing (habitat snapped, target elevations filled)."""
    with open(PROCESSED / "aoi_resolved.json", encoding="utf-8") as f:
        return json.load(f)
