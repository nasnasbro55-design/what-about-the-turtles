"""F4 coverage tests - synthetic, no photos or internet needed.  python3 -m pytest -q"""
import math

import numpy as np
from PIL import Image

from turtles.planner.coverage import coverage, ground_offsets, green_fraction, patches

LAT0, LON0 = 38.79, -77.65
KL = 111_320 * math.cos(math.radians(LAT0))
SQUARE = [[LON0, LAT0], [LON0 + 100 / KL, LAT0], [LON0 + 100 / KL, LAT0 + 100 / 111_320], [LON0, LAT0 + 100 / 111_320], [LON0, LAT0]]


def test_nadir_footprint_matches_camera():
    e, n, r = ground_offsets(np.array([-2640, 2640]), np.array([0, 0]), 15, -90, 0)
    assert abs((e[1] - e[0]) - 21.3) < 0.2 and np.allclose(n, 0, atol=1e-6) and abs(r[0] - 18.2) < 0.2


def test_tilted_camera_looks_ahead_and_yaw_rotates():
    _, n, _ = ground_offsets(np.array([0.0]), np.array([0.0]), 15, -75, 0)
    assert abs(n[0] - 15 / math.tan(math.radians(75))) < 0.01   # center ray lands ~4 m ahead
    e, n2, _ = ground_offsets(np.array([0.0]), np.array([0.0]), 15, -75, 90)
    assert abs(e[0] - n[0]) < 1e-6 and abs(n2[0]) < 1e-6        # facing east -> ahead is east


def test_sky_rays_are_dropped():
    _, _, r = ground_offsets(np.array([0.0]), np.array([-3000.0]), 15, -10, 0)
    assert np.isnan(r[0])


def test_green_fraction_tells_brush_from_dirt():
    img = Image.new("RGB", (64, 32), (150, 120, 90)); img.paste((40, 140, 40), (0, 0, 32, 32))
    g = green_fraction(img, (2, 1))
    assert g[0, 0] > 0.9 and g[0, 1] < 0.1


def test_coverage_percentages():
    # samples cover the south half of a 100 m square; a quarter of that half is green brush
    pts = [[LAT0 + y / 111_320, LON0 + x / KL, 0.9 if x < 25 else 0.1] for x in range(1, 100, 2) for y in range(1, 50, 2)]
    cov = coverage(np.array(pts), SQUARE)
    p = cov["pct"]
    assert abs(p["not_seen"] - 50) < 6 and abs(p["vegetation"] - 12.5) < 4 and abs(sum(p.values()) - 100) < 0.5


def test_patches_group_neighbours():
    st = np.array([["not_seen", "not_seen", ""], ["", "", ""], ["", "vegetation", "vegetation"]], object)
    assert sorted(len(p) for p in patches(st)) == [2, 2]
