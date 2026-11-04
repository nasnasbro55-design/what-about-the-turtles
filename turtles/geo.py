"""Pixel -> ground coordinates and distances.

Flat-earth approximations: accurate to well under a meter at site scale (< 2 km).
pixel_to_latlon handles straight-down and tilted cameras (frame.pitch_deg, flat ground). Tilted photos are less
accurate the closer a pixel is to the horizon, so ingest only keeps pitch -45 or steeper (MIN_DEPRESSION_DEG).
For handheld thermal frames, don't use it - use the frame's own phone GPS lat/lon.
"""
from __future__ import annotations

import math

M_PER_DEG_LAT = 111_320.0

# Horizontal field of view by capture mode. DJI publishes 82.1 deg *diagonal* for the
# Mini 4 Pro; horizontal is derived from the aspect ratio. Estimates - calibrate on the
# first flight by photographing an object of known size from a known height.
HFOV_DEG = {
    "m3e_wide": 70.65,             # DJI Mavic 3 Enterprise wide camera, from CalibratedFocalLength in real photos
    "mini4pro_photo_4x3": 69.7,
    "mini4pro_video_16x9": 74.4,
    "flir_one_edge_pro": 54.0,
}


def nadir_yaw(gimbal_yaw: float, gimbal_roll: float) -> float:
    """Heading the top of a straight-down photo faces, in -180..180.

    Pointing straight down, DJI sometimes reports the same orientation two ways: Logan's Sept 29
    photos alternate yaw -155.9 / roll 0 and yaw +24.1 / roll 180, which are the same picture.
    Always pass yaw through this before pixel_to_latlon, or half the detections land mirrored.
    """
    return ((gimbal_yaw + 180 if abs(gimbal_roll) > 90 else gimbal_yaw) + 180) % 360 - 180


def gsd_m(alt_m: float, hfov_deg: float, width_px: int) -> float:
    """Ground sample distance: meters of ground per pixel, camera pointed straight down."""
    return 2 * alt_m * math.tan(math.radians(hfov_deg) / 2) / width_px


def ground_offset_m(alt_m: float, hfov_deg: float, width_px: int, height_px: int, yaw_deg: float, pitch_deg: float,
                    px: float, py: float) -> tuple[float, float]:
    """(east, north) meters from the drone to the ground under pixel (px, py), flat ground at alt_m below the camera.

    Pinhole camera: a ray through the pixel, tilted pitch_deg below horizontal (-90 = straight down) and turned to
    yaw_deg, meets the ground. The top of the image faces yaw_deg (for pitch -90 the same as the old formula)."""
    f = width_px / 2 / math.tan(math.radians(hfov_deg) / 2)            # focal length in pixels
    x, y, t, yaw = px - width_px / 2, py - height_px / 2, math.radians(-pitch_deg), math.radians(yaw_deg)
    fwd = (math.sin(yaw) * math.cos(t), math.cos(yaw) * math.cos(t), -math.sin(t))   # boresight (east, north, up)
    up = (math.sin(yaw) * math.sin(t), math.cos(yaw) * math.sin(t), math.cos(t))     # top of the image
    right = (math.cos(yaw), -math.sin(yaw), 0.0)
    d = [f * fw + x * r - y * u for fw, r, u in zip(fwd, right, up)]
    d[2] = min(d[2], -math.hypot(d[0], d[1]) * math.tan(math.radians(MIN_RAY_DEG)))   # never at or above the horizon
    s = alt_m / -d[2]
    return s * d[0], s * d[1]


MIN_DEPRESSION_DEG = 45   # ingest keeps photos tilted at most this far from straight down (pitch -45 .. -90)
MIN_RAY_DEG = 3           # rays flatter than this below the horizon are clamped (only beyond the top edge of -45 photos)


def pixel_to_latlon(frame, px: float, py: float) -> tuple[float, float]:
    """Lat/lon of the ground under pixel (px, py). Straight-down or tilted (frame.pitch_deg, default -90)."""
    east, north = ground_offset_m(frame.alt_m, frame.hfov_deg, frame.width_px, frame.height_px, frame.yaw_deg,
                                  getattr(frame, "pitch_deg", -90.0), px, py)
    return (frame.lat + north / M_PER_DEG_LAT,
            frame.lon + east / (M_PER_DEG_LAT * math.cos(math.radians(frame.lat))))


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    north = (lat2 - lat1) * M_PER_DEG_LAT
    east = (lon2 - lon1) * M_PER_DEG_LAT * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot(north, east)
