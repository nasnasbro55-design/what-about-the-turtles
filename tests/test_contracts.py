"""Run from the repo root:  python3 -m pytest -q"""
from pathlib import Path

import pytest

from turtles.backend.fusion import fuse
from turtles.contracts import Alert, Confidence, Detection, FlightWindow, Frame, Sensor, Zone, from_dict, load
from turtles.geo import distance_m, pixel_to_latlon
from turtles.planner.planner import urgency

MOCK = Path(__file__).resolve().parents[1] / "turtles" / "architecture" / "mock"


def frame(yaw=0.0):
    return Frame("f", "fl", "s", Sensor.RGB, "x.jpg", "2026-10-25T14:00:00Z",
                 38.76, -77.52, 15.0, yaw, 8064, 6048, 69.7)


def test_mock_files_match_contracts():
    assert len(load(Frame, MOCK / "frames.json")) == 7
    assert len(load(Detection, MOCK / "detections.json")) == 8
    assert len(load(Alert, MOCK / "alerts.json")) == 4


def test_planner_mocks_and_urgency():
    assert len(load(Zone, MOCK / "zones.json")) == 3
    windows = load(FlightWindow, MOCK / "windows.json")
    assert [w.priority for w in windows] == sorted((w.priority for w in windows), reverse=True)
    assert [urgency(h) for h in (-1, 10, 48, 100, 500)] == [0.0, 1.0, 0.7, 0.4, 0.1]


def test_heatmap_mock_is_valid_geojson():
    import json
    fc = json.loads((MOCK / "heatmap.geojson").read_text())
    assert fc["type"] == "FeatureCollection" and fc["features"]
    for f in fc["features"]:
        ring = f["geometry"]["coordinates"][0]
        assert f["geometry"]["type"] == "Polygon" and ring[0] == ring[-1]
        assert 0 <= f["properties"]["likelihood"] <= 1 and isinstance(f["properties"]["reasons"], list)


def test_unknown_field_is_rejected():
    with pytest.raises(ValueError):
        from_dict(Alert, {"alert_id": "x", "surprise": 1})


def test_center_pixel_is_drone_position():
    assert pixel_to_latlon(frame(), 4032, 3024) == pytest.approx((38.76, -77.52))


def test_pixel_direction_follows_heading():
    lat, lon = pixel_to_latlon(frame(yaw=0), 8000, 3024)   # right edge, facing north -> east
    assert lat == pytest.approx(38.76) and lon > -77.52
    lat, lon = pixel_to_latlon(frame(yaw=90), 8000, 3024)  # right edge, facing east -> south
    assert lat < 38.76 and lon == pytest.approx(-77.52)


def test_distance():
    assert distance_m(38.76, -77.52, 38.76 + 1e-4, -77.52) == pytest.approx(11.13, abs=0.01)


def test_fusion_reproduces_mock_alerts():
    expected = load(Alert, MOCK / "alerts.json")
    got = fuse(load(Detection, MOCK / "detections.json"), "grayson-mock", "F-20261025-01", now=expected[0].created_at)
    assert [(a.confidence, a.sensors, a.detection_ids) for a in got] == \
           [(a.confidence, a.sensors, a.detection_ids) for a in expected]
    assert got[0].confidence is Confidence.HIGH and Sensor.THERMAL in got[0].sensors
