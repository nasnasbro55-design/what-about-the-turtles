"""Backend tests: ingest on synthetic DJI photos, SQLite store, pipeline, API.  python3 -m pytest -q"""
import io
import json
import zipfile

import pytest

from turtles.backend import api, ingest, notify, pipeline
from turtles.backend.db import SqliteAlertStore
from turtles.contracts import Detection, Sensor

PACK = [{"alert_id": "spot-1", "label": "Spot 1: Open bare dirt", "lat": 38.79, "lon": -77.64,
         "suggestion": {"reasons": ["Carry it 44 m northeast to dense cover."], "distance_m": 44, "bearing_deg": 45}},
        {"alert_id": "spot-2", "label": "Spot 2: Rut", "lat": 38.791, "lon": -77.641,
         "suggestion": {"reasons": ["Carry it 51 m northwest to dense cover."], "distance_m": 51, "bearing_deg": 315}}]


def dji_photo(path, lat=38.79453, lon=-77.64542, alt=15.0, pitch=-90.0, yaw=-155.9, roll=0.0,
              utc="2026-11-04T15:00:00.123456", size=(1056, 792)):
    """A small JPEG with a DJI-style XMP block (APP1), like Logan's M3E photos."""
    from PIL import Image
    buf = io.BytesIO(); Image.new("RGB", size, (90, 120, 60)).save(buf, "JPEG"); jpg = buf.getvalue()
    xmp = (f'<x:xmpmeta><rdf:Description drone-dji:GpsLatitude="+{lat}" drone-dji:GpsLongitude="{lon}" '
           f'drone-dji:RelativeAltitude="+{alt}" drone-dji:GimbalPitchDegree="{pitch}" drone-dji:GimbalYawDegree="{yaw}" '
           f'drone-dji:GimbalRollDegree="{roll}" drone-dji:UTCAtExposure="{utc}" drone-dji:RtkFlag="16"/></x:xmpmeta>').encode()
    payload = b"http://ns.adobe.com/xap/1.0/\x00" + xmp
    path.write_bytes(jpg[:2] + b"\xff\xe1" + (len(payload) + 2).to_bytes(2, "big") + payload + jpg[2:])
    return path


def sub(tmp_path, name):
    (tmp_path / name).mkdir(); return tmp_path / name


def flight(tmp_path, n=4):
    d = tmp_path / "flight"; d.mkdir()
    for i in range(n):   # alternate the heading flip the real photos have
        dji_photo(d / f"DJI_2026110415{i:04d}_{i + 1:04d}_V.JPG", lat=38.79453 + i * 0.00002,
                  yaw=-155.9 if i % 2 else 24.1, roll=0 if i % 2 else 180, utc=f"2026-11-04T15:00:{10 - i:02d}.5")
    dji_photo(d / "DJI_tilted_0099_V.JPG", pitch=-30)           # too close to the horizon: skipped
    dji_photo(d / "DJI_tele_0100_T.JPG")                        # other camera: skipped
    (d / "DJI_flight.MRK").write_text("timestamps")             # ignored
    return d


# --- ingest ---------------------------------------------------------------------------------------------

def test_ingest_reads_xmp_skips_bad_photos_and_sorts(tmp_path):
    fr = ingest.ingest_flight(str(flight(tmp_path)), "grayson", "F-20261104-01")
    assert len(fr) == 4 and fr[0].frame_id == "DJI_20261104150003_0004_V"          # photo stem, as the detector expects
    assert [f.timestamp for f in fr] == sorted(f.timestamp for f in fr) and fr[0].timestamp == "2026-11-04T15:00:07Z"
    assert {round(f.yaw_deg, 1) for f in fr} == {-155.9}                      # flipped headings agree after nadir_yaw
    f = fr[0]
    assert (f.width_px, f.height_px, f.alt_m, f.hfov_deg, f.sensor) == (1056, 792, 15.0, 70.65, Sensor.RGB)
    assert f.path.endswith("_V.JPG") and "/" not in f.path


def test_db_upgrades_frames_table_made_before_tilt(tmp_path):
    import sqlite3
    c = sqlite3.connect(tmp_path / "old.db")
    c.execute("CREATE TABLE frames (frame_id TEXT PRIMARY KEY, flight_id TEXT, site_id TEXT, sensor TEXT, path TEXT, timestamp TEXT,"
              " lat REAL, lon REAL, alt_m REAL, yaw_deg REAL, width_px INTEGER, height_px INTEGER, hfov_deg REAL)"); c.commit(); c.close()
    s = SqliteAlertStore(tmp_path / "old.db"); fr = ingest.ingest_flight(str(flight(tmp_path)), "grayson", "F1")
    s.add_frames(fr); assert s.frame(fr[0].frame_id).pitch_deg == -90


