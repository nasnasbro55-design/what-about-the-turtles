"""Ingest: a folder of drone photos -> list[Frame]. Ethan owns this.

DJI writes everything needed into each photo's EXIF/XMP:
    GPSLatitude / GPSLongitude      -> lat, lon
    XMP drone-dji:RelativeAltitude  -> alt_m (height above takeoff point)
    XMP drone-dji:GimbalYawDegree   -> yaw_deg
    XMP drone-dji:GimbalPitchDegree -> should be about -90 (straight down); skip frames that aren't
    DateTimeOriginal                -> timestamp (DJI writes local time with no timezone - convert to UTC)

Easiest reader: exiftool (brew install exiftool) via the pyexiftool package.
Verify these tag names against the first real Mini 4 Pro photo before trusting them.
"""
from __future__ import annotations

from turtles.contracts import Frame


def ingest_flight(folder: str, site_id: str, flight_id: str) -> list[Frame]:
    """Return one Frame per usable image in folder, sorted by timestamp."""
    raise NotImplementedError
