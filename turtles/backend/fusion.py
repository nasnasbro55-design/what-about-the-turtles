"""Fusion v1: turn per-frame detections into alerts.

The rules are specified in turtles/architecture/ARCHITECTURE.md section 5 - keep the two in sync.
Thresholds are first guesses; tune them after the first real flight.

Pass in every detection for one site from one survey, including any handheld thermal
checks done afterwards, and you get back one Alert per probable turtle.
"""
from __future__ import annotations

from datetime import datetime, timezone

from turtles.contracts import Alert, Confidence, Detection, Sensor
from turtles.geo import distance_m

MIN_SCORE = {Sensor.RGB: 0.25, Sensor.THERMAL: 0.5}  # below this, ignore
CLUSTER_RADIUS_M = 4.0  # detections closer than this are the same turtle (GPS error + photo overlap)
MULTIVIEW_SCORE = 0.7   # RGB seen in >= 2 different photos at this score counts as agreement


def fuse(detections: list[Detection], site_id: str, flight_id: str, now: str | None = None) -> list[Alert]:
    clusters: list[list[Detection]] = []
    for d in sorted((d for d in detections if d.score >= MIN_SCORE[d.sensor]), key=lambda d: -d.score):
        c = next((c for c in clusters if distance_m(c[0].lat, c[0].lon, d.lat, d.lon) <= CLUSTER_RADIUS_M), None)
        if c: c.append(d)
        else: clusters.append([d])

    now = now or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    alerts = []
    for i, c in enumerate(clusters, 1):
        sensors = sorted({d.sensor for d in c}, key=lambda s: s.value)
        views = len({d.frame_id for d in c if d.sensor is Sensor.RGB and d.score >= MULTIVIEW_SCORE})
        w = sum(d.score for d in c)
        alerts.append(Alert(
            alert_id=f"{flight_id}-A{i:03d}", site_id=site_id, flight_id=flight_id,
            lat=round(sum(d.lat * d.score for d in c) / w, 7), lon=round(sum(d.lon * d.score for d in c) / w, 7),
            confidence=Confidence.HIGH if len(sensors) > 1 or views >= 2 else Confidence.REVIEW,
            score=c[0].score, sensors=sensors, detection_ids=[d.detection_id for d in c],
            thumbnail=f"thumbnails/{c[0].detection_id}.jpg", created_at=now))
    return alerts