def test_utc_parsing_any_fraction_length():
    assert {ingest.utc_iso(t) for t in ("2026-11-04T15:00:10.5", "2026-11-04T15:00:10.972224", "2026-11-04T15:00:10Z",
                                        "2026-11-04T15:00:10")} == {"2026-11-04T15:00:10Z"}


def test_flight_id_from_first_photo_date():
    assert ingest.flight_id_for("2026-11-04T15:00:07Z", 2) == "F-20261104-02"


# --- store ----------------------------------------------------------------------------------------------

def pack_file(tmp_path):
    p = tmp_path / "voice_pack.json"; p.write_text(json.dumps(PACK)); return p


def test_store_survives_restart_and_pack_import_is_idempotent(tmp_path):
    db = tmp_path / "t.db"
    s = SqliteAlertStore(db); assert s.import_pack(pack_file(tmp_path)) == 2 and s.import_pack(pack_file(tmp_path)) == 0
    s.update("2", status="relocated", species="Eastern box turtle", note="moved north", record={"mass_g": 410})
    s2 = SqliteAlertStore(db)
    a = s2.get("spot-2")
    assert a["status"] == "relocated" and a["notes"] == ["moved north"] and a["record"]["mass_g"] == 410
    assert s2.relocation("spot-1")["distance_m"] == 44                        # pack's relocation kept in the row


def test_old_json_state_is_carried_over(tmp_path):
    pack = pack_file(tmp_path)
    (tmp_path / "voice_pack_state.json").write_text(json.dumps({"spot-1": {"status": "confirmed", "species": "Box"}}))
    s = api.open_store(str(tmp_path / "t.db"), str(pack))
    assert s.get("spot-1")["status"] == "confirmed" and SqliteAlertStore(tmp_path / "t.db").get("spot-1")["species"] == "Box"


# --- pipeline -------------------------------------------------------------------------------------------

def two_view_detector(frame, image_path):
    """The same turtle seen in every photo at 0.8 -> one high alert (multi-view rule)."""
    return [Detection("", frame.frame_id, Sensor.RGB, [500, 370, 540, 410], 0.8, 38.79455, -77.64542, frame.timestamp, "rgb-test")]


def test_pipeline_end_to_end(tmp_path, capsys):
    s = SqliteAlertStore(tmp_path / "t.db"); s.import_pack(pack_file(tmp_path))
    out = pipeline.run_flight(flight(tmp_path), "grayson", s, detect=two_view_detector)
    assert out == {"flight_id": "F-20261104-01", "frames": 4, "detections": 4, "off_site": 0, "alerts": 1, "high": 1}
    a = next(a for a in s.list() if a.get("flight_id") == "F-20261104-01")
    assert a["number"] == 3 and a["name"] == "Spot 3: detection 80%" and a["confidence"] == "high" and len(a["detection_ids"]) == 4
    assert (tmp_path / a["thumbnail"]).exists()                               # thumbnails/ beside the database
    assert len(s.detections(a["detection_ids"])) == 4 and s.frame(s.detections(a["detection_ids"])[0].frame_id)
    assert "notify (off" in capsys.readouterr().out
    assert pipeline.run_flight(flight(sub(tmp_path, "b")), "grayson", s, detect=two_view_detector)["flight_id"] == "F-20261104-02"


def test_pipeline_drops_detections_off_site(tmp_path):
    def near_and_far(frame, path):
        return [Detection("", frame.frame_id, Sensor.RGB, [500, 370, 540, 410], 0.8, 38.79455, -77.64542, frame.timestamp, "t"),
                Detection("", frame.frame_id, Sensor.RGB, [100, 100, 140, 140], 0.9, 38.80, -77.60, frame.timestamp, "t")]
    s = SqliteAlertStore(tmp_path / "t.db")
    out = pipeline.run_flight(flight(tmp_path), "grayson", s, detect=near_and_far)
    assert (out["detections"], out["off_site"], out["alerts"]) == (4, 4, 1)
    assert pipeline.run_flight(flight(sub(tmp_path, "x")), "grayson", s,
                               detect=near_and_far, geofence=None)["alerts"] == 2


