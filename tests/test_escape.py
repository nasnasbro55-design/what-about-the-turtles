"""F6 v2 fence-exit simulator tests - synthetic site, no internet.  python3 -m pytest -q"""
import math

import numpy as np

from turtles.planner.escape import Fence, evenly, exit_step, hit_fence, run, simulate

LAT0, LON0 = 38.79, -77.65
KL = 111_320 * math.cos(math.radians(LAT0))
ll = lambda x, y: [LON0 + x / KL, LAT0 + y / 111_320]
SQUARE = [ll(0, 0), ll(200, 0), ll(200, 200), ll(0, 200), ll(0, 0)]
ARROW = [ll(0, 0), ll(200, 0), ll(200, 150), ll(100, 300), ll(0, 150), ll(0, 0)]   # sharp tip at the top


def test_square_has_four_corners_and_tip_is_found():
    assert len(Fence(SQUARE).corners) == 4
    f = Fence(ARROW); o = f.to_xy([LON0], [LAT0])[0]; tips = [f.xy[c] - o for c in f.corners]
    assert any(abs(x - 100) < 4 and abs(y - 300) < 4 for x, y in tips)


def test_ray_hits_the_fence_ahead():
    f = Fence(SQUARE); o = f.to_xy([LON0], [LAT0])[0]
    j, d = hit_fence(f, o + [100.0, 100.0], 0.0)                 # due north from the middle
    assert abs(f.xy[j][1] - o[1] - 200) < 2.5 and abs(d - 100) < 2.5


def test_walk_follows_heading_and_stays_short():
    f = Fence(SQUARE); T = simulate(f, np.zeros((0, 2)), n=200)
    assert all(t["walk_steps"] * 2 <= 100 * 0.3048 + 2 for t in T)   # never more than ~100 ft
    assert {t["kind"] for t in T} == {"random"}


def test_woods_pull_turtles_toward_them():
    f = Fence(SQUARE); o = f.to_xy([LON0], [LAT0])[0]; woods = np.array([o + [100.0, 400.0]])   # woods to the north
    T = simulate(f, woods, n=400)
    north = np.mean([f.xy[t["hit"]][1] - o[1] > 190 for t in T])
    assert north > 0.4                                                # far above the 25% a random walk gives


def test_closer_ramps_free_more_turtles():
    f = Fence(SQUARE); T = simulate(f, np.zeros((0, 2)), n=300)
    pct = lambda ramps: np.mean([exit_step(f, t, ramps, set(f.corners), t["walk_steps"]) >= 0 for t in T])
    assert pct([]) == 0 and pct(evenly(f, 30)) > pct(evenly(f, 60)) > 0


def test_run_output_and_deterrent():
    r = run(SQUARE, heatmap="/nonexistent", n=300, n_tracks=10)
    assert r["version"] == 2 and len(r["tracks"]) == 10 and r["scenarios"][0]["key"] == "none"
    s = {x["key"]: x for x in r["scenarios"]}
    assert s["every100"]["escaped_pct"]["1.0"] > s["every150"]["escaped_pct"]["1.0"]
    assert s["every150"]["escaped_pct"]["2.0"] >= s["every150"]["escaped_pct"]["1.0"]
