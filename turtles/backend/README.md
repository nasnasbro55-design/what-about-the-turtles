# Backend

**Owner:** Naz (took over from Ethan, Nov 3).
**Job:** photos in, alerts out, served over an API.

```
photo folder -> ingest.py -> list[Frame] -> detector.detect() -> list[Detection] -> fusion.fuse() -> list[Alert]
             -> thumbnails -> SQLite (db.py) -> api.py   (+ notify.py on high alerts)
```

## Files

| File | What it does |
|---|---|
| `ingest.py` | Reads DJI M3E `*_V.JPG` XMP tags into Frames (`frame_id` = photo stem). Skips photos not pointed straight down (±5°), fixes heading flips with `nadir_yaw`, and uses `UTCAtExposure` for time. `python3 -m turtles.backend.ingest <folder>` prints what it read. |
| `fusion.py` | Fusion v1 (ARCHITECTURE section 5). |
| `pipeline.py` | `run_flight()` runs ingest → YOLO detect → geofence (site boundary + 25 m, same as `detection/run_flight.py`) → fuse → thumbnail crops → store. CLI: `python3 -m turtles.backend.pipeline <folder> --db <OneDrive>/reports/turtles.db [--mock-detect] [--no-geofence]`. |
| `db.py` | `SqliteAlertStore`: `frames`, `detections`, `alerts`, and `flights` tables. It's a drop-in `AlertStore`, so A.E.R.O. and the app share the same rows. |
| `api.py` | The server: ARCHITECTURE section 6 on SQLite, plus everything from `assistant.create_app` (login, A.E.R.O., UI). |
| `notify.py` | Emails or texts high alerts (stretch). Off unless the `TURTLE_SMTP_*` env vars are set. |
| `assistant.py` | A.E.R.O. (F7). |

## Run

```bash
pip install fastapi uvicorn pillow python-multipart anthropic
python3 -m turtles.backend.api --pack "<OneDrive>/reports/voice_pack_2026-10-24.json"
python3 -m turtles.backend.api --mock --mock-detect --db /tmp/mock.db      # no real data needed
```

Site data is private, so it stays out of the repo. The database, `thumbnails/`, uploaded `flights/` and `thermal/` all live beside the database, which defaults to `turtles.db` in the pack's folder. That folder is also where `detection/run_flight.py` writes its packs and thumbnails, so both paths show up in the app. The pack is imported once; re-running adds only new spot ids. On a fresh database, the old `<pack>_state.json` field changes are carried over. `--reset` deletes the database for a clean demo.

## Endpoints

| Method | Path | Notes |
|---|---|---|
| `POST` | `/flights` | multipart: `file` = zip of the flight folder, `site_id`, optional `flight_id`, `mock_detect`, `no_geofence` |
| `POST` | `/flights/local` | `{"folder": "...", "site_id": "grayson"}` for a folder already on the laptop |
| `GET` | `/flights?site_id=` | past flights, newest first |
| `GET` | `/alerts?site_id=&status=` | newest first; spots from the same time stay in spot order |
| `GET` | `/alerts/{id}` | accepts `spot-3`, `3`, or a flight alert id |
| `PATCH` | `/alerts/{id}` | from `assistant.py` (status, note, species, sex, field log) |
| `POST` | `/alerts/{id}/thermal` | multipart `file` + `lat`, `lon`; calls `detect_thermal` and re-fuses. Thermal is phase 2 (spring), so for now it logs "no hot spot" |
| `GET` | `/thumbnails/{file}` | JPEG crop of the best detection, from `<db folder>/thumbnails` |
| `GET` | `/plan?site_id=` | live planner when `TURTLE_ZONES=<zones.json>` has work dates; otherwise sample windows |
| `GET` | `/zones`, `/heatmap`, `/alerts/changes`, `/alerts/{id}/relocation` | from `assistant.py`, unchanged |

## Detector hookup

The pipeline calls `turtles.detection.detector.detect(frame, image_path)`, the sliced YOLO model with weights from `$AERO_WEIGHTS` or the team OneDrive. If the weights or `ultralytics` are missing, flights return a 503 that says so; `--mock-detect` places the mock boxes on the real frames so every other step runs. Detector ids (`<photo stem>-<k>`) are kept, and empty or duplicate ids are filled in.

Tests: `python3 -m pytest -q tests/test_backend.py`
