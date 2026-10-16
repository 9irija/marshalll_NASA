"""Coordinate conventions, layer maths and windowed reads on a synthetic DTM fixture."""
import numpy as np
import pytest
import rasterio
from rasterio.windows import Window

from pipeline.geo import GEOGRAPHIC_CRS, MARS_RADIUS_M, Grid, wrap_lon
from pipeline.layers import terrain


def test_mars_conventions():
    assert MARS_RADIUS_M == 3_396_190.0
    assert "+R=3396190" in GEOGRAPHIC_CRS.to_proj4()
    assert wrap_lon(282.6) == pytest.approx(-77.4)       # 0..360 input -> east-positive -180..180
    assert wrap_lon(-180.0) == pytest.approx(-180.0)
    g = Grid.from_config()
    assert "+R=3396190" in g.crs.to_proj4() and "+proj=eqc" in g.crs.to_proj4()
    assert -180 <= g.min_lon < g.max_lon <= 180


def test_grid_round_trip_and_pyproj_agreement():
    from pyproj import Transformer

    g = Grid.from_config()
    lon, lat = 77.4508, 18.4447
    x, y = g.lonlat_to_xy(lon, lat)
    tr = Transformer.from_crs(GEOGRAPHIC_CRS, g.crs, always_xy=True)
    px, py = tr.transform(lon, lat)
    assert x == pytest.approx(px, abs=1e-3) and y == pytest.approx(py, abs=1e-3)
    lon2, lat2 = g.xy_to_lonlat(x, y)
    assert lon2 == pytest.approx(lon, abs=1e-9) and lat2 == pytest.approx(lat, abs=1e-9)
    r, c = g.lonlat_to_rc(lon, lat)
    lon3, lat3 = g.rc_to_lonlat(r, c)
    assert abs(lon3 - lon) * 56_000 < g.res_m and abs(lat3 - lat) * 59_000 < g.res_m


def test_slope_of_known_plane():
    res = 2.0
    yy, xx = np.mgrid[0:50, 0:60] * res
    z = 0.2 * xx + 0.1 * yy                                   # gradient magnitude sqrt(0.05)
    s = terrain.slope_deg(z, res)
    assert np.allclose(s, np.degrees(np.arctan(np.hypot(0.2, 0.1))), atol=1e-4)


def test_roughness_zero_on_plane_positive_on_bumps():
    res = 1.0
    yy, xx = np.mgrid[0:64, 0:64].astype(float)
    plane = 0.3 * xx
    assert np.nanmax(terrain.roughness_m(plane, res, 6)[8:-8, 8:-8]) < 1e-6
    bumpy = plane + 0.5 * np.sin(xx) * np.cos(yy)
    assert np.nanmean(terrain.roughness_m(bumpy, res, 6)) > 0.1


def test_window_read_matches_full(synthetic_dtm):
    with rasterio.open(synthetic_dtm) as src:
        win = src.read(1, window=Window(10, 20, 16, 8))
        full = src.read(1)
        assert np.array_equal(win, full[20:28, 10:26])
        assert src.crs.to_proj4().count("+R=3396190") == 1


def test_normalise_floor():
    a = np.array([-1.0, 0.0, 0.5, 1.0, np.nan])
    n = terrain.normalise(a, 0, 100, floor=0.0)
    assert n[0] == 0 and n[3] == 1 and np.isnan(n[4])
