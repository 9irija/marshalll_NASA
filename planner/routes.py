"""Route planning: legs by A*, per-segment consumables, envelope evaluation."""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

import numpy as np

from planner import envelope, fields, graph
from planner.cost import CostParams, step_cost, stop_cost
from planner.site import Site

OBJECTIVE_LABEL = {"safest": "Safest", "fastest": "Fastest", "science": "Most science"}


@dataclass
class Stop:
    row: int
    col: int
    name: str
    kind: str = "target"        # target | hotspot | habitat
    value: float = 0.0
    id: str = ""


@dataclass
class Route:
    objective: str
    rows: np.ndarray
    cols: np.ndarray
    stops: list[Stop]
    stop_index: list[int]
    seg: dict
    totals: dict
    margins: dict
    params: CostParams
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    compute_ms: float = 0.0


def leg(site: Site, p: CostParams, objective: int, a: tuple[int, int], b: tuple[int, int]) -> np.ndarray:
    """Optimal cell path a -> b. Legs touching the habitat use the cached habitat fields."""
    home = (site.habitat["row"], site.habitat["col"])
    W = site.grid.shape[1]
    if objective != graph.FASTEST and home in (a, b) and a != b:
        reverse = b == home
        f = fields.get(site, p, objective, home, reverse)
        path = fields.path_from_field(f, W, a, b, reverse)
        if path is None:
            raise ValueError(f"no passable route between cells {a} and {b} (slope limit {p.max_slope_deg} deg)")
        return path
    # Other legs: A* inside the leg's bounding box plus a margin (paths rarely wander further;
    # if the windowed search fails we fall back to the full grid).
    for margin in (200, None):
        if margin is None:
            r0, r1, c0, c1 = 0, site.grid.shape[0], 0, W
        else:
            r0, r1 = max(0, min(a[0], b[0]) - margin), min(site.grid.shape[0], max(a[0], b[0]) + margin + 1)
            c0, c1 = max(0, min(a[1], b[1]) - margin), min(W, max(a[1], b[1]) + margin + 1)
        win = (slice(r0, r1), slice(c0, c1))
        P = p.as_array()
        path, cost = graph.astar(
            np.ascontiguousarray(site.elev[win]), np.ascontiguousarray(site.passable(p.max_slope_deg)[win]),
            np.ascontiguousarray(site.rough_norm[win]), np.ascontiguousarray(site.hazard[win]),
            np.ascontiguousarray(site.slope_frac(p.max_slope_deg)[win]), site.grid.res_m, P, objective,
            p.hazard_weight_safest, a[0] - r0, a[1] - c0, b[0] - r0, b[1] - c0, graph.min_cost_per_metre(P, objective))
        if np.isfinite(cost):
            w = c1 - c0
            return (path // w + r0) * W + (path % w + c0)
    raise ValueError(f"no passable route between cells {a} and {b} (slope limit {p.max_slope_deg} deg)")


def profile(site: Site, p: CostParams, rows: np.ndarray, cols: np.ndarray, stop_index: list[int]) -> dict:
    """Cumulative distance/time/O2/battery along a cell path (same physics as the kernels, vectorised)."""
    res = site.grid.res_m
    z = site.elev[rows, cols]
    rough = site.rough_norm[rows, cols]
    diag = (np.diff(rows) != 0) & (np.diff(cols) != 0)
    d = np.where(diag, res * np.sqrt(2.0), res)
    t, o2, b = step_cost(d, np.diff(z), p, 0.5 * (rough[1:] + rough[:-1]))
    step_d, step_t, step_o2, step_b = (np.concatenate([[0.0], x]) for x in (d, t, o2, b))
    st, so2, sb = stop_cost(p)
    for k in stop_index:
        step_t[k] += st
        step_o2[k] += so2
        step_b[k] += sb
    return {"dist_m": np.cumsum(step_d), "elev_m": z, "slope_deg": site.slope[rows, cols].astype(np.float64),
            "t_s": np.cumsum(step_t), "o2_kg": np.cumsum(step_o2), "batt_wh": np.cumsum(step_b),
            "hazard": site.hazard[rows, cols], "science": site.science[rows, cols]}


def build_route(site: Site, p: CostParams, objective: str, stops: list[Stop], o2_start: float | None = None,
                batt_start: float | None = None) -> Route:
    """Join A* legs through the ordered stops (first = start, last = end)."""
    t0 = time.perf_counter()
    obj = graph.OBJECTIVES[objective]
    rows, cols, stop_index = [np.array([stops[0].row])], [np.array([stops[0].col])], []
    for a, b in zip(stops[:-1], stops[1:]):
        path = leg(site, p, obj, (a.row, a.col), (b.row, b.col))
        W = site.grid.shape[1]
        rows.append(path[1:] // W)
        cols.append(path[1:] % W)
        if b.kind != "habitat":
            stop_index.append(sum(len(r) for r in rows) - 1)
    rows_a, cols_a = np.concatenate(rows), np.concatenate(cols)
    seg = profile(site, p, rows_a, cols_a, stop_index)
    return finish_route(site, p, objective, rows_a, cols_a, stops, stop_index, seg, o2_start, batt_start, t0)


def finish_route(site, p, objective, rows, cols, stops, stop_index, seg, o2_start, batt_start, t0) -> Route:
    home = (site.habitat["row"], site.habitat["col"])
    hf = envelope.home_field(site, p, home)
    o2_start = p.initial_o2_kg if o2_start is None else o2_start
    batt_start = p.battery_wh if batt_start is None else batt_start
    T = envelope.deadline_field(hf, p, seg["t_s"], seg["o2_kg"], seg["batt_wh"], o2_start, batt_start)
    margins = envelope.route_margins(site, hf, T, rows, cols, seg["t_s"])
    o2_left = o2_start - seg["o2_kg"][-1]
    b_left = batt_start - seg["batt_wh"][-1]
    o2_res = p.initial_o2_kg * p.o2_reserve_frac
    b_res = p.battery_wh * p.batt_reserve_frac
    totals = {
        "distance_m": float(seg["dist_m"][-1]), "duration_s": float(seg["t_s"][-1]),
        "o2_kg": float(seg["o2_kg"][-1]), "batt_wh": float(seg["batt_wh"][-1]),
        "o2_remaining_kg": float(o2_left), "batt_remaining_wh": float(b_left),
        "o2_reserve_kg": float(o2_res), "batt_reserve_wh": float(b_res),
        "max_slope_deg": float(np.nanmax(seg["slope_deg"])), "mean_hazard": float(np.mean(seg["hazard"])),
        "science_score": float(sum(s.value for s in stops if s.kind != "habitat")),
        "stops": len(stop_index),
        "within_duration": bool(seg["t_s"][-1] <= p.max_duration_s),
        "feasible": bool(o2_left >= o2_res and b_left >= b_res and seg["t_s"][-1] <= p.max_duration_s
                         and "point_of_no_return" not in margins),
    }
    r = Route(objective=objective, rows=rows, cols=cols, stops=stops, stop_index=stop_index, seg=seg, totals=totals,
              margins=margins, params=p)
    r.deadline = T  # kept for the envelope endpoint
    r.compute_ms = (time.perf_counter() - t0) * 1000
    return r


def to_geojson(site: Site, r: Route, max_points: int = 1500) -> dict:
    """API shape (section 6 of the brief). Arrays are decimated for transport; stops are always kept."""
    n = len(r.rows)
    keep = np.unique(np.concatenate([np.linspace(0, n - 1, min(n, max_points)).round().astype(int),
                                     np.array(r.stop_index, dtype=int), [0, n - 1]]))
    lon, lat = site.grid.rc_to_lonlat(r.rows[keep], r.cols[keep])
    seg = {k: np.round(v[keep], 5).tolist() for k, v in r.seg.items() if k in ("dist_m", "elev_m", "slope_deg", "t_s", "o2_kg", "batt_wh")}
    seg["slack_s"] = np.round(np.where(np.isfinite(r.margins["slack_s"][keep]), r.margins["slack_s"][keep], -1e9), 1).tolist()
    remap = {int(k): i for i, k in enumerate(keep)}
    out = {
        "id": r.id, "objective": r.objective, "label": OBJECTIVE_LABEL.get(r.objective, r.objective),
        "geometry": {"type": "LineString", "coordinates": [[round(float(a), 7), round(float(b), 7), round(float(z), 2)]
                                                            for a, b, z in zip(lon, lat, r.seg["elev_m"][keep])]},
        "segments": seg,
        "stops": [{"id": s.id, "name": s.name, "kind": s.kind, "value": round(s.value, 3),
                   "lat": float(site.grid.rc_to_lonlat(s.row, s.col)[1]), "lon": float(site.grid.rc_to_lonlat(s.row, s.col)[0]),
                   "index": remap.get(int(k)) if k is not None else None}
                  for s, k in zip(r.stops, [0] + _stop_positions(r) + [n - 1])],
        "totals": {k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.totals.items()},
        "compute_ms": round(r.compute_ms, 1),
    }
    for key in ("point_of_no_return", "tightest_point"):
        if key in r.margins:
            m = dict(r.margins[key])
            m["index"] = int(np.searchsorted(keep, m["index"]))
            out[key] = m
    return out


def _stop_positions(r: Route) -> list[int]:
    """Path index of each intermediate stop (habitat pass-throughs share the next index)."""
    out, it = [], iter(r.stop_index)
    for s in r.stops[1:-1]:
        out.append(next(it) if s.kind != "habitat" else None)
    return out
