"""F6 fence-exit simulator tests - synthetic terrain, no internet.  python3 -m pytest -q"""
import math

import numpy as np

from turtles.planner.escape import Fence, choose_gaps, run, sample_dem, simulate, traps

LAT0, LON0 = 38.79, -77.65
KL = 111_320 * math.cos(math.radians(LAT0))
SQ = [[LON0, LAT0], [LON0 + 200 / KL, LAT0], [LON0 + 200 / KL, LAT0 + 200 / 111_320], [LON0, LAT0 + 200 / 111_320], [LON0, LAT0]]
BBOX = np.array([LON0 - 0.001, LAT0 - 0.001, LON0 + 0.004, LAT0 + 0.003])


def dem(fn):
    w, s, e, n = BBOX; H = W = 200
    lat = np.linspace(n, s, H)[:, None] * np.ones((1, W)); lon = np.ones((H, 1)) * np.linspace(w, e, W)[None, :]
    return {"z": fn(lon, lat), "bbox": BBOX, "source": "synthetic"}


def north_m(lat): return (lat - LAT0) * 111_320


def test_dem_sampling_is_bilinear():
    d = dem(lambda lon, lat: 100 + north_m(lat) * 0.1)
    z = sample_dem(d, np.array([LON0 + 0.001]), np.array([LAT0 + 0.001]))
    assert abs(z[0] - (100 + 11.13)) < 0.3


def test_turtles_pile_up_at_the_low_side():
    d = dem(lambda lon, lat: 100 + north_m(lat) * 0.1)   # 10% grade rising to the north
    f = Fence(SQ, lambda lo, la: sample_dem(d, lo, la))
    _, _, _, final, _ = simulate(f, n=400)
    ys = f.xy[final, 1]
    assert (ys < f.xy[:, 1].min() + 40).mean() > 0.6     # most end along the south (low) fence


def test_gaps_avoid_drainage_lows_and_add_up():
    d = dem(lambda lon, lat: 100 + north_m(lat) * 0.1)
    f = Fence(SQ, lambda lo, la: sample_dem(d, lo, la))
    _, _, visited, _, _ = simulate(f, n=400)
    gaps, banned = choose_gaps(f, visited, k=3)
    assert len(gaps) == 3 and not banned[gaps].any()
    freed = np.zeros(len(visited), bool); cum = []
    for g in gaps:
        freed |= visited[:, g]; cum.append(freed.mean())
    assert cum == sorted(cum) and cum[-1] > 0.3


def test_flat_site_spreads_turtles_out():
    f = Fence(SQ, lambda lo, la: np.zeros(np.shape(lo)))
    _, _, _, final, _ = simulate(f, n=400)
    tr, h = traps(f, final)
    assert max(h) / 400 < 0.1                            # no single trap holds most turtles on flat ground


def test_run_output_shape():
    r = run(SQ, dem(lambda lon, lat: 100 + north_m(lat) * 0.05), n=200, n_tracks=20)
    assert r["freed_curve_pct"][0] == 0 and r["freed_curve_pct"] == sorted(r["freed_curve_pct"])
    assert len(r["tracks"]) == 20 and all("fence_idx" in g for g in r["gaps"]) and r["terrain"] == "synthetic"
