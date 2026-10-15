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

from turtles.contracts import Frame


def ingest_flight(folder: str, site_id: str, flight_id: str) -> list[Frame]:
    """Return one Frame per usable *_V.JPG in folder, sorted by timestamp."""
    raise NotImplementedError
