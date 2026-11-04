"""SQLite storage: frames, detections and alerts in one file, mirroring turtles/contracts.py.

SqliteAlertStore is a drop-in AlertStore (same list/get/update/touch/relocation), so A.E.R.O. and Huy's app
read and write the same rows. Field changes survive restarts without the old <pack>_state.json.

    store = SqliteAlertStore("turtles.db")            # opens or creates the file
    store.import_pack("voice_pack_2026-10-24.json")   # first run only: the real Grayson pins
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from turtles.backend.assistant import AlertStore
from turtles.contracts import Alert, Detection, Frame

SCHEMA = """
CREATE TABLE IF NOT EXISTS flights (
    flight_id TEXT PRIMARY KEY, site_id TEXT, folder TEXT, created_at TEXT,
    frames INTEGER, detections INTEGER, alerts INTEGER, model_version TEXT);
CREATE TABLE IF NOT EXISTS frames (
    frame_id TEXT PRIMARY KEY, flight_id TEXT, site_id TEXT, sensor TEXT, path TEXT, timestamp TEXT,
    lat REAL, lon REAL, alt_m REAL, yaw_deg REAL, width_px INTEGER, height_px INTEGER, hfov_deg REAL, pitch_deg REAL DEFAULT -90);
CREATE TABLE IF NOT EXISTS detections (
    detection_id TEXT PRIMARY KEY, frame_id TEXT, sensor TEXT, bbox TEXT, score REAL,
    lat REAL, lon REAL, timestamp TEXT, model_version TEXT);
CREATE TABLE IF NOT EXISTS alerts (
    alert_id TEXT PRIMARY KEY, site_id TEXT, flight_id TEXT, status TEXT, confidence TEXT,
    created_at TEXT, number INTEGER, data TEXT NOT NULL);   -- data = the full alert dict (field log, notes, relocation)
