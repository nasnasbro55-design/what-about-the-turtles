"""One flight folder in, alerts out:  ingest -> detect -> fuse -> thumbnails -> SQLite (-> notify on high).

    python3 -m turtles.backend.pipeline "<OneDrive>/flights/2026-11-04" --site grayson --db turtles.db
    python3 -m turtles.backend.pipeline <folder> --mock-detect     # pipeline test before Jake's model is in

Same steps as turtles.detection.run_flight (geofence to the site boundary + BUFFER_M), but results go into the
SQLite store the server reads, instead of a pack file. Detector: turtles.detection.detector.detect. If it isn't
available the run stops with a clear message, unless --mock-detect (mock/detections.json boxes on the real frames).
Outputs describe a private site: keep the database (and the thumbnails/ beside it) in OneDrive, not the repo.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, List, Optional

from turtles.backend import ingest, notify
from turtles.backend.fusion import fuse
from turtles.contracts import Detection, Frame, Sensor, from_dict
from turtles.geo import pixel_to_latlon

ROOT = Path(__file__).resolve().parents[1]
THUMB_PAD = 1.5      # crop = bbox grown by this many bbox-sizes on each side, so the responder sees surroundings
THUMB_MIN_PX = 160   # never crop smaller than this (tiny far-away boxes)
THUMB_OUT_PX = 480   # saved thumbnail size; small crops are smoothly scaled up so phones do not show blocky pixels


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def real_detector() -> Callable[[Frame, str], List[Detection]]:
    from turtles.detection import detector
    return detector.detect


def mock_detector() -> Callable[[Frame, str], List[Detection]]:
    """Puts the mock boxes on real frames, round-robin, so every step after detect runs on real photos."""
    mock = [from_dict(Detection, d) for d in json.loads((ROOT / "architecture" / "mock" / "detections.json").read_text())]
    mock = [d for d in mock if d.sensor is Sensor.RGB]
    state = {"i": 0}

    def detect(frame: Frame, image_path: str) -> List[Detection]:
        if state["i"] >= len(mock): return []
        m = mock[state["i"]]; state["i"] += 1
        sx, sy = frame.width_px / 5280, frame.height_px / 3956   # mock boxes are in full-size M3E pixels
        x0, y0, x1, y1 = bbox = [round(m.bbox[0] * sx), round(m.bbox[1] * sy), round(m.bbox[2] * sx), round(m.bbox[3] * sy)]
        lat, lon = pixel_to_latlon(frame, (x0 + x1) / 2, (y0 + y1) / 2)
        return [Detection(detection_id="", frame_id=frame.frame_id, sensor=Sensor.RGB, bbox=bbox, score=m.score,
                          lat=round(lat, 7), lon=round(lon, 7), timestamp=frame.timestamp, model_version="rgb-mock")]
    return detect


def make_thumbnail(image_path, bbox, out_path) -> bool:
    from PIL import Image
    try:
        with Image.open(image_path) as im:
            x0, y0, x1, y1 = bbox
            half = min(max(THUMB_MIN_PX, (1 + 2 * THUMB_PAD) * max(x1 - x0, y1 - y0)), im.width, im.height) / 2
            cx = min(max((x0 + x1) / 2, half), im.width - half)    # keep the crop inside the photo near the edges
            cy = min(max((y0 + y1) / 2, half), im.height - half)
            box = tuple(int(v) for v in (max(0, cx - half), max(0, cy - half), min(im.width, cx + half), min(im.height, cy + half)))
            crop = im.crop(box).convert("RGB")
            k = THUMB_OUT_PX / max(crop.size); crop = crop.resize((round(crop.width * k), round(crop.height * k)), Image.LANCZOS)
            Path(out_path).parent.mkdir(parents=True, exist_ok=True)
            crop.save(out_path, "JPEG", quality=85)
        return True
    except Exception as e:
        print(f"  thumbnail failed for {image_path}: {e}"); return False


def geofence_for(site_id: str):
    """Keep-detection test for the site: Logan's boundary + BUFFER_M for Grayson, no fence for other/mock sites."""
    from turtles.detection.run_flight import SITE, on_site
    return on_site if site_id == "grayson" and SITE.exists() else None


