"""Cached single-source fields from the habitat, so habitat <-> anywhere legs need no new search.

Most EVA legs start or end at the habitat. One forward Dijkstra (habitat -> all cells) and one
reverse Dijkstra (all cells -> habitat) per objective answer every such leg by walking the
predecessor array. Fields are cached per (objective, params, habitat) and warmed at API start.
"""
from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass

import numpy as np

from planner import graph
from planner.cost import CostParams
from planner.site import Site


@dataclass
class Field:
    cost: np.ndarray
    pred: np.ndarray


_cache: dict[str, Field] = {}
_locks: dict[str, threading.Lock] = {}
_guard = threading.Lock()


def _key(p: CostParams, objective: int, src: tuple[int, int], reverse: bool) -> str:
    return hashlib.sha1(repr((p.as_array().tobytes(), p.max_slope_deg, p.hazard_weight_safest, objective, src, reverse)).encode()).hexdigest()


def get(site: Site, p: CostParams, objective: int, src: tuple[int, int], reverse: bool) -> Field:
    k = _key(p, objective, src, reverse)
    with _guard:
        lock = _locks.setdefault(k, threading.Lock())
    with lock:                                  # concurrent requests wait for one computation
        if k not in _cache:
            cost, _, _, _, pred = graph.dijkstra(site.elev, site.passable(p.max_slope_deg), site.rough_norm, site.hazard,
                                                 site.slope_frac(p.max_slope_deg), site.grid.res_m, p.as_array(), objective,
                                                 p.hazard_weight_safest, src[0], src[1], reverse, np.inf)
            _cache[k] = Field(cost=cost, pred=pred)
            while len(_cache) > 24:
                _cache.pop(next(iter(_cache)))
        return _cache[k]


def path_from_field(f: Field, W: int, a: tuple[int, int], b: tuple[int, int], reverse: bool) -> np.ndarray | None:
    """Cell path a -> b using a field rooted at a (forward) or at b (reverse)."""
    if reverse:                                  # field rooted at b: follow pred from a towards b
        u, goal, out = a[0] * W + a[1], b[0] * W + b[1], []
        while u != -1:
            out.append(u)
            if u == goal:
                return np.array(out, dtype=np.int64)
            u = int(f.pred[u])
        return None
    u, start, out = b[0] * W + b[1], a[0] * W + a[1], []
    while u != -1:                               # field rooted at a: follow pred from b back to a
        out.append(u)
        if u == start:
            return np.array(out[::-1], dtype=np.int64)
        u = int(f.pred[u])
    return None
