"""Detector interface. The backend only ever calls detect() / detect_thermal().

RGB model: YOLO (Ultralytics) trained on 640 px tiles cut at native resolution (see build_dataset.py).
Full 5280 x 3956 photos are sliced into overlapping 640 px tiles, boxes mapped back, duplicates merged.
Weights: $AERO_WEIGHTS, else the team OneDrive models/aero_turtle.pt (weights stay out of git: trained on Hazel imagery).
"""
from __future__ import annotations

import os
from pathlib import Path

from turtles.contracts import Detection, Frame, Sensor
from turtles.geo import pixel_to_latlon

WEIGHTS = Path(os.environ.get("AERO_WEIGHTS", Path.home() / "Library/CloudStorage/OneDrive-GeorgeMasonUniversity-O365Production/TNUX Turtles Data/models/aero_turtle.pt"))
TILE, OVERLAP = 640, 0.2
MIN_SCORE = 0.25   # fusion's floor; 0.7 = strong
_model = None


def model():
    global _model
    if _model is None:
        from ultralytics import YOLO
        _model = YOLO(str(WEIGHTS))
    return _model


MODEL_VERSION = f"rgb-{WEIGHTS.stem}"


def boxes(image, conf: float = MIN_SCORE, batch: int = 16) -> list[tuple[float, float, float, float, float]]:
    """(x0, y0, x1, y1, score) in full-image pixels for one photo (path or PIL image), overlaps merged."""
    import numpy as np, torch, torchvision
    from PIL import Image
    im = np.asarray(Image.open(image).convert("RGB") if isinstance(image, (str, Path)) else image.convert("RGB"))
    H, W, step = im.shape[0], im.shape[1], int(TILE * (1 - OVERLAP))
    xs = sorted({*range(0, max(W - TILE, 0), step), max(W - TILE, 0)}); ys = sorted({*range(0, max(H - TILE, 0), step), max(H - TILE, 0)})
    origins = [(x, y) for y in ys for x in xs]; out = []
    for i in range(0, len(origins), batch):
        chunk = origins[i:i + batch]
        for (x, y), r in zip(chunk, model().predict([im[y:y + TILE, x:x + TILE] for x, y in chunk], imgsz=TILE, conf=conf, verbose=False)):
            out += [(b[0] + x, b[1] + y, b[2] + x, b[3] + y, s) for b, s in zip(r.boxes.xyxy.tolist(), r.boxes.conf.tolist())]
    if not out: return []
    t = torch.tensor(out); keep = torchvision.ops.nms(t[:, :4], t[:, 4], 0.3)
    return [tuple(map(float, t[k])) for k in keep]


def detect(frame: Frame, image_path: str) -> list[Detection]:
    """Turtle detections in one aerial RGB frame (bbox in original-image px, lat/lon of the bbox center)."""
    dets = []
    for k, (x0, y0, x1, y1, s) in enumerate(boxes(image_path)):
        lat, lon = pixel_to_latlon(frame, (x0 + x1) / 2, (y0 + y1) / 2)
        dets.append(Detection(detection_id=f"{frame.frame_id}-{k}", frame_id=frame.frame_id, sensor=Sensor.RGB,
                              bbox=[round(x0), round(y0), round(x1), round(y1)], score=round(s, 3), lat=lat, lon=lon,
                              timestamp=frame.timestamp, model_version=MODEL_VERSION))
    return dets


def detect_thermal(frame: Frame, image_path: str) -> list[Detection]:
    """Thermal is phase 2 (spring): ground ran warmer than air all of Oct 24, see technical plan section 9."""
    return []
