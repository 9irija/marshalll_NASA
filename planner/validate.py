"""Compare a planned route with Perseverance's real traverse between the same two waypoints.

Metrics (both in metres, computed in the local equirectangular plane):
  mean_deviation_m  mean distance from each planned vertex to the actual polyline
  frechet_m         discrete Frechet distance (Eiter & Mannila 1994) between the two polylines
"""
from __future__ import annotations

import json
from functools import lru_cache

import numba as nb
import numpy as np
from shapely.geometry import LineString, Point

from pipeline.geo import RAW
from planner.cost import CostParams
from planner.routes import Stop, build_route
from planner.site import Site

# Default comparison: sols 389 -> 415, the last 3 km of the April 2022 rapid traverse to the
# delta front (rover path only 1.09x the straight line, so a fair test of route choice).
# Sols 340 -> 415 is the instructive counter-example: the rover drove 8.6 km around the
# Seitah dunes that a walker crosses in about 2.6 km.
DEFAULT_SOLS = (389, 415)


@lru_cache(maxsize=1)
def _waypoints() -> list[dict]:
    feats = json.loads((RAW / "m20" / "M20_waypoints.json").read_text(encoding="utf-8"))["features"]
    return [f["properties"] for f in feats]


@lru_cache(maxsize=1)
def _traverse() -> list[dict]:
    return json.loads((RAW / "m20" / "M20_traverse.json").read_text(encoding="utf-8"))["features"]


def waypoint_at(sol: int) -> dict:
    cands = [p for p in _waypoints() if p["sol"] <= sol]
    if not cands:
        raise ValueError(f"no waypoint at or before sol {sol}")
    return cands[-1]


def actual_path(sol_from: int, sol_to: int) -> np.ndarray:
    """Concatenated traverse vertices (lon, lat) for drives on sols (sol_from, sol_to]."""
    pts = []
    for f in _traverse():
        if sol_from < f["properties"]["sol"] <= sol_to:
            pts.extend((c[0], c[1]) for c in f["geometry"]["coordinates"])
    arr = np.array(pts, dtype=np.float64)
    if len(arr) < 2:
        raise ValueError(f"no traverse between sols {sol_from} and {sol_to}")
    keep = np.r_[True, np.any(np.abs(np.diff(arr, axis=0)) > 1e-9, axis=1)]
    return arr[keep]


@nb.njit(cache=True)
def discrete_frechet(P: np.ndarray, Q: np.ndarray) -> float:
    n, m = P.shape[0], Q.shape[0]
    ca = np.empty((n, m))
    for i in range(n):
        for j in range(m):
            d = np.sqrt((P[i, 0] - Q[j, 0]) ** 2 + (P[i, 1] - Q[j, 1]) ** 2)
            if i == 0 and j == 0:
                ca[i, j] = d
            elif i == 0:
                ca[i, j] = max(ca[i, j - 1], d)
            elif j == 0:
                ca[i, j] = max(ca[i - 1, j], d)
            else:
                ca[i, j] = max(min(ca[i - 1, j], ca[i - 1, j - 1], ca[i, j - 1]), d)
    return ca[n - 1, m - 1]


def _resample(xy: np.ndarray, step: float) -> np.ndarray:
    line = LineString(xy)
    n = max(2, int(line.length / step) + 1)
    return np.array([line.interpolate(d).coords[0] for d in np.linspace(0, line.length, n)])


def compare(site: Site, sol_from: int = DEFAULT_SOLS[0], sol_to: int = DEFAULT_SOLS[1], objective: str = "fastest") -> dict:
    g = site.grid
    a, b = waypoint_at(sol_from), waypoint_at(sol_to)
    p = CostParams.from_config()
    s = Stop(*site.snap_passable(*site.rc(a["lat"], a["lon"]), p.max_slope_deg), f"Sol {sol_from}", "habitat")
    e = Stop(*site.snap_passable(*site.rc(b["lat"], b["lon"]), p.max_slope_deg), f"Sol {sol_to}", "target")
    route = build_route(site, p, objective, [s, e])
    act_ll = actual_path(sol_from, sol_to)
    ax, ay = g.lonlat_to_xy(act_ll[:, 0], act_ll[:, 1])
    act = np.column_stack([ax, ay])
    lon, lat = g.rc_to_lonlat(route.rows, route.cols)
    px, py = g.lonlat_to_xy(lon, lat)
    plan = np.column_stack([px, py])
    act_line = LineString(act)
    mean_dev = float(np.mean([act_line.distance(Point(x, y)) for x, y in plan[::2]]))
    fr = discrete_frechet(_resample(plan, 10.0), _resample(act, 10.0))
    return {
        "sol_from": sol_from, "sol_to": sol_to,
        "start": {"lat": a["lat"], "lon": a["lon"], "rmc": a["RMC"]}, "end": {"lat": b["lat"], "lon": b["lon"], "rmc": b["RMC"]},
        "planned": {"type": "LineString", "coordinates": [[round(float(x), 7), round(float(y), 7)] for x, y in zip(lon[::3], lat[::3])],
                    "length_m": round(route.totals["distance_m"], 1), "objective": objective},
        "actual": {"type": "LineString", "coordinates": [[round(float(x), 7), round(float(y), 7)] for x, y in act_ll],
                   "length_m": round(act_line.length, 1)},
        "mean_deviation_m": round(mean_dev, 1), "frechet_m": round(float(fr), 1),
        "note": "Perseverance is a rover with its own traversability limits and science stops; deviation measures "
                "how a suited walker's optimal path differs, not an error.",
        "source": "https://mars.nasa.gov/mmgis-maps/M20/Layers/json/M20_traverse.json",
    }