def test_pipeline_says_when_the_detector_is_missing(tmp_path):
    def missing(f, p): raise NotImplementedError
    with pytest.raises(RuntimeError, match="mock-detect"):
        pipeline.run_flight(flight(tmp_path), "grayson", SqliteAlertStore(tmp_path / "t.db"), detect=missing)
    def no_weights(f, p): raise FileNotFoundError("aero_turtle.pt")
    with pytest.raises(RuntimeError, match="AERO_WEIGHTS"):
        pipeline.run_flight(flight(sub(tmp_path, "w")), "grayson",
                            SqliteAlertStore(tmp_path / "t.db"), detect=no_weights)


def test_mock_detector_runs_on_real_frames(tmp_path):
    out = pipeline.run_flight(flight(tmp_path), "grayson-mock", SqliteAlertStore(tmp_path / "t.db"), detect=pipeline.mock_detector())
    assert out["frames"] == 4 and out["detections"] == 4 and out["alerts"] >= 1


def test_thumbnail_at_photo_edge_stays_inside(tmp_path):
    from PIL import Image
    img = dji_photo(tmp_path / "a_V.JPG"); out = tmp_path / "t.jpg"
    assert pipeline.make_thumbnail(img, [1040, 780, 1100, 830], out)   # box hangs off the bottom-right corner
    with Image.open(out) as im: assert max(im.size) == pipeline.THUMB_OUT_PX and min(im.size) > 50   # small crops scaled up


def test_notify_message():
    subj, body = notify.message([{"number": 3, "lat": 38.79, "lon": -77.64, "score": 0.81}], "F-20261104-01")
    assert subj == "A.E.R.O.: 1 likely turtle (F-20261104-01)" and "Spot 3: 38.790000, -77.640000 (score 0.81)" in body


# --- API ------------------------------------------------------------------------------------------------

@pytest.fixture
def client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.delenv("TURTLE_APP_PASSWORD", raising=False)
    monkeypatch.setattr(pipeline, "real_detector", lambda: two_view_detector)
    from turtles.planner import planner
    def offline(*a, **k): raise OSError("tests never call the real weather service")
    monkeypatch.setattr(planner, "fetch_forecast", offline); api._plan_cache.clear()
    for v in ("TURTLE_ZONES", "TURTLE_WORK_STARTS"): monkeypatch.delenv(v, raising=False)
    s = api.open_store(str(tmp_path / "t.db"), str(pack_file(tmp_path)))
    c = TestClient(api.create_app(s)); c.store = s; c.tmp = tmp_path
    return c


def zipped(folder):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for p in folder.iterdir(): z.write(p, f"DCIM/{p.name}")
    return buf.getvalue()


def test_api_flight_upload_alerts_and_thumbnail(client):
    r = client.post("/flights", files={"file": ("f.zip", zipped(flight(client.tmp)), "application/zip")}, data={"site_id": "grayson"})
    assert r.status_code == 200 and r.json()["alerts"] == 1
    al = client.get("/alerts").json()
    assert al[0]["flight_id"] == "F-20261104-01" and al[0]["confidence"] == "high"   # newest first
    assert [a["alert_id"] for a in al[1:]] == ["spot-1", "spot-2"]
    assert client.get(f"/{al[0]['thumbnail']}").headers["content-type"] == "image/jpeg"
    assert client.get(f"/alerts/{al[0]['alert_id']}").json()["number"] == 3
    assert client.get("/flights").json()[0]["frames"] == 4
    assert client.get("/alerts?status=open&site_id=nowhere").json() == []


def test_api_routes_kept_from_assistant(client):
    assert client.patch("/alerts/spot-1", json={"status": "confirmed", "user": "Naz"}).json()["status"] == "confirmed"
    assert client.get("/alerts/changes").json()["by"] == "Naz"                  # not swallowed by /alerts/{alert_id}
    assert SqliteAlertStore(client.tmp / "t.db").get("spot-1")["status"] == "confirmed"
    assert [a["alert_id"] for a in client.get("/alerts?status=confirmed").json()] == ["spot-1"]
    assert client.get("/alerts/spot-1/relocation").json()["distance_m"] == 44
    assert client.get("/plan").status_code == 200 and client.get("/alerts/nope").status_code == 404


