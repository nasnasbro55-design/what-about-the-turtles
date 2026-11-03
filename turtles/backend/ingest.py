"""Ingest: a folder of drone photos -> list[Frame]. Ethan owns this.

Tag names VERIFIED on real DJI Mavic 3 Enterprise photos (Logan's Sept 29 Grayson flight).
They're in each JPG's XMP block as drone-dji:<Name>="value":

    GpsLatitude / GpsLongitude -> lat, lon (e.g. "+38.794225136"; standard EXIF GPS is there too)
    RelativeAltitude           -> alt_m, meters above the takeoff point (e.g. "+115.810")
    GimbalPitchDegree          -> about -90 means straight down; skip frames more than ~5 deg off
    GimbalYawDegree +
    GimbalRollDegree           -> yaw_deg = turtles.geo.nadir_yaw(yaw, roll)   <- REQUIRED, see below
    UTCAtExposure              -> timestamp (e.g. "2026-09-29T16:50:12.890123"; already UTC)
    RtkFlag                    -> 50 = RTK fixed (cm-level); 16 = standard GPS (~1-1.5 m). Sept 29 = 16.

Gotchas found in the real photos:
  1. Heading flips. Pointing straight down, the drone reports yaw -155.9/roll 0 on some photos and
     yaw +24.1/roll 180 on others - the same orientation. Without nadir_yaw() half the turtles land
     on the wrong side of the photo (up to ~20 m off at 50 ft).
  2. Don't use EXIF DateTimeOriginal. It's local time with no timezone, and on Sept 29 the drone's
     clock was ~5 minutes off from GPS time (12:55:19 local vs 16:50:12 UTC). Use UTCAtExposure.
  3. Photos are 5280 x 3956; hfov_deg = turtles.geo.HFOV_DEG["m3e_wide"] (70.65, from the camera's
     CalibratedFocalLength). DewarpFlag=0, so lens distortion isn't removed - fine for our accuracy.
  4. Wide-camera photos end in _V.JPG. The flight folder also has a .MRK timestamp file and PPK files
     (.obs/.nav/.bin) - ignore them.

Reading XMP needs no special tools: it's plain text inside the JPG. A regex over the bytes works:
    re.findall(r'drone-dji:(\\w+)="([^"]*)"', xmp_text)
"""
from __future__ import annotations

import re
from pathlib import Path

from turtles.contracts import Frame, Sensor
from turtles.geo import HFOV_DEG, nadir_yaw

MAX_TILT_DEG = 5.0  # frames whose gimbal is further than this from straight down are skipped


def read_xmp(path: str | Path) -> dict[str, str]:
    """All drone-dji:<Name>="value" tags in one DJI JPG (XMP sits in the first ~100 KB)."""
    with open(path, "rb") as f:
        return dict(re.findall(r'drone-dji:(\w+)="([^"]*)"', f.read(300_000).decode("latin1")))


def frame_from_photo(path: str | Path, folder: str | Path, site_id: str, flight_id: str, nadir_only: bool = True) -> Frame | None:
    """Frame for one *_V.JPG, or None if it has no GPS or (nadir_only) the camera wasn't pointed straight down."""
    x = read_xmp(path)
    if "GpsLatitude" not in x or (nadir_only and abs(float(x.get("GimbalPitchDegree", -90)) + 90) > MAX_TILT_DEG):
        return None
    w, h = (5280, 3956)
    return Frame(frame_id=Path(path).stem, flight_id=flight_id, site_id=site_id, sensor=Sensor.RGB,
                 path=str(Path(path).relative_to(folder)), timestamp=x["UTCAtExposure"][:19] + "Z",
                 lat=float(x["GpsLatitude"]), lon=float(x["GpsLongitude"]), alt_m=float(x["RelativeAltitude"]),
                 yaw_deg=nadir_yaw(float(x["GimbalYawDegree"]), float(x["GimbalRollDegree"])),
                 width_px=w, height_px=h, hfov_deg=HFOV_DEG["m3e_wide"])


def ingest_flight(folder: str, site_id: str, flight_id: str) -> list[Frame]:
    """Return one Frame per usable *_V.JPG in folder (searched recursively), sorted by timestamp."""
    return sorted((f for p in Path(folder).rglob("*_V.JPG") if (f := frame_from_photo(p, folder, site_id, flight_id))),
                  key=lambda f: f.timestamp)