def run_flight(folder, site_id: str, store, flight_id: Optional[str] = None, detect=None,
               thumbs_dir: Optional[Path] = None, created_at: Optional[str] = None, geofence="auto") -> dict:
    """The whole POST /flights job. Returns {flight_id, frames, detections, off_site, alerts, high}.
    thumbs_dir defaults to <store.media_dir>/thumbnails, which GET /thumbnails serves."""
    folder = Path(folder)
    thumbs_dir = Path(thumbs_dir or Path(getattr(store, "media_dir", None) or ".") / "thumbnails")
    keep = geofence_for(site_id) if geofence == "auto" else geofence
    probe = ingest.ingest_flight(str(folder), site_id, "probe")
    if not probe: raise ValueError(f"no usable *_V.JPG photos in {folder} (need DJI XMP tags and the gimbal at -45 or steeper)")
    flight_id = flight_id or ingest.flight_id_for(probe, store.next_flight_number(probe[0].timestamp[:10].replace("-", "")))
    frames = ingest.ingest_flight(str(folder), site_id, flight_id)
    detect = detect or real_detector()

    dets: List[Detection] = []; seen, off = set(), 0
    for f in frames:
        try: got = detect(f, str(folder / f.path)) or []
        except (NotImplementedError, ImportError, FileNotFoundError) as e:
            raise RuntimeError(f"detector not available ({type(e).__name__}: {e}): set AERO_WEIGHTS, or run with --mock-detect")
        for k, d in enumerate(got):
            if keep and not keep(d.lat, d.lon): off += 1; continue
            d.frame_id = f.frame_id
            if not d.detection_id or d.detection_id in seen: d.detection_id = f"{f.frame_id}-{k}"
            seen.add(d.detection_id); dets.append(d)

    alerts = sorted(fuse(dets, site_id, flight_id, now=created_at or now_utc()), key=lambda a: -a.score)   # best = spot 1
    by_id, frame_by_id = {d.detection_id: d for d in dets}, {f.frame_id: f for f in frames}
    for a in alerts:
        best = by_id[a.detection_ids[0]]
        name = f"{best.detection_id}.jpg"
        ok = make_thumbnail(folder / frame_by_id[best.frame_id].path, best.bbox, Path(thumbs_dir) / name)
        a.thumbnail = f"thumbnails/{name}" if ok else ""   # no broken links in the app

    store.add_frames(frames); store.add_detections(dets)
    added = store.add_contract_alerts(alerts, label=lambda a: f"detection {a['score']:.0%}")
    store.add_flight(flight_id=flight_id, site_id=site_id, folder=str(folder.resolve()), created_at=now_utc(),
                     frames=len(frames), detections=len(dets), alerts=len(added),
                     model_version=dets[0].model_version if dets else "")
    high = [a for a in added if a.get("confidence") == "high"]
    if high: notify.high_alerts(high, flight_id)
    return {"flight_id": flight_id, "frames": len(frames), "detections": len(dets), "off_site": off, "alerts": len(added), "high": len(high)}


if __name__ == "__main__":
    import argparse
    from turtles.backend.db import SqliteAlertStore
    ap = argparse.ArgumentParser(description="Run one flight folder through ingest -> detect -> fuse")
    ap.add_argument("folder"); ap.add_argument("--site", default="grayson"); ap.add_argument("--db", default="turtles.db")
    ap.add_argument("--flight", help="flight id (default F-YYYYMMDD-NN)")
    ap.add_argument("--mock-detect", action="store_true", help="use mock boxes instead of the YOLO model")
    ap.add_argument("--no-geofence", action="store_true", help="keep detections outside the site boundary")
    a = ap.parse_args()
    s = SqliteAlertStore(a.db); s.media_dir = Path(a.db).resolve().parent
    print(run_flight(a.folder, a.site, s, a.flight, mock_detector() if a.mock_detect else None,
                     geofence=None if a.no_geofence else "auto"))
