"""Return envelope and point of no return.

cost_home(X): consumables needed to walk from cell X back to the habitat on the
O2-optimal path (reverse Dijkstra, directional edges). For a route with cumulative
consumption c(t), cell X is inside the envelope at time t when

    c(t) + cost_home(X) <= initial - reserve      (for O2 and for battery)
    t + time_home(X)    <= EVA time limit         (back before the EVA ends)

Because c(t) only grows, each cell has a single *deadline* T(X): the last moment it is
still inside the envelope. envelope(t) = {X : T(X) >= t}. The web app animates the
envelope on the GPU by thresholding the T field; the API also returns polygons.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from functools import lru_cache

import numpy as np
import rasterio.features
import shapely
from shapely.geometry import mapping, shape

from planner import graph
from planner.cost import CostParams
from planner.site import Site, get_site


@dataclass
class HomeField:
    o2: np.ndarray       # kg O2 to get home from each cell (inf = unreachable)
    batt: np.ndarray     # Wh along that path
    t: np.ndarray        # seconds along that path
    elapsed_s: float


def _key(p: CostParams, home: tuple[int, int]) -> str:
    return hashlib.sha1(repr((p.as_array().tobytes(), p.max_slope_deg, home)).encode()).hexdigest()


_cache: dict[str, HomeField] = {}


def home_field(site: Site, p: CostParams, home: tuple[int, int]) -> HomeField:
    """Reverse Dijkstra toward the habitat. Cached per (habitat, params)."""
    import time

    k = _key(p, home)
    if k not in _cache:
        t0 = time.perf_counter()
        _, t, o2, b, _ = graph.dijkstra(site.elev, site.passable(p.max_slope_deg), site.rough_norm, site.hazard,
                                        site.slope_frac(p.max_slope_deg), site.grid.res_m, p.as_array(), graph.ENERGY,
                                        0.0, home[0], home[1], True, np.inf)
        _cache[k] = HomeField(o2=o2, batt=b, t=t, elapsed_s=time.perf_counter() - t0)
        if len(_cache) > 16:
            _cache.pop(next(iter(_cache)))
    return _cache[k]


def deadline_field(field: HomeField, p: CostParams, t_s: np.ndarray, o2_kg: np.ndarray, batt_wh: np.ndarray,
                   o2_start: float | None = None, batt_start: float | None = None) -> np.ndarray:
    """T(X) in seconds since EVA start; -1 where the cell is never safe; capped at max_duration."""
    o2_start = p.initial_o2_kg if o2_start is None else o2_start
    batt_start = p.battery_wh if batt_start is None else batt_start
    rest_o2 = p.o2_rate_rest_kg_s
    rest_b = p.suit_power_w / 3600.0
    out = np.empty(field.o2.shape, dtype=np.float64)
    T = np.full(field.o2.shape, np.inf)
    for home, used, start, reserve, rest in (
        (field.o2, o2_kg, o2_start, p.initial_o2_kg * p.o2_reserve_frac, rest_o2),
        (field.batt, batt_wh, batt_start, p.battery_wh * p.batt_reserve_frac, rest_b),
    ):
        budget = start - reserve - home                         # consumption allowed before leaving X
        within = np.interp(budget, used, t_s)                   # inverse of the monotone timeline
        beyond = t_s[-1] + (budget - used[-1]) / rest           # after the route ends, loiter at rest
        Ti = np.where(budget <= used[-1], within, beyond)
        Ti[budget < used[0]] = -1.0
        T = np.minimum(T, Ti)
    # Flight rule: be back at the habitat by the end of the planned EVA (max_duration_s).
    T = np.minimum(T, p.max_duration_s - field.t)
    T[~np.isfinite(field.o2)] = -1.0
    np.minimum(T, p.max_duration_s, out=out)
    out[T < 0] = -1.0
    return out


def route_margins(site: Site, field: HomeField, T: np.ndarray, rows, cols, t_s) -> dict:
    """Per-point slack (s) against the deadline field and the point of no return."""
    dl = T[rows, cols]
    slack = np.where(dl < 0, -np.inf, dl - t_s)
    bad = np.nonzero(slack < 0)[0]
    out = {"slack_s": slack}
    if bad.size:
        k = max(int(bad[0]) - 1, 0)
        lon, lat = site.grid.rc_to_lonlat(rows[k], cols[k])
        out["point_of_no_return"] = {"index": k, "lat": float(lat), "lon": float(lon), "t_s": float(t_s[k]),
                                     "reason": "continuing past this point leaves the return envelope"}
    else:
        k = int(np.argmin(slack))
        lon, lat = site.grid.rc_to_lonlat(rows[k], cols[k])
        out["tightest_point"] = {"index": k, "lat": float(lat), "lon": float(lon), "t_s": float(t_s[k]),
                                 "slack_s": float(slack[k])}
    return out


def envelope_polygons(site: Site, T: np.ndarray, times: np.ndarray, factor: int = 4, simplify_m: float = 6.0) -> list[dict]:
    """GeoJSON (lon/lat) MultiPolygon of the envelope at each time."""
    g = site.grid
    H, W = T.shape
    h, w = H // factor, W // factor
    Tc = T[: h * factor, : w * factor].reshape(h, factor, w, factor).min(axis=(1, 3))
    tr = g.transform @ g.transform.scale(factor)
    frames = []
    for t in times:
        mask = (Tc >= t).astype(np.uint8)
        polys = [shape(geom).simplify(simplify_m) for geom, val in rasterio.features.shapes(mask, mask=mask, transform=tr)
                 if val == 1]
        polys = [p for p in polys if p.area > 2000.0]
        geo = [shapely.transform(p, lambda xy: np.column_stack(g.xy_to_lonlat(xy[:, 0], xy[:, 1]))) for p in polys]
        frames.append({"t_s": float(t), "polygon": {"type": "MultiPolygon",
                                                    "coordinates": [mapping(p)["coordinates"] for p in geo]},
                       "area_km2": round(sum(p.area for p in polys) / 1e6, 4)})
    return frames


def encode_deadline_png(T: np.ndarray, t_max: float) -> np.ndarray:
    """RGBA uint8: R = round(T / t_max * 255), G = B = 0, A = 255 where T >= 0. Row 0 = north.

    8-bit in one channel so GPU linear filtering interpolates T correctly (a split 16-bit
    value would not); 1/255 of an 8 h horizon is under 2 minutes."""
    from scipy import ndimage

    valid = T >= 0
    if valid.any() and not valid.all():
        # fill invalid cells with the nearest valid deadline so GPU filtering creates no false edges
        idx = ndimage.distance_transform_edt(~valid, return_distances=False, return_indices=True)
        T = T[tuple(idx)]
    rgba = np.zeros(T.shape + (4,), dtype=np.uint8)
    rgba[..., 0] = np.clip(np.round(np.clip(T, 0, t_max) / t_max * 255), 0, 255).astype(np.uint8)
    rgba[..., 3] = np.where(valid, 255, 0)
    return rgba


@lru_cache(maxsize=1)
def default_home_field() -> HomeField:
    site = get_site()
    return home_field(site, CostParams.from_config(), (site.habitat["row"], site.habitat["col"]))
