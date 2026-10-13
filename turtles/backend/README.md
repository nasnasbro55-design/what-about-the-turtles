# Backend: Ethan

**Your job:** photos in, alerts out, served over an API.
Read [`../architecture/ARCHITECTURE.md`](../architecture/ARCHITECTURE.md) sections 1, 4, 5, and 6 first.

```
photo folder -> ingest.py -> list[Frame] -> detector.detect() -> list[Detection] -> fusion.fuse() -> list[Alert] -> SQLite -> api.py
```

## What's already here

- **`fusion.py`:** fusion v1 is written and tested (`python3 -m pytest -q`). Read it, own it, and tune the constants at the top after the first real flight.
- **`ingest.py`:** a stub with the DJI EXIF/XMP tag names you need. Your first real code.

## Steps

1. **Ingest.**
   - Read GPS, `RelativeAltitude`, `GimbalYawDegree`, `GimbalPitchDegree`, and `DateTimeOriginal` from each photo (`exiftool` via `pyexiftool` is easiest).
   - Skip photos where pitch isn't about −90°.
   - DJI timestamps have no timezone, so convert them to UTC.
   - Check the tag names against the first real Mini 4 Pro photo.
2. **Fake detector.** Until Jake's model is ready, use a `detect()` that returns `mock/detections.json` so the whole pipeline runs end to end now.
3. **Storage.** One SQLite file with `frames`, `detections`, and `alerts` tables mirroring `contracts.py`.
4. **API.** Use FastAPI with the endpoints in ARCHITECTURE section 6. Turn CORS on so Huy's web app can call it.
5. **Thumbnails.** Crop the best detection's bbox (plus some padding) from its photo, save it as `thumbnails/<detection_id>.jpg`, and serve it.

## Milestones

| Date | Done means |
|---|---|
| Thu Oct 16 | `GET /alerts` serves `mock/alerts.json`; Huy can hit it |
| Mon Oct 20 | `PATCH /alerts/{id}` saves status to SQLite; `ingest_flight()` reads a sample DJI photo |
| Fri Oct 23 | `POST /flights` runs ingest → detect → fuse on a folder and the alerts show up in Huy's app |

**Stretch:** text or email to the responder when a `high` alert is created.
**Don't worry about:** model training or how the dashboard looks.
