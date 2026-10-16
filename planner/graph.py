"""Numba-accelerated 8-connected grid search: A* (point to point) and Dijkstra (cost fields).

Edge costs are directional: walking uphill and downhill cost differently, so the
reverse search used for cost-to-home evaluates every edge in the physical direction
of travel (neighbour -> settled cell).

Packed parameter array `P` (CostParams.as_array):
  0..5  Minetti coefficients a5..a0     6  gradient clamp
  7     walk scale (kg)                 8  kg O2 per joule
  9     O2 rest rate (kg/s)             10 v0 = Tobler peak * suit factor * hazard mult (m/s)
  11    min speed (m/s)                 12 roughness weight
  13    suit electrical power (W)
"""
from __future__ import annotations

import heapq
import math

import numba as nb
import numpy as np

# objectives
FASTEST, ENERGY, SAFEST = 0, 1, 2
OBJECTIVES = {"fastest": FASTEST, "energy": ENERGY, "safest": SAFEST, "science": ENERGY}

DR = np.array([-1, -1, -1, 0, 0, 1, 1, 1], dtype=np.int64)
DC = np.array([-1, 0, 1, -1, 1, -1, 0, 1], dtype=np.int64)
SQRT2 = math.sqrt(2.0)


@nb.njit(cache=True, nogil=True, inline="always")
def _edge(P, z0, z1, dist, rough):
    """Physical step from height z0 to z1 over horizontal dist. Returns (t, o2, batt)."""
    i = (z1 - z0) / dist
    clamp = P[6]
    if i > clamp:
        i = clamp
    elif i < -clamp:
        i = -clamp
    c = ((((P[0] * i + P[1]) * i + P[2]) * i + P[3]) * i + P[4]) * i + P[5]
    v = P[10] * math.exp(-3.5 * abs(i + 0.05))
    if v < P[11]:
        v = P[11]
    terrain = 1.0 + P[12] * rough
    t = dist / v * terrain
    o2 = c * P[7] * dist * terrain * P[8] + t * P[9]
    batt = t * P[13] / 3600.0
    return t, o2, batt


@nb.njit(cache=True, nogil=True, inline="always")
def _weight(objective, t, o2, hazard, slope_frac, hazard_w):
    if objective == 0:
        return t
    if objective == 1:
        return o2
    return o2 * (1.0 + hazard_w * hazard) * (1.0 + 2.0 * slope_frac * slope_frac)


@nb.njit(cache=True, nogil=True)
def dijkstra(elev, passable, rough, hazard, slope_frac, res, P, objective, hazard_w, src_r, src_c, reverse, max_cost):
    """Single-source shortest paths. reverse=True gives cost of travelling *to* the source.

    Returns cost (objective units), and the accumulated t_s, o2_kg, batt_wh along each
    optimal path, plus the predecessor index (-1 = none).
    """
    H, W = elev.shape
    N = H * W
    INF = np.inf
    cost = np.full(N, INF)
    acc_t = np.full(N, INF)
    acc_o2 = np.full(N, INF)
    acc_b = np.full(N, INF)
    pred = np.full(N, -1, dtype=np.int64)
    done = np.zeros(N, dtype=np.bool_)
    s = src_r * W + src_c
    cost[s] = 0.0
    acc_t[s] = 0.0
    acc_o2[s] = 0.0
    acc_b[s] = 0.0
    heap = [(0.0, s)]
    while heap:
        d, u = heapq.heappop(heap)
        if done[u]:
            continue
        done[u] = True
        if d > max_cost:
            break
        ur = u // W
        uc = u - ur * W
        for k in range(8):
            vr = ur + DR[k]
            vc = uc + DC[k]
            if vr < 0 or vr >= H or vc < 0 or vc >= W:
                continue
            if not passable[vr, vc]:
                continue
            v = vr * W + vc
            if done[v]:
                continue
            dist = res * (SQRT2 if (DR[k] != 0 and DC[k] != 0) else 1.0)
            rgh = 0.5 * (rough[ur, uc] + rough[vr, vc])
            if reverse:
                t, o2, b = _edge(P, elev[vr, vc], elev[ur, uc], dist, rgh)
            else:
                t, o2, b = _edge(P, elev[ur, uc], elev[vr, vc], dist, rgh)
            w = _weight(objective, t, o2, 0.5 * (hazard[ur, uc] + hazard[vr, vc]),
                        max(slope_frac[ur, uc], slope_frac[vr, vc]), hazard_w)
            nd = d + w
            if nd < cost[v]:
                cost[v] = nd
                acc_t[v] = acc_t[u] + t
                acc_o2[v] = acc_o2[u] + o2
                acc_b[v] = acc_b[u] + b
                pred[v] = u
                heapq.heappush(heap, (nd, v))
    return cost.reshape(H, W), acc_t.reshape(H, W), acc_o2.reshape(H, W), acc_b.reshape(H, W), pred


@nb.njit(cache=True, nogil=True)
def astar(elev, passable, rough, hazard, slope_frac, res, P, objective, hazard_w, s_r, s_c, g_r, g_c, h_per_m):
    """Point-to-point A* with an admissible octile-distance heuristic (h_per_m = min cost per metre)."""
    H, W = elev.shape
    N = H * W
    g = np.full(N, np.inf)
    pred = np.full(N, -1, dtype=np.int64)
    done = np.zeros(N, dtype=np.bool_)
    s = s_r * W + s_c
    goal = g_r * W + g_c
    g[s] = 0.0
    heap = [(0.0, s)]
    while heap:
        _, u = heapq.heappop(heap)
        if done[u]:
            continue
        done[u] = True
        if u == goal:
            break
        ur = u // W
        uc = u - ur * W
        for k in range(8):
            vr = ur + DR[k]
            vc = uc + DC[k]
            if vr < 0 or vr >= H or vc < 0 or vc >= W:
                continue
            if not passable[vr, vc]:
                continue
            v = vr * W + vc
            if done[v]:
                continue
            dist = res * (SQRT2 if (DR[k] != 0 and DC[k] != 0) else 1.0)
            t, o2, b = _edge(P, elev[ur, uc], elev[vr, vc], dist, 0.5 * (rough[ur, uc] + rough[vr, vc]))
            w = _weight(objective, t, o2, 0.5 * (hazard[ur, uc] + hazard[vr, vc]),
                        max(slope_frac[ur, uc], slope_frac[vr, vc]), hazard_w)
            nd = g[u] + w
            if nd < g[v]:
                g[v] = nd
                pred[v] = u
                dr = abs(vr - g_r)
                dc = abs(vc - g_c)
                octile = (max(dr, dc) + (SQRT2 - 1.0) * min(dr, dc)) * res
                heapq.heappush(heap, (nd + octile * h_per_m, v))
    if pred[goal] == -1 and goal != s:
        return np.empty(0, dtype=np.int64), np.inf
    n = 0
    u = goal
    while u != -1:
        n += 1
        u = pred[u]
    path = np.empty(n, dtype=np.int64)
    u = goal
    for i in range(n - 1, -1, -1):
        path[i] = u
        u = pred[u]
    return path, g[goal]


def min_cost_per_metre(P: np.ndarray, objective: int) -> float:
    """Lower bound of edge weight per metre over all gradients (admissible A* heuristic)."""
    best = np.inf
    for i in np.linspace(-P[6], P[6], 361):
        t, o2, _ = _edge(P, 0.0, i * 10.0, 10.0, 0.0)
        best = min(best, (t if objective == FASTEST else o2) / 10.0)
    return float(best) * 0.999
