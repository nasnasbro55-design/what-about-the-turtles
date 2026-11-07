"""The backend server: ARCHITECTURE section 6 on SQLite, with A.E.R.O. and Huy's app on the same store.

    pip install fastapi uvicorn pillow python-multipart anthropic
    python3 -m turtles.backend.api --pack "<OneDrive>/reports/voice_pack_2026-10-24.json"   # db: <OneDrive>/reports/turtles.db
    python3 -m turtles.backend.api --mock --db /tmp/mock.db        # mock alerts + zones, nothing real needed

Private site data (database, thumbnails/, uploaded flights/, thermal/) lives beside the database, in OneDrive, not the repo.
By default that is the pack's folder, so run_flight packs and their thumbnails work too. A pack is imported once
(new spot ids only) and, on a fresh database, its old <pack>_state.json field changes are carried over.
Everything else from assistant.create_app is unchanged: login, /assistant, /alerts/changes, PATCH, /heatmap, the UI.

Added or replaced here:
    POST /flights                 zip of a flight folder (+ site_id)    -> {flight_id, frames, detections, alerts, high}
    POST /flights/local           {"folder": "...", "site_id": "..."}   same, for a folder already on this laptop
    GET  /flights?site_id=        past flights, newest first
    GET  /alerts?site_id=&status= alerts newest first
    GET  /alerts/{alert_id}       one alert
    POST /alerts/{alert_id}/thermal   FLIR photo + phone lat/lon -> re-fused alert
    GET  /plan?site_id=           live 7-day planner on the real site boundary (TURTLE_ZONES / TURTLE_WORK_STARTS for dated
                                  work areas); last saved plan when offline; sample windows only with --mock
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
import time
import uuid
import zipfile
from pathlib import Path
from typing import Optional

from turtles.backend import assistant, pipeline
from turtles.backend.db import SqliteAlertStore, row
from turtles.backend.fusion import fuse
from turtles.contracts import Detection, Frame, Sensor, Zone, from_dict, load
from turtles.geo import HFOV_DEG

ROOT = Path(__file__).resolve().parents[1]
MOCK = ROOT / "architecture" / "mock"
_plan_cache: dict = {}

try:   # module level: with `from __future__ import annotations` FastAPI resolves these names from module globals
    from fastapi import File, Form, HTTPException, Request, UploadFile
    from pydantic import BaseModel

    class LocalFlight(BaseModel):   # module level, same reason as assistant.Patch
        folder: str
        site_id: str = "grayson"
        flight_id: Optional[str] = None
        mock_detect: bool = False
        no_geofence: bool = False
        photos: Optional[list[str]] = None   # file names to use (e.g. one turtle's photos); None = the whole folder
except ImportError:
    LocalFlight = None


def thermal_detector():
    from turtles.detection import detector
    return detector.detect_thermal


def refuse_with_thermal(store: SqliteAlertStore, a: dict, dets: list[Detection]) -> dict:
    """Fuse the alert's drone detections + the new thermal ones; keep the cluster that holds this alert's spot."""
    old = store.detections(a.get("detection_ids", []))
    store.add_detections(dets)
    fused = fuse(old + dets, a.get("site_id", "grayson"), a.get("flight_id", ""))
    mine = next((f for f in fused if old and old[0].detection_id in f.detection_ids), None) \
        or next((f for f in fused if any(d.detection_id in f.detection_ids for d in dets)), None)
    hot = any(d.sensor is Sensor.THERMAL and mine and d.detection_id in mine.detection_ids for d in dets)
    if mine:
        f = row(mine)
        a.update({k: f[k] for k in ("confidence", "score", "sensors", "detection_ids", "lat", "lon")})
    a.setdefault("notes", []).append("thermal check: hot spot found" if hot else "thermal check: no hot spot")
    store.touch(a)
    return a


SITE_GEOJSON = ROOT / "planner" / "sites" / "grayson.geojson"
NO_DATE_HORIZON_D = 30   # with no work date, every forecast hour is equally (un)urgent: rank on weather + activity only


def site_zones(site_id: str) -> list[Zone]:
    """Zones the planner covers: TURTLE_ZONES (Hazel's work areas with dates) if set, else the traced site boundary,
    with TURTLE_WORK_STARTS (ISO UTC) as its work date when there is one."""
    zp = os.environ.get("TURTLE_ZONES")
    if zp and Path(zp).exists(): return [z for z in load(Zone, zp) if z.site_id == site_id and z.work_starts]
    if site_id != "grayson" or not SITE_GEOJSON.exists(): return []
    ring = json.loads(SITE_GEOJSON.read_text())["features"][0]["geometry"]["coordinates"][0]
    return [Zone(zone_id="SITE", site_id="grayson", name="Grayson Overlook site boundary", work="active construction",
                 polygon=[[round(la, 6), round(lo, 6)] for lo, la in ring], work_starts=os.environ.get("TURTLE_WORK_STARTS", ""))]


def live_plan(site_id: str, cache_dir: Optional[Path] = None):
    """Naz's planner on the real 7-day forecast for the real site, refreshed every 30 min.
    No internet (venue Wi-Fi) -> the last good plan from <cache_dir>/plan_<site>.json, marked with its age.
    None only when there is no zone and no saved plan."""
    zones = site_zones(site_id)
    saved = Path(cache_dir) / f"plan_{site_id}.json" if cache_dir else None
    key = (site_id, os.environ.get("TURTLE_ZONES"), os.environ.get("TURTLE_WORK_STARTS"), int(time.time() // 1800))
    if _plan_cache.get("key") == key: return _plan_cache["val"]
    try:
        if not zones: raise LookupError(f"no zones for {site_id}")
        from datetime import datetime, timedelta, timezone
        from turtles.planner.planner import plan
        undated = [z for z in zones if not z.work_starts]
        far = (datetime.now(timezone.utc) + timedelta(days=NO_DATE_HORIZON_D)).strftime("%Y-%m-%dT%H:00:00Z")
        for z in undated: z.work_starts = far
        pts = [p for z in zones for p in z.polygon]
        val = [row(w) for w in plan(site_id, sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts), zones)]
        names, nodate = {z.zone_id: z.name for z in zones}, {z.zone_id for z in undated}
        top = max([w["priority"] for w in val if w["zone_id"] in nodate] or [1])
        for w in val:
            w["zone_name"] = names.get(w["zone_id"], "")
            if w["zone_id"] in nodate:   # don't claim a start date nobody gave: say so, and rank relative to the best hour
                w["reasons"][0] = "Active construction (no scheduled work date set): ranked on weather and turtle activity"
                w["priority"] = round(w["priority"] / top, 2)
        val.sort(key=lambda w: (-w["priority"], w["start"]))
        if saved:
            try: saved.write_text(json.dumps({"fetched": pipeline.now_utc(), "windows": val}))
            except OSError: pass
    except Exception as e:
        if not (saved and saved.exists()):
            print(f"  planner unavailable ({e}); no saved plan"); return [] if zones else None
        old = json.loads(saved.read_text()); val = old["windows"]
        print(f"  planner unavailable ({e}); serving the plan saved {old['fetched']}")
        for w in val: w["reasons"] = [*w["reasons"][:1], f"Offline: forecast from {old['fetched']}", *w["reasons"][1:]]
        return val
    _plan_cache.update(key=key, val=val); return val


def create_app(store: SqliteAlertStore, mock_zones: bool = False, mock_detect: bool = False):
    """GET /thumbnails/{name} comes from assistant.app_router and serves <store.media_dir>/thumbnails."""
    from fastapi import APIRouter
    data = Path(store.media_dir)

    first, r = APIRouter(), APIRouter()   # first: overrides of assistant.app_router (GET /alerts, /plan); r: new routes,
                                          # mounted after, so /alerts/changes still wins over /alerts/{alert_id}

    def run(folder, site_id, flight_id=None, mock=False, no_geofence=False, photos=None):
        try:
            return pipeline.run_flight(folder, site_id, store, flight_id, pipeline.mock_detector() if (mock or mock_detect) else None,
                                       geofence=None if no_geofence else "auto", photos=photos)
        except ValueError as e: raise HTTPException(400, str(e))
        except RuntimeError as e: raise HTTPException(503, str(e))

    @r.post("/flights")
    def upload_flight(file: UploadFile = File(...), site_id: str = Form("grayson"), flight_id: Optional[str] = Form(None),
                      mock_detect: bool = Form(False), no_geofence: bool = Form(False)):
        dest = data / "flights" / uuid.uuid4().hex[:12]
        dest.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile() as tmp:
            shutil.copyfileobj(file.file, tmp); tmp.seek(0)
            try:
                with zipfile.ZipFile(tmp) as z:
                    for m in z.infolist():   # photos only; extract() already strips absolute and ../ paths
                        if m.filename.upper().endswith(".JPG"): z.extract(m, dest)
            except zipfile.BadZipFile: raise HTTPException(400, "upload a .zip of the flight folder")
        return run(dest, site_id, flight_id, mock_detect, no_geofence)

    @r.post("/flights/local")
    def local_flight(p: LocalFlight):
        if not Path(p.folder).is_dir(): raise HTTPException(400, f"not a folder on this laptop: {p.folder}")
        return run(p.folder, p.site_id, p.flight_id, p.mock_detect, p.no_geofence, p.photos)

    @r.get("/flights")
    def flights(site_id: Optional[str] = None): return store.flights(site_id)

    @r.get("/videos")
    def videos():
        """Recorded drone videos beside the database (<db folder>/videos/<name>.mp4) with the detector's track
        (<name>.json, made by turtles.backend.video_track after landing), for the app's flight-video screen."""
        out = []
        for mp4 in sorted((data / "videos").glob("*.mp4")):
            tr = mp4.with_suffix(".json"); t = json.loads(tr.read_text()) if tr.exists() else {}
            out.append({"name": mp4.stem, "video": f"videos/{mp4.name}", "track": f"videos/{tr.name}" if tr.exists() else "",
                        **{k: t.get(k) for k in ("title", "caption", "model", "recorded", "sample_fps", "ms_per_frame")}})
        return out

    @r.get("/videos/{name}")
    def video_file(name: str, request: Request):
        from fastapi.responses import FileResponse, Response
        f = data / "videos" / Path(name).name
        if f.suffix not in (".mp4", ".json") or not f.is_file(): raise HTTPException(404)
        if f.suffix == ".json": return FileResponse(f, media_type="application/json", headers={"Cache-Control": "no-store"})
        size, rng = f.stat().st_size, request.headers.get("range", "")
        if not rng.startswith("bytes="):   # whole file; Safari and phones then ask for ranges
            return FileResponse(f, media_type="video/mp4", headers={"Accept-Ranges": "bytes"})
        a, _, b = rng[6:].split(",")[0].partition("-")
        start = int(a) if a else max(0, size - int(b)); end = min(int(b) if a and b else size - 1, size - 1, start + (8 << 20) - 1)
        if start >= size: return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
        with open(f, "rb") as fh: fh.seek(start); chunk = fh.read(end - start + 1)
        return Response(chunk, status_code=206, media_type="video/mp4",
                        headers={"Content-Range": f"bytes {start}-{end}/{size}", "Accept-Ranges": "bytes", "Content-Length": str(len(chunk))})

    @first.get("/alerts")
    def alerts(site_id: Optional[str] = None, status: Optional[str] = None):
        out = [assistant.as_contract(a) for a in store.list(status or "all", site_id)]
        out.sort(key=lambda a: a.get("number") or 0)
        out.sort(key=lambda a: a.get("created_at") or "", reverse=True)   # newest first; same-time spots keep spot order
        return out

    @r.get("/alerts/{alert_id}")
    def one_alert(alert_id: str):
        a = store.get(alert_id)
        if a is None: raise HTTPException(404, "no such alert")
        return assistant.as_contract(a)

    @r.post("/alerts/{alert_id}/thermal")
    def thermal(alert_id: str, file: UploadFile = File(...), lat: float = Form(...), lon: float = Form(...),
                user: str = Form("")):
        a = store.get(alert_id)
        if a is None: raise HTTPException(404, "no such alert")
        thermal_dir = data / "thermal"; thermal_dir.mkdir(parents=True, exist_ok=True)
        n = len(list(thermal_dir.glob(f"{a['alert_id']}-t*.jpg"))) + 1
        path = thermal_dir / f"{a['alert_id']}-t{n}.jpg"
        with open(path, "wb") as f: shutil.copyfileobj(file.file, f)
        from PIL import Image
        try:
            with Image.open(path) as im: w, h = im.size
        except Exception: raise HTTPException(400, "not an image")
        ts = pipeline.now_utc()
        fr = Frame(frame_id=f"{a['alert_id']}-t{n}", flight_id=a.get("flight_id", ""), site_id=a.get("site_id", "grayson"),
                   sensor=Sensor.THERMAL, path=str(path), timestamp=ts, lat=lat, lon=lon, alt_m=1.5, yaw_deg=0.0,
                   width_px=w, height_px=h, hfov_deg=HFOV_DEG["flir_one_edge_pro"])
        try: dets = thermal_detector()(fr, str(path)) or []
        except NotImplementedError: raise HTTPException(503, "detector.detect_thermal() isn't implemented yet (Jake)")
        for i, d in enumerate(dets, 1):
            d.detection_id, d.frame_id, d.sensor = f"{fr.frame_id}-d{i}", fr.frame_id, Sensor.THERMAL
            d.lat, d.lon = lat, lon   # handheld: the phone's GPS is the spot (detection/README)
        store.add_frames([fr]); store.actor = user
        try: return assistant.as_contract(refuse_with_thermal(store, a, dets))
        finally: store.actor = ""

    @first.get("/plan")
    def plan(site_id: str = "grayson"):
        if mock_zones: return json.loads((MOCK / "windows.json").read_text())   # --mock: sample windows for the mock lot
        got = live_plan(site_id, data)
        return got if got is not None else []

    store.plan_fn = (lambda: json.loads((MOCK / "windows.json").read_text())) if mock_zones else (lambda: live_plan("grayson", data))   # A.E.R.O.'s get_flight_plan
    app = assistant.create_app(store, mock_zones=mock_zones, first=first)
    app.include_router(r)
    return app


def open_store(db: str, pack: Optional[str] = None, mock: bool = False) -> SqliteAlertStore:
    fresh = not Path(db).exists()
    s = SqliteAlertStore(db)
    if pack:
        n = s.import_pack(pack)
        if n: print(f"backend: imported {n} spots from {Path(pack).name}")
        state = Path(pack).with_name(Path(pack).stem + "_state.json")
        if fresh and (k := s.import_state(state)): print(f"backend: carried over field changes for {k} spots from {state.name}")
    elif mock and not s.alerts:
        s.add_alerts(assistant.AlertStore.from_alerts(MOCK / "alerts.json").alerts.values())
    return s


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="What About the Turtles backend (SQLite + A.E.R.O. + app)")
    ap.add_argument("--db", help="SQLite file (default: turtles.db beside the pack)"); ap.add_argument("--pack", help="relocation pack JSON (real pins)")
    ap.add_argument("--mock", action="store_true", help="mock alerts and zones (no real data needed)")
    ap.add_argument("--mock-detect", action="store_true", help="flights use mock boxes until Jake's model is in")
    ap.add_argument("--reset", action="store_true", help="delete the database first (fresh demo)")
    ap.add_argument("--port", type=int, default=8000)
    a = ap.parse_args()
    if not a.db:
        if not a.pack: ap.error("--db is required without --pack (keep it out of the repo, e.g. in OneDrive)")
        a.db = str(Path(a.pack).with_name("turtles.db"))
    if a.reset and Path(a.db).exists(): Path(a.db).unlink(); print(f"backend: deleted {a.db}")
    store = open_store(a.db, a.pack, a.mock)
    import uvicorn
    print(f"backend: {len(store.alerts)} alerts in {a.db}, {len(store.flights())} flights, "
          f"detector: {'MOCK' if a.mock_detect else 'turtles.detection.detector'}, "
          f"password: {'ON' if os.environ.get('TURTLE_APP_PASSWORD') else 'OFF (set TURTLE_APP_PASSWORD before sharing a link)'} "
          f"-> http://localhost:{a.port}")
    uvicorn.run(create_app(store, mock_zones=a.mock, mock_detect=a.mock_detect), host="0.0.0.0", port=a.port)   # real site unless --mock
