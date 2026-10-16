import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from pipeline.geo import Grid
from planner.site import Site


@pytest.fixture(scope="session")
def synthetic_dtm(tmp_path_factory):
    """Tiny SYNTHETIC DTM (tilted plane + hill) in a Mars eqc CRS, for window/CRS tests."""
    path = tmp_path_factory.mktemp("fixtures") / "SYNTHETIC_dtm.tif"
    g = Grid.from_config()
    yy, xx = np.mgrid[0:64, 0:80].astype(np.float32)
    z = -2500 + 0.1 * xx + 20 * np.exp(-((xx - 40) ** 2 + (yy - 32) ** 2) / 120)
    with rasterio.open(path, "w", driver="GTiff", width=80, height=64, count=1, dtype="float32", crs=g.crs,
                       transform=from_origin(0, 1_093_000, 2, 2)) as dst:
        dst.write(z, 1)
    return path


def synthetic_site(shape=(60, 80), res=2.0, wall_col=None, slope_x=0.0):
    """SYNTHETIC planner site: flat or tilted plane, optional impassable wall with a gap."""
    from pipeline.geo import MARS_RADIUS_M

    H, W = shape
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float64)
    elev = -2500 + slope_x * xx * res
    slope = np.full(shape, np.degrees(np.arctan(slope_x)), dtype=np.float32)
    if wall_col is not None:
        slope[: H - 10, wall_col] = 60.0
    ky = MARS_RADIUS_M * np.pi / 180.0
    lat1 = 18.44 + H * res / ky
    kx = ky * np.cos(np.radians(0.5 * (18.44 + lat1)))
    grid = Grid(18.44, lat1, 77.40, 77.40 + W * res / kx, res)
    assert grid.shape == shape
    site = Site(grid=grid, elev=elev, slope=slope, rough_norm=np.zeros(shape), hazard=np.zeros(shape),
                science=np.zeros(shape, dtype=np.float32), minerals={},
                habitat={"row": H // 2, "col": 5, "name": "SYNTHETIC habitat"}, targets=[], hotspots=[])
    return site