def test_api_local_folder_and_bad_input(client):
    assert client.post("/flights/local", json={"folder": str(flight(client.tmp))}).json()["frames"] == 4
    assert (client.tmp / "t.db").exists() and not list(client.tmp.glob("thermal"))
    assert client.post("/flights/local", json={"folder": "/no/such"}).status_code == 400
    assert client.post("/flights", files={"file": ("x.zip", b"not a zip")}).status_code == 400


def test_api_thermal_check_upgrades_alert(client, monkeypatch):
    def hot(frame, path): return [Detection("t", frame.frame_id, Sensor.THERMAL, [10, 10, 30, 30], 0.9, 0, 0, frame.timestamp, "thermal-v1")]
    monkeypatch.setattr(api, "thermal_detector", lambda: hot)
    from PIL import Image
    buf = io.BytesIO(); Image.new("RGB", (160, 120)).save(buf, "JPEG")
    r = client.post("/alerts/spot-1/thermal", files={"file": ("t.jpg", buf.getvalue(), "image/jpeg")}, data={"lat": 38.79, "lon": -77.64})
    a = r.json()
    assert r.status_code == 200 and a["sensors"] == ["thermal"] and "hot spot found" in a["note"]
    def missing(frame, path): raise NotImplementedError
    monkeypatch.setattr(api, "thermal_detector", lambda: missing)
    assert client.post("/alerts/spot-2/thermal", files={"file": ("t.jpg", buf.getvalue())}, data={"lat": 1, "lon": 1}).status_code == 503


# --- /zones and /plan on the real site (no mock zones 12 km away) ---------------------------------------

