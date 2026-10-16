"""Render layers into web assets: colourised RGBA PNG overlays and uint16 height grids."""
from __future__ import annotations

import json
import struct
import zlib
from pathlib import Path

import numpy as np

# Colour ramps chosen to read on top of grey HiRISE imagery.
RAMPS = {
    # slope: transparent-ish green -> amber -> red at the cutoff
    "slope": [(0.0, (46, 160, 120, 0)), (0.25, (120, 200, 120, 110)), (0.6, (240, 190, 60, 190)), (1.0, (220, 50, 50, 230))],
    "hazard": [(0.0, (255, 140, 60, 0)), (0.35, (255, 160, 70, 90)), (0.7, (240, 90, 40, 180)), (1.0, (190, 20, 30, 230))],
    "science": [(0.0, (60, 200, 255, 0)), (0.15, (60, 200, 255, 40)), (0.5, (70, 140, 255, 160)), (1.0, (190, 90, 255, 235))],
    "olivine": [(0.0, (120, 200, 60, 0)), (0.2, (120, 200, 60, 60)), (1.0, (170, 240, 40, 230))],
    "fe_mg_smectite": [(0.0, (60, 150, 255, 0)), (0.2, (60, 150, 255, 60)), (1.0, (40, 110, 255, 230))],
    "carbonate": [(0.0, (250, 90, 200, 0)), (0.2, (250, 90, 200, 60)), (1.0, (255, 60, 190, 235))],
    "hydration": [(0.0, (40, 220, 220, 0)), (0.2, (40, 220, 220, 60)), (1.0, (20, 240, 240, 230))],
    "cost_home": [(0.0, (60, 220, 160, 200)), (0.5, (250, 210, 80, 200)), (1.0, (230, 60, 60, 220))],
}


def colourise(a01: np.ndarray, ramp: str) -> np.ndarray:
    stops = RAMPS[ramp]
    xs = np.array([s[0] for s in stops])
    cols = np.array([s[1] for s in stops], dtype=np.float32)
    v = np.nan_to_num(np.clip(a01, 0, 1), nan=0.0)
    rgba = np.stack([np.interp(v, xs, cols[:, c]) for c in range(4)], axis=-1)
    rgba[~np.isfinite(a01)] = 0
    return rgba.astype(np.uint8)


def write_png(path: Path, img: np.ndarray) -> None:
    """Minimal PNG writer (8-bit gray, gray+alpha, RGB or RGBA) with no imaging dependency."""
    if img.ndim == 2:
        img = img[..., None]
    h, w, c = img.shape
    colour_type = {1: 0, 2: 4, 3: 2, 4: 6}[c]
    raw = b"".join(b"\x00" + img[y].tobytes() for y in range(h))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, colour_type, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b"")
    path.write_bytes(png)


def write_heights(path: Path, z: np.ndarray, bounds: dict, offset: float = -3000.0, scale: float = 0.01) -> dict:
    """uint16 little-endian height grid, row 0 = north. 65535 = no data. Sidecar JSON describes it."""
    q = np.round((z - offset) / scale)
    q = np.where(np.isfinite(q), np.clip(q, 0, 65534), 65535).astype("<u2")
    path.write_bytes(q.tobytes())
    meta = {"width": int(z.shape[1]), "height": int(z.shape[0]), "offset": offset, "scale": scale,
            "nodata": 65535, "bounds": bounds, "file": path.name}
    path.with_suffix(".json").write_text(json.dumps(meta, indent=1))
    return meta
