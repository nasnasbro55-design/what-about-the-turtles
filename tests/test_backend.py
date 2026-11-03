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
    dji_photo(d / "DJI_tilted_0099_V.JPG", pitch=-60)           # not straight down: skipped
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
    with Image.open(out) as im: assert min(im.size) > 50


def test_notify_message():
    subj, body = notify.message([{"number": 3, "lat": 38.79, "lon": -77.64, "score": 0.81}], "F-20261104-01")
    assert subj == "A.E.R.O.: 1 likely turtle (F-20261104-01)" and "Spot 3: 38.790000, -77.640000 (score 0.81)" in body


# --- API ------------------------------------------------------------------------------------------------

@pytest.fixture
def client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.delenv("TURTLE_APP_PASSWORD", raising=False)
    monkeypatch.setattr(pipeline, "real_detector", lambda: two_view_detector)
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
