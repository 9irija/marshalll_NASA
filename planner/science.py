"""Pareto routes: safest, fastest and most-science.

Most-science is an orienteering problem: visit the required target(s) and as many
CRISM science hotspots as the O2 / battery / duration budget allows, then return.

  1. Leg costs between habitat, required targets and hotspots are estimated with
     Dijkstra on a 6x coarsened grid (one run per node, ~20 ms each).
  2. Greedy insertion: repeatedly insert the hotspot with the best
     value / added-O2 ratio that keeps the tour within 90 % of each budget
     (10 % margin for coarse-grid error).
  3. 2-opt on the coarse O2 matrix to shorten the tour.
  4. Exact legs with fine-grid A*; if the exact tour breaks a budget, drop the
     lowest-ratio hotspot and retry.
"""
from __future__ import annotations

import itertools
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from planner import graph
from planner.cost import CostParams, stop_cost
from planner.routes import Route, Stop, build_route
from planner.site import Site

COARSE = 6


def _coarse(site: Site, p: CostParams):
    f = COARSE
    H, W = site.grid.shape
    h, w = H // f, W // f

    def pool(a, fn):
        return fn(a[: h * f, : w * f].reshape(h, f, w, f), axis=(1, 3))

    passable = pool(site.passable(p.max_slope_deg).astype(np.float64), np.mean) > 0.8
    elev = pool(np.nan_to_num(site.elev, nan=np.nanmean(site.elev)), np.mean)
    return (elev, passable, pool(site.rough_norm, np.mean), pool(site.hazard, np.mean),
            pool(site.slope_frac(p.max_slope_deg), np.max))


_coarse_cache: dict = {}
_node_fields: dict = {}


def _coarse_cached(site: Site, p: CostParams):
    key = (p.as_array().tobytes(), p.max_slope_deg)
    if key not in _coarse_cache:
        _coarse_cache.clear()
        _node_fields.clear()
        _coarse_cache[key] = _coarse(site, p)
    return key, _coarse_cache[key]


def cost_matrices(site: Site, p: CostParams, nodes: list[Stop]):
    """Pairwise O2 / time / battery between nodes on the coarse grid. Each node's Dijkstra field is
    cached, so changing the target only costs one new search; new searches run in parallel."""
    key, (elev, passable, rough, hazard, slope_frac) = _coarse_cached(site, p)
    P = p.as_array()
    cells = []
    for s in nodes:
        r, c = min(s.row // COARSE, passable.shape[0] - 1), min(s.col // COARSE, passable.shape[1] - 1)
        if not passable[r, c]:
            rr, cc = np.nonzero(passable)
            k = np.argmin((rr - r) ** 2 + (cc - c) ** 2)
            r, c = int(rr[k]), int(cc[k])
        cells.append((r, c))

    def field(rc):
        _, t, o, b, _ = graph.dijkstra(elev, passable, rough, hazard, slope_frac, site.grid.res_m * COARSE, P,
                                       graph.ENERGY, 0.0, rc[0], rc[1], False, np.inf)
        return rc, (o.astype(np.float32), t.astype(np.float32), b.astype(np.float32))

    missing = [rc for rc in dict.fromkeys(cells) if (key, rc) not in _node_fields]
    if missing:
        with ThreadPoolExecutor(max_workers=8) as ex:
            for rc, f in ex.map(field, missing):
                _node_fields[(key, rc)] = f
    n = len(nodes)
    o2, tt, bb = (np.full((n, n), np.inf) for _ in range(3))
    for i, rc in enumerate(cells):
        o, t, b = _node_fields[(key, rc)]
        for j, (r2, c2) in enumerate(cells):
            o2[i, j], tt[i, j], bb[i, j] = o[r2, c2], t[r2, c2], b[r2, c2]
    return o2, tt, bb


def _tour_cost(tour, M, stop_extra):
    return sum(M[a, b] for a, b in zip(tour[:-1], tour[1:])) + stop_extra * (len(tour) - 2)


def _two_opt(tour: list[int], M: np.ndarray) -> list[int]:
    best = tour[:]
    improved = True
    while improved:
        improved = False
        for i, j in itertools.combinations(range(1, len(best) - 1), 2):
            cand = best[:i] + best[i:j + 1][::-1] + best[j + 1:]
            if _tour_cost(cand, M, 0) < _tour_cost(best, M, 0) - 1e-12:
                best, improved = cand, True
    return best


def orienteer(site: Site, p: CostParams, start: Stop, required: list[Stop], end: Stop,
              o2_start: float | None = None, batt_start: float | None = None, max_hotspots: int = 12):
    o2_cap = (p.initial_o2_kg if o2_start is None else o2_start) - p.initial_o2_kg * p.o2_reserve_frac
    b_cap = (p.battery_wh if batt_start is None else batt_start) - p.battery_wh * p.batt_reserve_frac
    t_cap = p.max_duration_s
    hs = [Stop(h["row"], h["col"], f"Science hotspot {h['id'][2:]}", "hotspot", float(h["value"]), h["id"])
          for h in site.hotspots]
    nodes = [start, *required, end, *hs]
    O2, T, B = cost_matrices(site, p, nodes)
    st, so2, sb = stop_cost(p)
    n_fixed = 2 + len(required)
    tour = [0, *range(1, 1 + len(required)), 1 + len(required)]
    if len(required) > 1:
        tour = _two_opt(tour, O2)

    def totals(tr):
        return (_tour_cost(tr, O2, so2), _tour_cost(tr, T, st), _tour_cost(tr, B, sb))

    def fits(tr, slack=0.9):
        o, t, b = totals(tr)
        return o <= slack * o2_cap and b <= slack * b_cap and t <= slack * t_cap

    pool = set(range(n_fixed, len(nodes)))
    while pool and sum(1 for k in tour if k >= n_fixed) < max_hotspots:
        best = None
        base = totals(tour)[0]
        for h in pool:
            for pos in range(1, len(tour)):
                cand = tour[:pos] + [h] + tour[pos:]
                if not fits(cand):
                    continue
                added = totals(cand)[0] - base
                ratio = nodes[h].value / max(added, 1e-6)
                if best is None or ratio > best[0]:
                    best = (ratio, cand, h)
        if best is None:
            break
        tour = _two_opt(best[1], O2)
        pool.discard(best[2])

    # exact verification with fine-grid A*
    while True:
        route = build_route(site, p, "science", [nodes[k] for k in tour], o2_start, batt_start)
        if route.totals["feasible"] or not any(k >= n_fixed for k in tour):
            return route
        worst = min((k for k in tour if k >= n_fixed), key=lambda k: nodes[k].value)
        tour = [k for k in tour if k != worst]


def plan_pareto(site: Site, p: CostParams, start: Stop, targets: list[Stop], end: Stop, objectives=("safest", "fastest", "science"),
                o2_start: float | None = None, batt_start: float | None = None) -> list[Route]:
    t0 = time.perf_counter()
    for t in targets:
        t.value = float(site.science[t.row, t.col])
    def one(obj: str) -> Route:
        if obj == "science":
            return orienteer(site, p, start, targets, end, o2_start, batt_start)
        return build_route(site, p, obj, [start, *targets, end], o2_start, batt_start)

    # numba kernels release the GIL, so the three objectives search in parallel
    with ThreadPoolExecutor(max_workers=len(objectives)) as ex:
        routes = list(ex.map(one, objectives))
    for r in routes:
        r.totals["pareto_compute_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    return routes