CREATE INDEX IF NOT EXISTS alerts_site ON alerts(site_id, status);
CREATE INDEX IF NOT EXISTS det_frame ON detections(frame_id);
"""


def _plain(v):
    return v.value if hasattr(v, "value") else [_plain(x) for x in v] if isinstance(v, list) else v


def row(obj) -> Dict[str, Any]:
    """A contract dataclass as plain JSON-able values (enums -> strings)."""
    return {k: _plain(v) for k, v in asdict(obj).items()}


class SqliteAlertStore(AlertStore):
    def __init__(self, path="turtles.db"):
        self.path = Path(path)
        self.media_dir = self.path.resolve().parent   # thumbnails/ live beside the database (assistant's GET /thumbnails)
        self.db = sqlite3.connect(self.path, check_same_thread=False)   # FastAPI runs sync routes on a thread pool
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        if "pitch_deg" not in {r[1] for r in self.db.execute("PRAGMA table_info(frames)")}:   # databases made before tilt support
            with self.db: self.db.execute("ALTER TABLE frames ADD COLUMN pitch_deg REAL DEFAULT -90")
        rows = self.db.execute("SELECT data FROM alerts ORDER BY number, created_at").fetchall()
        super().__init__([json.loads(r["data"]) for r in rows])
        self._dirty: set = set()

    # --- alerts -------------------------------------------------------------------------------------------
    def _write(self, a: Dict[str, Any]):
        self.db.execute("INSERT OR REPLACE INTO alerts VALUES (?,?,?,?,?,?,?,?)",
                        (a["alert_id"], a.get("site_id", "grayson"), a.get("flight_id", ""), a["status"],
                         a.get("confidence", "review"), a.get("created_at", ""), a.get("number"), json.dumps(a)))

    def touch(self, a: Dict[str, Any], by: str = "") -> Dict[str, Any]:
        self._dirty.add(a["alert_id"]); return super().touch(a, by)

    def save(self):
        """Called by touch() after every change. Writes the changed alerts (PATCH writes fields straight onto the dict)."""
        with self.db:
            for aid in self._dirty or self.alerts:
                if aid in self.alerts: self._write(self.alerts[aid])
        self._dirty = set()

    def add_alerts(self, alerts: Iterable[Dict[str, Any]], label=None) -> List[Dict[str, Any]]:
        """New alerts (from a flight or a pack) get the next spot numbers. Existing ids are left alone.
        label(alert) -> text after "Spot N: " when the alert has no name yet."""
        n, added = max((a.get("number") or 0 for a in self.alerts.values()), default=0), []
        for a in alerts:
            if a["alert_id"] in self.alerts: continue
            n += 1
            a = {"species": "", "sex": "", "est_length_in": None, "notes": [], "updated_at": "", **a, "number": n}
            a.setdefault("name", f"Spot {n}: {label(a)}" if label else f"Spot {n}")
            self.alerts[a["alert_id"]] = a; added.append(a)
        with self.db:
            for a in added: self._write(a)
        if added:
            self.version += 1
            self.last = {"version": self.version, "alert_id": added[-1]["alert_id"], "label": f"{len(added)} new alert(s)",
                         "status": "open", "by": "drone", "at": ""}
        return added

    def import_pack(self, path) -> int:
        """A relocation pack (python3 -m turtles.planner.relocation ... --out). Safe to run twice."""
        return len(self.add_alerts(AlertStore.from_pack(path).alerts.values()))

    def import_state(self, path) -> int:
        """Carry over field changes saved by the old JSON store (<pack>_state.json)."""
        p = Path(path)
        if not p.exists(): return 0
        n = 0
        for k, v in json.loads(p.read_text()).items():
            if k in self.alerts: self.alerts[k].update(v); self._dirty.add(k); n += 1
        self.save(); return n

    def add_contract_alerts(self, alerts: List[Alert], label=None) -> List[Dict[str, Any]]:
        return self.add_alerts((row(a) for a in alerts), label)

    def list(self, status: str = "all", site_id: Optional[str] = None) -> List[Dict[str, Any]]:
        return [a for a in super().list(status) if site_id in (None, "") or a.get("site_id", "grayson") == site_id]

    # --- frames / detections / flights --------------------------------------------------------------------
    def add_frames(self, frames: List[Frame]):
        with self.db:
            self.db.executemany("INSERT OR REPLACE INTO frames VALUES (:frame_id,:flight_id,:site_id,:sensor,:path,:timestamp,"
                                ":lat,:lon,:alt_m,:yaw_deg,:width_px,:height_px,:hfov_deg,:pitch_deg)", [row(f) for f in frames])

    def add_detections(self, dets: List[Detection]):
        with self.db:
            self.db.executemany("INSERT OR REPLACE INTO detections VALUES (:detection_id,:frame_id,:sensor,:bbox,:score,"
                                ":lat,:lon,:timestamp,:model_version)", [{**row(d), "bbox": json.dumps(d.bbox)} for d in dets])

    def detections(self, ids: Iterable[str]) -> List[Detection]:
        from turtles.contracts import from_dict
        ids = list(ids)
        if not ids: return []
        rows = self.db.execute(f"SELECT * FROM detections WHERE detection_id IN ({','.join('?' * len(ids))})", ids).fetchall()
        return [from_dict(Detection, {**dict(r), "bbox": json.loads(r["bbox"])}) for r in rows]

    def frame(self, frame_id: str) -> Optional[Frame]:
        from turtles.contracts import from_dict
        r = self.db.execute("SELECT * FROM frames WHERE frame_id = ?", (frame_id,)).fetchone()
        return from_dict(Frame, dict(r)) if r else None

    def add_flight(self, **f):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO flights VALUES (:flight_id,:site_id,:folder,:created_at,:frames,"
                            ":detections,:alerts,:model_version)", f)

    def flights(self, site_id: Optional[str] = None) -> List[Dict[str, Any]]:
        q, args = "SELECT * FROM flights", ()
        if site_id: q, args = q + " WHERE site_id = ?", (site_id,)
        return [dict(r) for r in self.db.execute(q + " ORDER BY created_at DESC", args)]

    def flight_folder(self, flight_id: str) -> Optional[str]:
        r = self.db.execute("SELECT folder FROM flights WHERE flight_id = ?", (flight_id,)).fetchone()
        return r["folder"] if r else None

    def next_flight_number(self, day: str) -> int:
        """day = 'YYYYMMDD'. Flights that day so far + 1."""
        return self.db.execute("SELECT COUNT(*) FROM flights WHERE flight_id LIKE ?", (f"F-{day}-%",)).fetchone()[0] + 1
