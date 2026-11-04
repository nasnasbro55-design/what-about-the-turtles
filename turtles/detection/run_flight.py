"""One drone flight -> alerts on the A.E.R.O. map. The end-to-end pipeline.

    python3 -m turtles.detection.run_flight "<flight folder>" --out "<OneDrive>/reports/flight_<date>.json" [--flight-id F-20261024]
    python3 -m turtles.backend.assistant --pack "<that json>"          # alerts show up in the app

ingest (straight-down photos) -> detect (YOLO, sliced) -> drop anything outside Logan's site boundary + BUFFER_M ->
fuse (same turtle seen in several photos = one alert) -> relocation suggestion per alert (F1) -> pack + thumbnails.
Outputs describe a private site: write them to OneDrive, not the repo.
"""
from __future__ import annotations

import argparse, json, math
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

from turtles.backend.fusion import fuse
from turtles.backend.ingest import ingest_flight
from turtles.detection.detector import MODEL_VERSION, detect
from turtles.geo import M_PER_DEG_LAT
from turtles.planner.relocation import HEATMAP, load_cells, suggest

SITE = Path(__file__).parents[1] / "planner" / "sites" / "grayson_lod.geojson"
BUFFER_M = 25  # keep detections just outside the boundary: turtles walk the silt fence on both sides


def _edge_m(lat: float, lon: float, ring: list) -> float:
    k = M_PER_DEG_LAT * math.cos(math.radians(lat)); best = 1e9
    for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
        ax, ay, bx, by = (x1 - lon) * k, (y1 - lat) * M_PER_DEG_LAT, (x2 - lon) * k, (y2 - lat) * M_PER_DEG_LAT
        t = max(0, min(1, -(ax * (bx - ax) + ay * (by - ay)) / (((bx - ax) ** 2 + (by - ay) ** 2) or 1)))
        best = min(best, math.hypot(ax + t * (bx - ax), ay + t * (by - ay)))
    return best


def on_site(lat: float, lon: float, site: Path = SITE, buffer_m: float = BUFFER_M) -> bool:
    """Inside any boundary polygon, or within buffer_m of one."""
    for f in json.loads(site.read_text())["features"]:
        ring = f["geometry"]["coordinates"][0]; inside = False
        for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
            if (y1 > lat) != (y2 > lat) and lon < (x2 - x1) * (lat - y1) / (y2 - y1) + x1: inside = not inside
        if inside or _edge_m(lat, lon, ring) <= buffer_m: return True
    return False


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("folder"); ap.add_argument("--out", required=True); ap.add_argument("--site-id", default="grayson")
    ap.add_argument("--flight-id"); ap.add_argument("--no-geofence", action="store_true"); a = ap.parse_args()
    frames = ingest_flight(a.folder, a.site_id, a.flight_id or "F-flight")
    if not a.flight_id and frames: a.flight_id = "F-" + frames[0].timestamp[:10].replace("-", "")
    for f in frames: f.flight_id = a.flight_id
    print(f"{len(frames)} straight-down photos in {a.folder} | model {MODEL_VERSION}")
    dets, by_id, paths = [], {}, {}
    for i, f in enumerate(frames, 1):
        d = detect(f, str(Path(a.folder, f.path))); kept = [x for x in d if a.no_geofence or on_site(x.lat, x.lon)]
        dets += kept; by_id.update({x.detection_id: x for x in kept}); paths.update({x.detection_id: Path(a.folder, f.path) for x in kept})
        if d: print(f"  [{i}/{len(frames)}] {f.frame_id}: {len(d)} found, {len(kept)} on site", flush=True)
    alerts = fuse(dets, a.site_id, a.flight_id)
    out = Path(a.out); thumbs = out.parent / "thumbnails"; thumbs.mkdir(parents=True, exist_ok=True)
    cells, pack = load_cells(str(HEATMAP)), []
    for i, al in enumerate(sorted(alerts, key=lambda x: -x.score), 1):
        best = by_id[al.detection_ids[0]]; x0, y0, x1, y1 = best.bbox; m = max(60, 2 * (x1 - x0))
        Image.open(paths[best.detection_id]).crop((x0 - m, y0 - m, x1 + m, y1 + m)).resize((240, 240), Image.LANCZOS).save(thumbs / f"{best.detection_id}.jpg", quality=90)
        s = suggest(al.alert_id, al.lat, al.lon, cells, None, "box"); sn = suggest(al.alert_id, al.lat, al.lon, cells, None, "snapping")
        pack.append({"alert_id": al.alert_id, "label": f"Detection {i} · {al.score:.0%}", "lat": al.lat, "lon": al.lon,
                     "suggestion": asdict(s), "suggestion_snapping": asdict(sn), "score": al.score, "confidence": al.confidence.value,
                     "sensors": [x.value for x in al.sensors], "detection_ids": al.detection_ids, "thumbnail": f"thumbnails/{best.detection_id}.jpg",
                     "flight_id": a.flight_id, "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")})
    out.write_text(json.dumps(pack, indent=1))
    print(f"{len(dets)} detections -> {len(alerts)} alerts -> {out}\nShow them:  python3 -m turtles.backend.assistant --pack \"{out}\"")


if __name__ == "__main__":
    main()
