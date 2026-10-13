"""Pixel -> ground coordinates and distances.

Flat-earth approximations: accurate to well under a meter at site scale (< 2 km).
pixel_to_latlon assumes the camera points straight down (gimbal -90 deg). For handheld
thermal frames, don't use it - use the frame's own phone GPS lat/lon.
"""
from __future__ import annotations

import math

M_PER_DEG_LAT = 111_320.0

# Horizontal field of view by capture mode. DJI publishes 82.1 deg *diagonal* for the
# Mini 4 Pro; horizontal is derived from the aspect ratio. Estimates - calibrate on the
# first flight by photographing an object of known size from a known height.
HFOV_DEG = {
    "mini4pro_photo_4x3": 69.7,
    "mini4pro_video_16x9": 74.4,
    "flir_one_edge_pro": 54.0,
}


def gsd_m(alt_m: float, hfov_deg: float, width_px: int) -> float:
    """Ground sample distance: meters of ground per pixel, camera pointed straight down."""
    return 2 * alt_m * math.tan(math.radians(hfov_deg) / 2) / width_px


def pixel_to_latlon(frame, px: float, py: float) -> tuple[float, float]:
    """Lat/lon of the ground under pixel (px, py). The top of the image faces frame.yaw_deg."""
    g, yaw = gsd_m(frame.alt_m, frame.hfov_deg, frame.width_px), math.radians(frame.yaw_deg)
    right, fwd = (px - frame.width_px / 2) * g, (frame.height_px / 2 - py) * g
    east, north = right * math.cos(yaw) + fwd * math.sin(yaw), fwd * math.cos(yaw) - right * math.sin(yaw)
    return (frame.lat + north / M_PER_DEG_LAT,
            frame.lon + east / (M_PER_DEG_LAT * math.cos(math.radians(frame.lat))))


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    north = (lat2 - lat1) * M_PER_DEG_LAT
    east = (lon2 - lon1) * M_PER_DEG_LAT * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot(north, east)