def forecast_from_now(hours=48):
    """Open-Meteo-shaped forecast starting this hour: sunny, dry, light wind, sun 11:00-22:00 UTC each day."""
    from datetime import datetime, timedelta, timezone
    t0 = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    ts = [(t0 + timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M") for i in range(hours)]
    days = sorted({t[:10] for t in ts})
    return {"hourly": {"time": ts, "temperature_2m": [20.0] * hours, "soil_temperature_0cm": [15.0] * hours,
                       "shortwave_radiation": [500.0] * hours, "cloud_cover": [10.0] * hours, "precipitation": [0.0] * hours,
                       "wind_speed_10m": [3.0] * hours},
            "daily": {"sunrise": [f"{d}T11:00" for d in days], "sunset": [f"{d}T22:00" for d in days]}}


def test_zones_are_the_real_site_without_a_pack(client):
    z = client.get("/zones").json()
    assert [x["zone_id"] for x in z][0] == "SITE" and abs(z[0]["polygon"][0][0] - 38.79) < 0.01   # Grayson, not 38.76 mock


def test_plan_on_real_site_says_no_work_date(client, monkeypatch):
    from turtles.planner import planner
    monkeypatch.setattr(planner, "fetch_forecast", lambda *a, **k: forecast_from_now()); api._plan_cache.clear()
    w = client.get("/plan").json()
    assert w and {x["zone_id"] for x in w} == {"SITE"} and w[0]["zone_name"] == "Grayson Overlook site boundary"
    assert w[0]["reasons"][0].startswith("Active construction (no scheduled work date set)") and w[0]["priority"] == 1.0
    assert all(" starts " not in x["reasons"][0] for x in w)                      # no invented start date
    assert (client.tmp / "plan_grayson.json").exists()                            # saved for offline use


def test_plan_uses_a_real_work_date_when_given(client, monkeypatch):
    from datetime import datetime, timedelta, timezone
    from turtles.planner import planner
    monkeypatch.setattr(planner, "fetch_forecast", lambda *a, **k: forecast_from_now()); api._plan_cache.clear()
    monkeypatch.setenv("TURTLE_WORK_STARTS", (datetime.now(timezone.utc) + timedelta(days=1, hours=12)).strftime("%Y-%m-%dT%H:00:00Z"))
    assert client.get("/plan").json()[0]["reasons"][0].startswith("Active construction starts ")


def test_plan_offline_serves_last_saved_plan(client, monkeypatch):
    from turtles.planner import planner
    monkeypatch.setattr(planner, "fetch_forecast", lambda *a, **k: forecast_from_now()); api._plan_cache.clear()
    good = client.get("/plan").json()
    def no_wifi(*a, **k): raise OSError("no route to host")
    monkeypatch.setattr(planner, "fetch_forecast", no_wifi); api._plan_cache.clear()
    off = client.get("/plan").json()
    assert [x["window_id"] for x in off] == [x["window_id"] for x in good] and off[0]["reasons"][1].startswith("Offline: forecast from ")


def test_plan_offline_with_nothing_saved_is_empty_not_mock(client, monkeypatch):
    from turtles.planner import planner
    def no_wifi(*a, **k): raise OSError("no route to host")
    monkeypatch.setattr(planner, "fetch_forecast", no_wifi); api._plan_cache.clear()
    assert client.get("/plan").json() == []


def test_mock_flag_keeps_sample_zones_and_windows(tmp_path):
    from fastapi.testclient import TestClient
    c = TestClient(api.create_app(api.open_store(str(tmp_path / "m.db"), mock=True), mock_zones=True))
    assert c.get("/zones").json()[0]["site_id"] == "grayson-mock" and c.get("/plan").json()[0]["site_id"] == "grayson-mock"


def test_zones_include_logans_official_limits(client):
    import json as _j
    z = {x["zone_id"]: x for x in client.get("/zones").json()}
    assert set(z) == {"SITE", "LOD-1", "LOD-2"} and z["LOD-1"]["work"] == "limits of disturbance"
    kml = _j.loads((api.ROOT / "planner" / "sites" / "grayson_lod.geojson").read_text())["features"]
    assert [len(z[f"LOD-{i}"]["polygon"]) for i in (1, 2)] == [len(f["geometry"]["coordinates"][0]) for f in kml]   # every KML point
    lat, lon = z["LOD-1"]["polygon"][0]; assert 38.78 < lat < 38.80 and -77.66 < lon < -77.64           # [lat, lon], on site
    assert {w["zone_id"] for w in client.get("/plan").json()} <= {"SITE"}                                # planner still on the fence line


def test_copy_spots_keeps_field_records_and_drops_flight_alerts(tmp_path):
    from turtles.backend.db import copy_spots
    s = SqliteAlertStore(tmp_path / "old.db"); s.import_pack(pack_file(tmp_path))
    s.update("spot-2", status="relocated", species="Eastern box turtle", record={"mass_g": 410}, note="moved north")
    pipeline.run_flight(flight(tmp_path), "grayson", s, detect=two_view_detector)
    assert len(s.alerts) == 3
    before = (tmp_path / "old.db").read_bytes()
    assert copy_spots(tmp_path / "old.db", tmp_path / "demo.db") == 2
    n = SqliteAlertStore(tmp_path / "demo.db")
    assert set(n.alerts) == {"spot-1", "spot-2"} and n.flights() == [] and n.get("spot-2")["record"] == {"mass_g": 410}
    assert n.get("spot-2")["notes"] == ["moved north"] and n.relocation("spot-1")["distance_m"] == 44
    assert (tmp_path / "old.db").read_bytes() == before                                     # source untouched
    with pytest.raises(FileExistsError): copy_spots(tmp_path / "old.db", tmp_path / "demo.db")   # never overwrites
    n.import_pack(pack_file(tmp_path)); assert len(n.alerts) == 2                            # --pack on start adds nothing


def test_alert_panel_shows_the_detection_close_up():
    html = (api.ROOT / "ui_docs" / "index.html").read_text()
    assert 'id="detailPhoto"' in html and "onerror=" in html.split('id="detailPhoto"')[1].split(">")[0]
    fill = html.split("function fillDetail(alert)")[1].split("\n  }\n")[0]
    assert "alert.thumbnail" in fill and 'API_BASE + "/" + alert.thumbnail' in fill and "photoBox.style.display = 'none'" in fill


def test_aero_knows_flights_and_detections_on_the_server(client):
    """A.E.R.O. runs on the same SQLite store: after a flight it can say what the flight found and which spot is first."""
    from turtles.backend.assistant import run_tool
    client.post("/flights", files={"file": ("f.zip", zipped(flight(client.tmp)), "application/zip")}, data={"site_id": "grayson"})
    f = run_tool(client.store, "list_flights", {})
    assert f["total"] == 1 and f["flights"][0]["frames"] == 4 and f["flights"][0]["alerts"] == 1
    top = run_tool(client.store, "list_alerts", {"status": "open"})["alerts"][0]
    assert top["number"] == 3 and top["source"].startswith("drone") and top["source"].endswith("high")
    assert run_tool(client.store, "get_alert", {"alert_id": "3"})["close_up_photo"]
    assert "windows" in run_tool(client.store, "get_flight_plan", {}) and "note" not in run_tool(client.store, "get_flight_plan", {})
