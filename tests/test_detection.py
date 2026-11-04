import random

from PIL import Image

from turtles.backend.ingest import frame_from_photo, read_xmp
from turtles.detection.build_dataset import T, boxes_in, crop, paste
from turtles.detection.run_flight import on_site

XMP = ('drone-dji:GpsLatitude="+38.793090954" drone-dji:GpsLongitude="-77.648273437" drone-dji:RelativeAltitude="+15.227" '
       'drone-dji:GimbalRollDegree="+180.00" drone-dji:GimbalYawDegree="-155.90" drone-dji:GimbalPitchDegree="{p}" '
       'drone-dji:UTCAtExposure="2026-10-24T15:22:57.928498"')


def _photo(tmp_path, pitch):
    p = tmp_path / "DJI_0001_V.JPG"; p.write_bytes(b"\xff\xd8" + XMP.format(p=pitch).encode()); return p


def test_ingest_reads_xmp_and_fixes_heading(tmp_path):
    f = frame_from_photo(_photo(tmp_path, "-89.9"), tmp_path, "grayson", "F1")
    assert read_xmp(_photo(tmp_path, "-89.9"))["RelativeAltitude"] == "+15.227"
    assert abs(f.yaw_deg - 24.1) < 1e-6 and f.timestamp == "2026-10-24T15:22:57Z" and f.alt_m == 15.227


def test_ingest_keeps_tilted_photos_down_to_45(tmp_path):
    assert frame_from_photo(_photo(tmp_path, "-59.5"), tmp_path, "grayson", "F1").pitch_deg == -59.5
    assert frame_from_photo(_photo(tmp_path, "-30.0"), tmp_path, "grayson", "F1") is None          # too close to the horizon
    assert frame_from_photo(_photo(tmp_path, "-59.5"), tmp_path, "grayson", "F1", nadir_only=True) is None


def test_crop_keeps_the_labeled_shell_inside():
    im, r = Image.new("RGB", (5280, 3956)), random.Random(1)
    for b in ([10, 10, 40, 40], [5240, 3920, 5270, 3950], [2600, 1900, 2630, 1930]):
        _, (x, y) = crop(im, r, b)
        assert boxes_in([b], x, y) == [[b[0] - x, b[1] - y, b[2] - x, b[3] - y]]


def test_boxes_mostly_outside_the_tile_are_dropped():
    assert boxes_in([[630, 0, 660, 30]], 0, 0) == [] and boxes_in([[600, 0, 630, 30]], 0, 0) == [[600, 0, 630, 30]]


def test_paste_returns_a_box_of_the_requested_size():
    bg, s = Image.new("RGB", (T, T), (120, 100, 80)), Image.new("RGBA", (100, 80), (200, 150, 50, 255))
    b = paste(bg, s, 30, random.Random(3))
    assert b and 15 <= max(b[2] - b[0], b[3] - b[1]) <= 45 and 0 <= b[0] < b[2] <= T


def test_geofence_keeps_site_and_fence_drops_far_away():
    assert on_site(38.7937722, -77.6473238)          # spot 1, inside
    assert on_site(38.7894977, -77.6469393)          # spot 6, woods edge
    assert not on_site(38.80, -77.60)                # ~4 km away


def test_real_tiles_rotate_with_their_boxes():
    from turtles.detection.build_real import turn
    im = Image.new("RGB", (T, T)); im.putpixel((120, 65), (255, 0, 0))
    for k in range(4):
        t, [b] = turn(im, [[100, 50, 140, 80]], k)
        assert any(t.getpixel((x, y)) == (255, 0, 0) for x in range(b[0], b[2]) for y in range(b[1], b[3]))


def test_detector_feeds_yolo_bgr(monkeypatch):
    """YOLO reads numpy input as BGR; a red photo must reach the model with red in the last channel."""
    import numpy as np
    from turtles.detection import detector
    seen = []
    class Fake:
        def predict(self, tiles, **kw): seen.append(tiles[0][0, 0].tolist()); return [type("R", (), {"boxes": type("B", (), {"xyxy": type("X", (), {"tolist": lambda s: []})(), "conf": type("C", (), {"tolist": lambda s: []})()})()})() for _ in tiles]
    monkeypatch.setattr(detector, "model", lambda: Fake())
    detector.boxes(Image.new("RGB", (640, 640), (200, 10, 5)))
    assert seen[0] == [5, 10, 200]


def test_shell_polygons_turn_with_their_tiles():
    """Segmentation labels: the outline polygon must land on the shell after the tile is rotated."""
    import cv2, numpy as np
    from turtles.detection.build_real import turn
    from turtles.detection.reskin import tile_polys
    big = np.zeros((1000, 1000, 3), np.uint8); cv2.ellipse(big, (300, 260), (20, 12), 30, 0, 360, (0, 0, 255), -1)
    m = np.zeros((80, 80), np.uint8); cv2.ellipse(m, (300 - 260, 260 - 220), (20, 12), 30, 0, 360, 1, -1)
    for k in range(4):
        t, _ = turn(Image.fromarray(big[100:740, 100:740, ::-1].copy()), [], k)
        [p] = tile_polys([(260, 220, m)], [[280, 248, 320, 272]], 100, 100, k)
        cx, cy = p.mean(0).astype(int); assert t.getpixel((int(cx), int(cy)))[0] > 200   # red shell under the polygon center
