"""Graph search, envelope and point-of-no-return on SYNTHETIC sites."""
import numpy as np
import pytest

from planner import envelope, graph
from planner.cost import CostParams, step_cost
from planner.routes import Stop, build_route
from tests.conftest import synthetic_site


@pytest.fixture(scope="module")
def p():
    return CostParams.from_config()


def _cells(site, path):
    W = site.grid.shape[1]
    return path // W, path % W


def test_astar_straight_on_flat(p):
    site = synthetic_site()
    P = p.as_array()
    path, cost = graph.astar(site.elev, site.passable(25), site.rough_norm, site.hazard, site.slope_frac(25),
                             2.0, P, graph.FASTEST, 0.0, 30, 5, 30, 75, graph.min_cost_per_metre(P, graph.FASTEST))
    r, c = _cells(site, path)
    assert np.all(r == 30) and len(path) == 71
    assert cost == pytest.approx(step_cost(140.0, 0.0, p)[0], rel=1e-9)


def test_astar_equals_dijkstra(p):
    site = synthetic_site(slope_x=0.05, wall_col=40)
    P = p.as_array()
    args = (site.elev, site.passable(25), site.rough_norm, site.hazard, site.slope_frac(25), 2.0, P, graph.ENERGY, 0.0)
    cost, *_ = graph.dijkstra(*args, 10, 5, False, np.inf)
    path, c2 = graph.astar(*args, 10, 5, 12, 70, graph.min_cost_per_metre(P, graph.ENERGY))
    assert c2 == pytest.approx(cost[12, 70], rel=1e-9)
    r, c = _cells(site, path)
    assert not np.any((c == 40) & (r < 50))      # never crosses the wall, goes through the gap


def test_reverse_dijkstra_is_directional(p):
    site = synthetic_site(slope_x=0.08)            # uphill towards +x
    P = p.as_array()
    args = (site.elev, site.passable(25), site.rough_norm, site.hazard, site.slope_frac(25), 2.0, P, graph.ENERGY, 0.0)
    _, _, to_home, _, _ = graph.dijkstra(*args, 30, 5, True, np.inf)    # cost to walk TO (30,5)
    _, _, from_home, _, _ = graph.dijkstra(*args, 30, 5, False, np.inf)  # cost to walk FROM (30,5)
    # walking home from the far east is downhill, so cheaper than walking out
    assert to_home[30, 75] < from_home[30, 75]


def test_envelope_shrinks_and_pnr(p):
    site = synthetic_site(shape=(40, 400))
    home = Stop(20, 5, "home", "habitat")
    far = Stop(20, 395, "far", "target")
    # a suit with almost no oxygen: walking 780 m out cannot be completed with a return
    tight = CostParams.from_config({"initial_o2_kg": 0.012, "o2_reserve_frac": 0.0})
    r = build_route(site, tight, "fastest", [home, far], None, None)
    assert "point_of_no_return" in r.margins
    pnr = r.margins["point_of_no_return"]["index"]
    # by the PNR the walker has used about half of the O2 (out + back)
    assert 0.3 < r.seg["o2_kg"][pnr] / 0.012 < 0.6
    hf = envelope.home_field(site, tight, (20, 5))
    T = r.deadline
    areas = [(T >= t).sum() for t in np.linspace(0, r.seg["t_s"][-1], 6)]
    assert all(a >= b for a, b in zip(areas, areas[1:])) and areas[0] > areas[-1]
    assert np.isfinite(hf.o2[20, 395])


def test_feasible_round_trip_has_no_pnr(p):
    site = synthetic_site()
    home = Stop(30, 5, "home", "habitat")
    tgt = Stop(30, 60, "t", "target")
    r = build_route(site, p, "safest", [home, tgt, home])
    assert r.totals["feasible"] and "point_of_no_return" not in r.margins
    assert r.totals["stops"] == 1
    assert np.all(np.diff(r.seg["t_s"]) >= 0) and np.all(np.diff(r.seg["o2_kg"]) > 0)
