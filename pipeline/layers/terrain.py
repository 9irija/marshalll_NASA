"""Terrain-derived layers: slope, roughness and the rock-hazard proxy."""
from __future__ import annotations

import numpy as np
from scipy import ndimage


def slope_deg(z: np.ndarray, res_m: float) -> np.ndarray:
    """Slope in degrees from central differences. NaNs propagate."""
    dzdy, dzdx = np.gradient(z.astype(np.float64), res_m)
    return np.degrees(np.arctan(np.hypot(dzdx, dzdy))).astype(np.float32)


def _nan_uniform(a: np.ndarray, size: int) -> np.ndarray:
    valid = np.isfinite(a)
    filled = np.where(valid, a, 0.0)
    num = ndimage.uniform_filter(filled, size, mode="nearest")
    den = ndimage.uniform_filter(valid.astype(np.float64), size, mode="nearest")
    with np.errstate(invalid="ignore", divide="ignore"):
        out = num / den
    out[~valid] = np.nan
    return out


def roughness_m(z: np.ndarray, res_m: float, window_m: float) -> np.ndarray:
    """Local standard deviation of detrended elevation (m) in a window of window_m."""
    size = max(3, int(round(window_m / res_m)) | 1)
    detr = z - _nan_uniform(z, size)
    return np.sqrt(np.maximum(_nan_uniform(detr * detr, size), 0.0)).astype(np.float32)


def local_std(a: np.ndarray, size: int) -> np.ndarray:
    m = _nan_uniform(a, size)
    return np.sqrt(np.maximum(_nan_uniform(a * a, size) - m * m, 0.0)).astype(np.float32)


def normalise(a: np.ndarray, lo_pct: float = 50, hi_pct: float = 99, floor: float | None = None) -> np.ndarray:
    """Map the lo..hi percentile range of finite values to 0..1 (clipped).
    `floor` raises the low anchor, e.g. 0 for band depths where <= 0 means no absorption."""
    v = a[np.isfinite(a)]
    if v.size == 0:
        return np.full_like(a, np.nan, dtype=np.float32)
    lo, hi = np.percentile(v, [lo_pct, hi_pct])
    if floor is not None:
        lo = max(lo, floor)
    out = (a - lo) / max(hi - lo, 1e-9)
    return np.clip(out, 0.0, 1.0).astype(np.float32)


def rock_hazard(roughness: np.ndarray, texture: np.ndarray) -> np.ndarray:
    """Proxy for rock abundance, 0..1: DTM roughness (60 %) + orthoimage texture (40 %).

    Boulders raise metre-scale relief and cast shadows that raise local brightness
    variance. This is a derived proxy, not a rock-count product.
    """
    r = normalise(roughness, 10, 99)
    t = normalise(texture, 10, 99)
    t = np.where(np.isfinite(t), t, r)
    return np.clip(0.6 * r + 0.4 * t, 0.0, 1.0).astype(np.float32)
