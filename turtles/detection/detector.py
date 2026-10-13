"""Detector interface. Jake owns the implementation - the backend only ever calls these two functions."""
from __future__ import annotations

from turtles.contracts import Detection, Frame

MODEL_VERSION = "rgb-v0-untrained"


def detect(frame: Frame, image_path: str) -> list[Detection]:
    """Turtle detections in one aerial RGB frame.

    bbox in pixels of the original image (tile big photos internally, map boxes back).
    lat/lon = turtles.geo.pixel_to_latlon(frame, bbox center).
    Return [] when nothing is found - never None.
    """
    raise NotImplementedError


def detect_thermal(frame: Frame, image_path: str) -> list[Detection]:
    """Hot spots in one handheld FLIR radiometric image. No ML needed - see detection/README.md.

    lat/lon = frame.lat/frame.lon (the phone's GPS). Return [] when nothing is found.
    """
    raise NotImplementedError
