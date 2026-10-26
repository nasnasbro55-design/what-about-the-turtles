"""Heat map tests on a synthetic NDVI image - no internet needed.  python3 -m pytest -q"""
import json

import numpy as np
import pytest

rasterio = pytest.importorskip("rasterio")
from rasterio.transform import from_origin  # noqa: E402

from turtles.planner.habitat import (bbox_around, edge_distance_m, heatmap_geojson, likelihood,  # noqa: E402
                                     save, to_cells)

CRS = "EPSG:32618"                                # UTM 18N, same as NAIP over northern Virginia
TR = from_origin(270000, 4300000, 0.6, 0.6)       # 0.6 m pixels, like NAIP


def fake_ndvi():
    """300 x 300 px (180 m): woods on the left third, bare dirt elsewhere, a grass strip on the right edge."""
    a = np.full((300, 300), 0.05, dtype="float32")
    a[:, :100] = 0.7
    a[:, 280:] = 0.35
    return a


def test_bbox_is_buffer_sized():
    w, s, e, n = bbox_around(38.8, -77.6, 300)
    assert n - s == pytest.approx(600 / 111_320) and w < -77.6 < e


def test_cells_average_to_10m():
    cells, ct = to_cells(fake_ndvi(), TR)
    assert cells.shape == (17, 17) and ct.a == pytest.approx(10.2)  # 17 px x 0.6 m per cell
    assert cells[0, 0] == pytest.approx(0.7) and cells[0, 8] == pytest.approx(0.05)


def test_edge_distance():
    hab = np.zeros((1, 10), bool)
    hab[0, 0] = True
    d = edge_distance_m(hab, 10, 50)
    assert list(d[0, :6]) == [0, 10, 20, 30, 40, 50] and np.isinf(d[0, 6])


def test_likelihood_woods_high_open_dirt_low():
    cells, _ = to_cells(fake_ndvi(), TR)
    lik, _, _ = likelihood(cells, 10)
    assert lik.max() == pytest.approx(1.0)
    woods, near, far = lik[8, 0], lik[8, 6], lik[8, 11]
    assert woods > near > far, (woods, near, far)


def test_geojson_matches_mock_shape(tmp_path):
    ndvi = fake_ndvi()
    cells, ct = to_cells(ndvi, TR)
    fc = heatmap_geojson(cells, ct, CRS, "test", "2023")
    assert fc["type"] == "FeatureCollection" and fc["features"]
    f = fc["features"][0]
    ring = f["geometry"]["coordinates"][0]
    assert len(ring) == 5 and ring[0] == ring[-1]
    assert -78 < ring[0][0] < -77 and 38 < ring[0][1] < 40      # lon, lat order, lands in Virginia
    assert 0 <= f["properties"]["likelihood"] <= 1 and f["properties"]["reasons"]
    save(ndvi, TR, CRS, fc, tmp_path)
    assert json.loads((tmp_path / "heatmap.geojson").read_text())["features"]
    assert (tmp_path / "ndvi.tif").exists() and (tmp_path / "ndvi_preview.png").exists()
