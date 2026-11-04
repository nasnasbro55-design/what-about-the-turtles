"""Run from the repo root:  python3 -m pytest -q"""
import math
from pathlib import Path

import pytest

from turtles.backend.fusion import fuse
from turtles.contracts import Alert, Confidence, Detection, FlightWindow, Frame, Sensor, Zone, from_dict, load
from turtles.geo import distance_m, nadir_yaw, pixel_to_latlon
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


def test_nadir_yaw_handles_dji_flip():
    # real values from Logan's Sept 29 Grayson photos: same orientation reported two ways
    assert nadir_yaw(-155.9, 0.0) == pytest.approx(-155.9)
    assert nadir_yaw(24.1, 180.0) == pytest.approx(-155.9)
    assert nadir_yaw(170.0, 0.0) == pytest.approx(170.0)


def test_distance():
    assert distance_m(38.76, -77.52, 38.76 + 1e-4, -77.52) == pytest.approx(11.13, abs=0.01)


def test_fusion_reproduces_mock_alerts():
    expected = load(Alert, MOCK / "alerts.json")
    got = fuse(load(Detection, MOCK / "detections.json"), "grayson-mock", "F-20261025-01", now=expected[0].created_at)
    assert [(a.confidence, a.sensors, a.detection_ids) for a in got] == \
           [(a.confidence, a.sensors, a.detection_ids) for a in expected]
    assert got[0].confidence is Confidence.HIGH and Sensor.THERMAL in got[0].sensors


def test_tilted_camera_projects_forward():
    from turtles.geo import ground_offset_m
    # straight down: identical to the old flat formula
    g = 2 * 15 * math.tan(math.radians(70.65) / 2) / 5280
    assert ground_offset_m(15, 70.65, 5280, 3956, 0, -90, 4000, 1000) == pytest.approx(((4000 - 2640) * g, (1978 - 1000) * g))
    # 15 m up, tilted -45 facing north: image center is 15 m north; -60 facing east: 15/tan(60) m east
    assert ground_offset_m(15, 70.65, 5280, 3956, 0, -45, 2640, 1978) == pytest.approx((0, 15), abs=1e-9)
    assert ground_offset_m(15, 70.65, 5280, 3956, 90, -60, 2640, 1978) == pytest.approx((15 / math.tan(math.radians(60)), 0), abs=1e-9)
    # higher in the image = further away when tilted
    assert ground_offset_m(15, 70.65, 5280, 3956, 0, -50, 2640, 500)[1] > ground_offset_m(15, 70.65, 5280, 3956, 0, -50, 2640, 3500)[1]
