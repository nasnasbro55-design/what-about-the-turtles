"""Ingest: a folder of drone photos -> list[Frame]. Ethan owns this.

Tag names VERIFIED on real DJI Mavic 3 Enterprise photos (Logan's Sept 29 Grayson flight).
They're in each JPG's XMP block as drone-dji:<Name>="value":

    GpsLatitude / GpsLongitude -> lat, lon (e.g. "+38.794225136"; standard EXIF GPS is there too)
    RelativeAltitude           -> alt_m, meters above the takeoff point (e.g. "+115.810")
    GimbalPitchDegree          -> pitch_deg; -90 = straight down. Tilted photos down to -45 are kept (geo handles tilt)
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
from datetime import datetime, timezone
from pathlib import Path

from turtles.contracts import Frame, Sensor
from turtles.geo import HFOV_DEG, MIN_DEPRESSION_DEG, nadir_yaw

MAX_TILT_DEG = 5.0   # nadir_only: frames further than this from straight down are skipped
# Default: anything from straight down to MIN_DEPRESSION_DEG (-45). Logan's Oct 24 spot flights were shot at -33..-83;
# tilt-aware projection puts the same labeled shell within ~1 m across photos (vs 3-14 m if treated as straight down).
M3E_SIZE = (5280, 3956)
NEEDED = ("GpsLatitude", "GpsLongitude", "RelativeAltitude", "GimbalYawDegree", "UTCAtExposure")


def read_xmp(path: str | Path) -> dict[str, str]:
    """All drone-dji:<Name>="value" tags in one DJI JPG (XMP sits in the first ~100 KB)."""
    with open(path, "rb") as f:
        return dict(re.findall(r'drone-dji:(\w+)="([^"]*)"', f.read(300_000).decode("latin1")))


def image_size(path) -> tuple[int, int]:
    """Real pixel size from the JPEG header; the M3E's 5280 x 3956 if it can't be read."""
    try:
        from PIL import Image
        with Image.open(path) as im: return im.size
    except Exception: return M3E_SIZE


def utc_iso(s: str) -> str:
    """'2026-09-29T16:50:12.890123' (DJI UTCAtExposure, already UTC) -> '2026-09-29T16:50:12Z'."""
    t = datetime.strptime(s.strip()[:19], "%Y-%m-%dT%H:%M:%S")   # drop fractions: Python < 3.11 can't parse every length
    return t.replace(tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def frame_from_photo(path: str | Path, folder: str | Path, site_id: str, flight_id: str, nadir_only: bool = False,
                     camera: str = "m3e_wide") -> Frame | None:
    """Frame for one *_V.JPG, or None if tags are missing or the camera is too flat (pitch above -45, or with
    nadir_only more than 5 deg from straight down). frame_id = the photo's file stem (detector ids build on it)."""
    x = read_xmp(path)
    if any(k not in x for k in NEEDED): return None
    pitch = float(x.get("GimbalPitchDegree", -90))
    if pitch > -MIN_DEPRESSION_DEG or (nadir_only and abs(pitch + 90) > MAX_TILT_DEG): return None
    w, h = image_size(path)
    return Frame(frame_id=Path(path).stem, flight_id=flight_id, site_id=site_id, sensor=Sensor.RGB,
                 path=str(Path(path).relative_to(folder)), timestamp=utc_iso(x["UTCAtExposure"]),
                 lat=float(x["GpsLatitude"]), lon=float(x["GpsLongitude"]), alt_m=float(x["RelativeAltitude"]),
                 yaw_deg=nadir_yaw(float(x["GimbalYawDegree"]), float(x.get("GimbalRollDegree", 0))),
                 width_px=w, height_px=h, hfov_deg=HFOV_DEG[camera], pitch_deg=pitch)


def flight_photos(folder) -> list[Path]:
    """Wide-camera photos only (*_V.JPG, any case, subfolders too); skips .MRK / PPK files and other cameras."""
    return sorted(p for p in Path(folder).rglob("*") if p.is_file() and p.name.upper().endswith("_V.JPG"))


def ingest_flight(folder: str, site_id: str, flight_id: str, nadir_only: bool = False) -> list[Frame]:
    """Return one Frame per usable *_V.JPG in folder (searched recursively), sorted by timestamp."""
    return sorted((f for p in flight_photos(folder) if (f := frame_from_photo(p, folder, site_id, flight_id, nadir_only))),
                  key=lambda f: (f.timestamp, f.path))


def flight_id_for(frames_or_ts, n: int = 1) -> str:
    """F-YYYYMMDD-NN from the first photo's UTC date (n = that day's flight number)."""
    ts = frames_or_ts if isinstance(frames_or_ts, str) else frames_or_ts[0].timestamp
    return f"F-{ts[:10].replace('-', '')}-{n:02d}"


if __name__ == "__main__":
    import argparse, json
    from dataclasses import asdict
    ap = argparse.ArgumentParser(description="Read a DJI flight folder into Frames")
    ap.add_argument("folder"); ap.add_argument("--site", default="grayson"); ap.add_argument("--flight", default="F-local-01")
    a = ap.parse_args()
    fr = ingest_flight(a.folder, a.site, a.flight)
    print(json.dumps([asdict(f) for f in fr[:3]], indent=2, default=str))
    print(f"{len(fr)} usable frames of {len(flight_photos(a.folder))} *_V.JPG photos")
