"""Consumables cost model: terrain step -> time (s), O2 (kg), battery (Wh).

All parameters come from config/model.yaml (see docs/ASSUMPTIONS.md).
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

import numpy as np

from pipeline.geo import load_yaml


def _v(d: dict, *path):
    for p in path:
        d = d[p]
    return d["value"]


@dataclass(frozen=True)
class CostParams:
    minetti: tuple[float, ...]
    gradient_clamp: float
    body_mass_kg: float
    suit_mass_kg: float
    gravity_metabolic_factor: float
    suit_penalty: float
    baseline_metabolic_w: float
    stop_metabolic_w: float
    stop_s: float
    tobler_peak_kmh: float
    suit_speed_factor: float
    min_speed_ms: float
    max_slope_deg: float
    roughness_weight: float
    hazard_weight_safest: float
    kj_per_l_o2: float
    o2_density: float
    initial_o2_kg: float
    o2_reserve_frac: float
    battery_wh: float
    suit_power_w: float
    batt_reserve_frac: float
    o2_leak_kg_per_h: float = 0.0
    speed_mult: float = 1.0
    max_duration_s: float = 8 * 3600
    timestep_s: float = 300
    version: str = ""
    hazard: str | None = None
    overrides: dict = field(default_factory=dict, compare=False, hash=False)

    @classmethod
    def from_config(cls, overrides: dict | None = None, hazard: str | None = None) -> CostParams:
        m = load_yaml("model.yaml")
        b = m["battery"]
        p = cls(
            minetti=tuple(_v(m, "walking", "minetti_coeffs")),
            gradient_clamp=_v(m, "walking", "gradient_clamp"),
            body_mass_kg=_v(m, "walking", "body_mass_kg"),
            suit_mass_kg=_v(m, "walking", "suit_mass_kg"),
            gravity_metabolic_factor=_v(m, "walking", "gravity_metabolic_factor"),
            suit_penalty=_v(m, "walking", "suit_penalty"),
            baseline_metabolic_w=_v(m, "walking", "baseline_metabolic_w"),
            stop_metabolic_w=_v(m, "walking", "science_stop_metabolic_w"),
            stop_s=_v(m, "walking", "science_stop_min") * 60.0,
            tobler_peak_kmh=_v(m, "speed", "tobler_peak_kmh"),
            suit_speed_factor=_v(m, "speed", "suit_speed_factor"),
            min_speed_ms=_v(m, "speed", "min_speed_ms"),
            max_slope_deg=_v(m, "terrain", "max_slope_deg"),
            roughness_weight=_v(m, "terrain", "roughness_weight"),
            hazard_weight_safest=_v(m, "terrain", "hazard_weight_safest"),
            kj_per_l_o2=_v(m, "oxygen", "kj_per_litre_o2"),
            o2_density=_v(m, "oxygen", "o2_density_kg_m3"),
            initial_o2_kg=_v(m, "oxygen", "initial_o2_kg"),
            o2_reserve_frac=_v(m, "oxygen", "reserve_frac"),
            battery_wh=b["capacity_wh"]["value"],
            suit_power_w=b["suit_baseline_w"]["value"] + b["comms_w"]["value"] + b["heater_w"]["value"],
            batt_reserve_frac=b["reserve_frac"]["value"],
            max_duration_s=_v(m, "eva", "max_duration_h") * 3600.0,
            timestep_s=_v(m, "eva", "envelope_timestep_s"),
            version=m["version"],
        )
        if hazard:
            h = m["hazards"][hazard]
            if hazard == "dust_storm":
                p = replace(p, speed_mult=h["speed_mult"]["value"], suit_power_w=p.suit_power_w + h["extra_power_w"]["value"],
                            o2_reserve_frac=p.o2_reserve_frac + h["extra_reserve_frac"]["value"],
                            batt_reserve_frac=p.batt_reserve_frac + h["extra_reserve_frac"]["value"])
            elif hazard == "suit_fault":
                p = replace(p, o2_leak_kg_per_h=h["o2_leak_kg_per_h"]["value"],
                            o2_reserve_frac=p.o2_reserve_frac + h["extra_reserve_frac"]["value"])
            else:
                raise ValueError(f"unknown hazard {hazard!r}")
            p = replace(p, hazard=hazard)
        if overrides:
            allowed = {k: v for k, v in overrides.items() if k in cls.__dataclass_fields__ and k not in ("overrides", "version")}
            p = replace(p, **allowed, overrides=allowed)
        return p

    # --- derived constants used by the numba kernels -------------------------------------------
    @property
    def mass_kg(self) -> float:
        return self.body_mass_kg + self.suit_mass_kg

    @property
    def kg_o2_per_joule(self) -> float:
        return self.o2_density / (self.kj_per_l_o2 * 1e6)  # (kg/m3) / (J/m3)

    @property
    def walk_scale(self) -> float:
        """Joules per (J/kg/m * m) — multiplies the Minetti cost to get metabolic J per metre per unit C."""
        return self.mass_kg * self.gravity_metabolic_factor * self.suit_penalty

    @property
    def o2_rate_rest_kg_s(self) -> float:
        """O2 consumed per second regardless of walking (baseline metabolism + leak)."""
        return self.baseline_metabolic_w * self.kg_o2_per_joule + self.o2_leak_kg_per_h / 3600.0

    @property
    def usable_o2_kg(self) -> float:
        return self.initial_o2_kg * (1 - self.o2_reserve_frac)

    @property
    def usable_batt_wh(self) -> float:
        return self.battery_wh * (1 - self.batt_reserve_frac)

    def as_array(self) -> np.ndarray:
        """Packed parameters for numba kernels (see graph.py for the index map)."""
        return np.array([*self.minetti, self.gradient_clamp, self.walk_scale, self.kg_o2_per_joule, self.o2_rate_rest_kg_s,
                         self.tobler_peak_kmh / 3.6 * self.suit_speed_factor * self.speed_mult, self.min_speed_ms,
                         self.roughness_weight, self.suit_power_w], dtype=np.float64)


# --- scalar reference implementations (used by tests and for per-segment reporting) ----------------

def minetti_cost(i, coeffs) -> np.ndarray:
    """Metabolic cost of walking, J kg^-1 m^-1, Minetti et al. 2002. i = gradient (rise/run)."""
    a5, a4, a3, a2, a1, a0 = coeffs
    i = np.asarray(i, dtype=np.float64)
    return ((((a5 * i + a4) * i + a3) * i + a2) * i + a1) * i + a0


def tobler_speed(i, p: CostParams) -> np.ndarray:
    """Walking speed (m/s): Tobler hiking function scaled for a suited walker."""
    v = p.tobler_peak_kmh / 3.6 * np.exp(-3.5 * np.abs(np.asarray(i) + 0.05)) * p.suit_speed_factor * p.speed_mult
    return np.maximum(v, p.min_speed_ms)


def step_cost(dist_m, dz_m, p: CostParams, roughness_norm=0.0):
    """Cost of walking a straight step. Returns (time_s, o2_kg, batt_wh)."""
    dist_m = np.asarray(dist_m, dtype=np.float64)
    i = np.clip(np.asarray(dz_m) / np.maximum(dist_m, 1e-9), -p.gradient_clamp, p.gradient_clamp)
    terrain = 1.0 + p.roughness_weight * np.asarray(roughness_norm)
    t = dist_m / tobler_speed(i, p) * terrain
    walk_j = minetti_cost(i, p.minetti) * p.walk_scale * dist_m * terrain
    o2 = walk_j * p.kg_o2_per_joule + t * p.o2_rate_rest_kg_s
    batt = t * p.suit_power_w / 3600.0
    return t, o2, batt


def stop_cost(p: CostParams):
    """Cost of a science stop: (time_s, o2_kg, batt_wh)."""
    t = p.stop_s
    o2 = t * (p.stop_metabolic_w * p.kg_o2_per_joule + p.o2_leak_kg_per_h / 3600.0)
    return t, o2, t * p.suit_power_w / 3600.0
