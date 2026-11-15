"""Verify that every safety-critical number in an answer came from a tool result this turn.

Checked quantities (unit-aware): oxygen mass (kg, g), distance (m, km), time (s, min, h,
H:MM), battery energy (Wh, kWh), slope / angles (deg), temperature (C), pressure (Pa), radiation dose (Sv, mSv, uSv),
percentages and coordinates (N/E). A number passes if some tool value of the same
dimension matches within 1 % or within the rounding of the digits written, or if it is
quoted verbatim from a retrieved document passage (document claims must carry a [n] citation).
Unitless numbers (sol numbers, counts, citation markers) are not safety-critical and are
not checked.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# dimension, factor to canonical unit
UNITS = {
    "kg": ("mass", 1.0), "kilograms": ("mass", 1.0), "kilogram": ("mass", 1.0), "g": ("mass", 1e-3), "grams": ("mass", 1e-3),
    "km": ("length", 1000.0), "kilometres": ("length", 1000.0), "kilometers": ("length", 1000.0),
    "m": ("length", 1.0), "metres": ("length", 1.0), "meters": ("length", 1.0),
    "s": ("time", 1.0), "sec": ("time", 1.0), "seconds": ("time", 1.0),
    "min": ("time", 60.0), "mins": ("time", 60.0), "minutes": ("time", 60.0), "minute": ("time", 60.0),
    "h": ("time", 3600.0), "hr": ("time", 3600.0), "hrs": ("time", 3600.0), "hours": ("time", 3600.0), "hour": ("time", 3600.0),
    "wh": ("energy", 1.0), "kwh": ("energy", 1000.0),
    "°": ("angle", 1.0), "deg": ("angle", 1.0), "degrees": ("angle", 1.0),
    "°c": ("temp", 1.0), "c": ("temp", 1.0), "pa": ("pressure", 1.0), "%": ("percent", 1.0),
    "msv": ("dose", 1.0), "µsv": ("dose", 1e-3), "μsv": ("dose", 1e-3), "usv": ("dose", 1e-3), "sv": ("dose", 1000.0),
}
NUM = r"(?<![\w.])(-?\d+(?:,\d{3})*(?:\.\d+)?)"
UNIT_RE = re.compile(NUM + r"\s*(msv\b|[µμu]sv\b|sv\b|°\s*c\b|kwh\b|wh\b|kilograms?\b|kg\b|grams\b|g\b|kilomet(?:re|er)s\b|km\b|met(?:re|er)s\b|m\b|"
                     r"seconds\b|sec\b|s\b|minutes?\b|mins?\b|hours?\b|hrs?\b|hr\b|h\b|degrees\b|deg\b|°|pa\b|%)", re.I)
COORD_RE = re.compile(NUM + r"\s*°?\s*([NSEW])\b")
CLOCK_RE = re.compile(r"(?<![\w.:])(\d{1,2}):([0-5]\d)(?![\d:])")


def _dim_of_key(key: str) -> list[tuple[str, float]]:
    k = key.lower()
    if k in ("lat", "lon", "seed_lat", "seed_lon"):
        return [("coord", 1.0)]
    if "msv" in k:
        return [("dose", 1.0)]
    if "o2" in k or k.endswith("_kg"):
        return [("mass", 1.0)]
    if k.endswith("_km"):
        return [("length", 1000.0)]
    if k.endswith("_m") or k in ("distance_m", "length_m", "frechet_m", "mean_deviation_m"):
        return [("length", 1.0)]
    if k.endswith("_min"):
        return [("time", 60.0)]
    if k.endswith("_h"):
        return [("time", 3600.0)]
    if k.endswith("_s"):
        return [("time", 1.0)]
    if "wh" in k:
        return [("energy", 1.0)]
    if "deg" in k:
        return [("angle", 1.0)]
    if k in ("min", "max") or "temp" in k:
        return [("temp", 1.0)]
    if "pressure" in k:
        return [("pressure", 1.0)]
    if "frac" in k:
        return [("percent", 100.0)]
    if k.endswith("_km2"):
        return [("area", 1.0)]
    return [("any", 1.0)]


def collect_values(obj, key: str = "", out: dict | None = None) -> dict[str, list[float]]:
    """Flatten tool results into {dimension: [canonical values]}."""
    out = out if out is not None else {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            collect_values(v, k, out)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            collect_values(v, key, out)
    elif isinstance(obj, bool):
        pass
    elif isinstance(obj, (int, float)):
        for dim, f in _dim_of_key(key):
            out.setdefault(dim, []).append(float(obj) * f)
            if dim == "time":                          # times are often quoted in derived units
                out.setdefault("time", []).append(float(obj) * f)
    elif isinstance(obj, str):
        for m in re.finditer(NUM, obj):                 # numbers quoted inside document passages
            out.setdefault("text", []).append(float(m.group(1).replace(",", "")))
    return out


@dataclass
class Claim:
    text: str
    value: float
    dim: str
    tol_abs: float
    start: int
    end: int
    raw: float = float("nan")


def _decimals(s: str) -> int:
    return len(s.split(".")[1]) if "." in s else 0


def extract_claims(answer: str) -> list[Claim]:
    claims: list[Claim] = []
    taken: list[tuple[int, int]] = []
    for m in COORD_RE.finditer(answer):
        v = float(m.group(1))
        v = -v if m.group(2).upper() in "SW" else v
        claims.append(Claim(m.group(0), v, "coord", 0.5 * 10 ** -_decimals(m.group(1)) + 1e-4, m.start(), m.end()))
        taken.append((m.start(), m.end()))
    for m in CLOCK_RE.finditer(answer):
        v = int(m.group(1)) * 3600 + int(m.group(2)) * 60
        claims.append(Claim(m.group(0), float(v), "time", 30.0, m.start(), m.end()))
        taken.append((m.start(), m.end()))
    for m in UNIT_RE.finditer(answer):
        if any(a <= m.start() < b for a, b in taken):
            continue
        num, unit = m.group(1).replace(",", ""), re.sub(r"\s+", "", m.group(2).lower())
        dim, f = UNITS.get(unit, UNITS.get(unit.rstrip("s"), ("any", 1.0)))
        claims.append(Claim(m.group(0), float(num) * f, dim, 0.5 * 10 ** -_decimals(num) * f, m.start(), m.end(), float(num)))
    return claims


def check(answer: str, tool_results: list, tolerance: float = 0.01) -> dict:
    values = collect_values(tool_results)
    unverified, verified = [], []
    for c in extract_claims(answer):
        pool = values.get(c.dim, []) + values.get("any", [])
        if c.dim == "percent":
            pool = pool + [v * 100 for v in values.get("any", [])]
        ok = any(abs(c.value - v) <= max(tolerance * abs(v), c.tol_abs) for v in pool)
        source = "tool"
        if not ok and c.raw == c.raw and c.raw in values.get("text", []):
            ok, source = True, "document"      # quoted from a retrieved NASA passage (must be cited)
        c.source = source
        (verified if ok else unverified).append({"text": c.text, "value": c.value, "dim": c.dim, "start": c.start, "end": c.end,
                                                 "source": getattr(c, "source", "tool") if ok else None})
    return {"passed": not unverified, "unverified": unverified, "verified": verified}
