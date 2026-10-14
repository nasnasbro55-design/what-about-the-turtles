"""Shared data contracts for What About the Turtles.

Every component reads and writes these shapes:
    ingest   (Ethan) -> Frame
    detector (Jake)  -> Detection
    fusion   (Ethan) -> Alert
    planner  (Naz)   -> FlightWindow, from Zone + weather forecast
    dashboard (Huy)  <- Alert and FlightWindow, as JSON from the API

Change a field here only after the team agrees - it breaks everyone downstream.
Times are ISO 8601 UTC strings ("2026-10-25T14:03:11Z"). Coordinates are WGS84 decimal degrees.

Check the mock data still matches:  python3 -m turtles.contracts
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from enum import Enum
from pathlib import Path


class Sensor(str, Enum):
    RGB = "rgb"          # drone camera, aerial, pointed straight down
    THERMAL = "thermal"  # FLIR One on a phone, handheld at ground level


class Confidence(str, Enum):
    HIGH = "high"      # act now
    REVIEW = "review"  # a human should look


class Status(str, Enum):
    OPEN = "open"
    CONFIRMED = "confirmed"            # responder found a turtle
    FALSE_POSITIVE = "false_positive"  # nothing there (rock, debris, shadow)
    RELOCATED = "relocated"            # turtle moved off site safely


@dataclass
class Frame:
    """One image (photo, or a frame pulled from video) plus where and when it was taken."""
    frame_id: str
    flight_id: str
    site_id: str
    sensor: Sensor
    path: str          # relative to the flight folder
    timestamp: str
    lat: float
    lon: float
    alt_m: float       # height above ground (takeoff point); ~1.5 for handheld
    yaw_deg: float     # camera heading, clockwise from north
    width_px: int
    height_px: int
    hfov_deg: float    # horizontal field of view for this camera/mode (see turtles.geo.HFOV_DEG)


@dataclass
class Detection:
    """One thing a model thinks is a turtle, in one frame."""
    detection_id: str
    frame_id: str
    sensor: Sensor
    bbox: list[int]    # [x_min, y_min, x_max, y_max] in pixels
    score: float       # 0-1 model confidence
    lat: float         # ground position of the bbox center
    lon: float
    timestamp: str
    model_version: str


@dataclass
class Alert:
    """What a human acts on: one probable turtle at one spot."""
    alert_id: str
    site_id: str
    flight_id: str
    lat: float
    lon: float
    confidence: Confidence
    score: float               # best detection score in the cluster
    sensors: list[Sensor]
    detection_ids: list[str]
    thumbnail: str             # crop of the best detection, served by the API
    created_at: str
    status: Status = Status.OPEN
    note: str = ""


@dataclass
class Zone:
    """A part of the site with scheduled work, from W.A. Hazel's schedule. Drawn on the map."""
    zone_id: str
    site_id: str
    name: str
    polygon: list[list[float]]  # [[lat, lon], ...]
    work: str                   # "clearing", "grading", "staging", ...
    work_starts: str            # when equipment arrives


@dataclass
class FlightWindow:
    """Planner output: a recommended time to survey one zone. Shown in the app, best first."""
    window_id: str
    site_id: str
    zone_id: str
    start: str
    end: str
    priority: float      # 0-1, higher = fly this first
    thermal_ok: bool     # planner expects turtles to stand out on thermal in this window
    reasons: list[str]   # plain English, shown to Logan / the site manager


_ENUMS = {"sensor": Sensor, "confidence": Confidence, "status": Status}


def from_dict(cls, d: dict):
    """Build a contract object from a dict, rejecting unknown or missing fields."""
    names = {f.name for f in fields(cls)}
    if extra := set(d) - names:
        raise ValueError(f"{cls.__name__}: unknown fields {sorted(extra)}")
    kw = {k: _ENUMS[k](v) if k in _ENUMS else v for k, v in d.items()}
    if "sensors" in kw:
        kw["sensors"] = [Sensor(s) for s in kw["sensors"]]
    return cls(**kw)


def load(cls, path) -> list:
    return [from_dict(cls, d) for d in json.loads(Path(path).read_text())]


def dump(items, path) -> None:
    Path(path).write_text(json.dumps([asdict(i) for i in items], indent=2) + "\n")


if __name__ == "__main__":
    mock = Path(__file__).parent / "architecture" / "mock"
    for cls, name in ((Frame, "frames"), (Detection, "detections"), (Alert, "alerts"),
                      (Zone, "zones"), (FlightWindow, "windows")):
        print(f"{name}.json: {len(load(cls, mock / f'{name}.json'))} records match the contract")
