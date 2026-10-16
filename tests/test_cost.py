"""Cost model against hand-computed values (config/model.yaml defaults)."""
import math

import numpy as np
import pytest

from planner.cost import CostParams, minetti_cost, step_cost, stop_cost


@pytest.fixture(scope="module")
def p():
    return CostParams.from_config()


def test_minetti_coefficients_by_hand(p):
    # C(0) = 2.5; C(0.1) and C(-0.1) expanded term by term
    assert minetti_cost(0.0, p.minetti) == pytest.approx(2.5)
    assert minetti_cost(0.1, p.minetti) == pytest.approx(0.002805 - 0.00587 - 0.0768 + 0.519 + 1.96 + 2.5)
    assert minetti_cost(-0.1, p.minetti) == pytest.approx(-0.002805 - 0.00587 + 0.0768 + 0.519 - 1.96 + 2.5)


def test_flat_100m_by_hand(p):
    walk_scale = (80 + 70) * 0.55 * 1.3                       # 107.25 kg
    kg_per_j = 1.429 / 20.1e6                                 # kg O2 per joule
    v = 6.0 / 3.6 * 0.55 * math.exp(-3.5 * 0.05)              # 0.76951 m/s
    t = 100 / v
    o2 = 2.5 * walk_scale * 100 * kg_per_j + 100 * kg_per_j * t
    batt = t * (90 + 10 + 0) / 3600
    got_t, got_o2, got_b = step_cost(100.0, 0.0, p)
    assert got_t == pytest.approx(t) and t == pytest.approx(129.95, abs=0.01)
    assert got_o2 == pytest.approx(o2) and o2 == pytest.approx(2.8301e-3, rel=1e-3)
    assert got_b == pytest.approx(batt) and batt == pytest.approx(3.6097, rel=1e-3)


def test_uphill_costs_more_than_downhill(p):
    up = step_cost(100.0, 10.0, p)
    flat = step_cost(100.0, 0.0, p)
    down = step_cost(100.0, -10.0, p)
    assert up[1] > flat[1] > down[1]          # O2
    assert up[0] > flat[0]                    # slower uphill
    # Tobler peaks at a gentle downhill (s = -0.05)
    assert step_cost(100.0, -5.0, p)[0] < flat[0]


def test_gradient_clamped_outside_minetti_range(p):
    assert step_cost(10.0, 9.0, p)[1] == pytest.approx(step_cost(10.0, 4.5, p)[1] * 1.0, rel=0.25)
    assert np.isfinite(step_cost(1.0, 5.0, p)[0])


def test_roughness_multiplies_cost(p):
    base = step_cost(100.0, 0.0, p, 0.0)
    rough = step_cost(100.0, 0.0, p, 1.0)
    assert rough[0] == pytest.approx(base[0] * (1 + p.roughness_weight))


def test_stop_cost(p):
    t, o2, b = stop_cost(p)
    assert t == 20 * 60
    assert o2 == pytest.approx(1200 * 200 * 1.429 / 20.1e6)
    assert b == pytest.approx(1200 * 100 / 3600)


def test_hazards_change_params():
    base = CostParams.from_config()
    dust = CostParams.from_config(hazard="dust_storm")
    leak = CostParams.from_config(hazard="suit_fault")
    assert dust.speed_mult < 1 and dust.suit_power_w > base.suit_power_w and dust.o2_reserve_frac > base.o2_reserve_frac
    assert leak.o2_rate_rest_kg_s > base.o2_rate_rest_kg_s
    assert step_cost(100.0, 0.0, dust)[0] > step_cost(100.0, 0.0, base)[0]


def test_overrides_only_known_fields():
    p = CostParams.from_config({"max_duration_s": 4 * 3600, "bogus": 1})
    assert p.max_duration_s == 14400 and p.overrides == {"max_duration_s": 14400}
