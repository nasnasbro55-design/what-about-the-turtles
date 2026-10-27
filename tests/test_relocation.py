"""F1 relocation guide tests on a synthetic site - no internet needed.  python3 -m pytest -q

Layout (10 m cells, turtle-relative meters): cleared site |x| <= 60, |y| <= 200; dense woods everywhere else,
except a road (bare) at x = -80..-70 and a pond at |x| <= 20, y = 240..260.
"""
import json, math
from dataclasses import asdict

from turtles.contracts import RelocationSuggestion, from_dict
from turtles.planner.relocation import load_cells, suggest

LAT0, LON0 = 38.79, -77.65
KL = 111_320 * math.cos(math.radians(LAT0))


def ndvi_at(x, y):
    if abs(x) <= 60 and abs(y) <= 200: return 0.05, True
    if -80 <= x <= -70: return 0.05, False
    if abs(x) <= 20 and 240 <= y <= 260: return -0.2, False
    return 0.6, False


def cells(tmp_path):
    feats = []
    for x in range(-150, 151, 10):
        for y in range(-300, 301, 10):
            v, on = ndvi_at(x, y)
            ring = [[LON0 + (x + dx) / KL, LAT0 + (y + dy) / 111_320] for dx, dy in ((-5, -5), (5, -5), (5, 5), (-5, 5), (-5, -5))]
            feats.append({"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [ring]},
                          "properties": {"likelihood": 0.5, "reasons": ["x"], "on_site": on, "ndvi": v}})
    p = tmp_path / "heatmap.geojson"; p.write_text(json.dumps({"type": "FeatureCollection", "features": feats}))
    return load_cells(p)


def at(x, y): return LAT0 + y / 111_320, LON0 + x / KL


def xy(s): return round((s.target_lon - LON0) * KL), round((s.target_lat - LAT0) * 111_320)


def test_nearest_cover_over_the_fence(tmp_path):
    s = suggest("A1", *at(20, 0), cells(tmp_path))
    assert xy(s) == (70, 0) and s.distance_m == 50 and round(s.bearing_deg) == 90
    assert "east to dense cover" in s.reasons[0] and any("hamburger" in r for r in s.reasons)


def test_follows_heading_off_site(tmp_path):
    s = suggest("A1", *at(20, 0), cells(tmp_path), heading_deg=80)
    assert xy(s)[0] == 70 and any("Same direction" in r for r in s.reasons)


def test_ignores_heading_deeper_into_site(tmp_path):
    s = suggest("A1", *at(20, 0), cells(tmp_path), heading_deg=270)
    assert xy(s)[0] == 70 and any("deeper into the site" in r for r in s.reasons)


def test_avoids_the_road(tmp_path):
    s = suggest("A1", *at(-40, 0), cells(tmp_path))
    assert xy(s)[0] <= -110 and any("Away from roads" in r for r in s.reasons)


def test_snapping_turtle_goes_beside_water_not_in_it(tmp_path):
    s = suggest("A1", *at(0, 0), cells(tmp_path), species="snapping")
    x, y = xy(s)
    assert abs(x) <= 20 and y == 230 and "beside the water" in s.reasons[0]


def test_nearly_out_lets_it_walk(tmp_path):
    s = suggest("A1", *at(58, 0), cells(tmp_path))
    assert s.distance_m <= 15 and any("walk off on its own" in r for r in s.reasons)


def test_contract_roundtrip(tmp_path):
    s = suggest("A1", *at(20, 0), cells(tmp_path))
    assert from_dict(RelocationSuggestion, asdict(s)) == s


def test_already_off_site_stays_put(tmp_path):
    s = suggest("A1", *at(100, 0), cells(tmp_path))
    assert s.distance_m == 0 and "leave it where it is" in s.reasons[0]
