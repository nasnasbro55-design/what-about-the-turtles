"""Flight planner: where and when to survey. Naz owns this - spec in README.md next to this file.

plan(site_id, lat, lon, zones) -> list[FlightWindow], best first.
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request

from turtles.contracts import FlightWindow, Zone

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"  # free, no key for non-commercial use
HOURLY = "temperature_2m,soil_temperature_0cm,shortwave_radiation,cloud_cover,precipitation,wind_speed_10m"

# Can we fly? Mini 4 Pro / Mavic 3T handle ~10-12 m/s wind; stay well under. Daylight only.
MAX_WIND_MS, MAX_PRECIP_MM = 8.0, 0.0

# How urgent is a zone, by hours until equipment arrives. Past the last step: 0.1. Work already started: 0.
URGENCY = ((24, 1.0), (72, 0.7), (168, 0.4))

# Thermal rule v1 - a HYPOTHESIS from our Oct 13 test (turtle visible when warmer than the ground:
# after basking, or as the ground cools late in the day; invisible when overcast). Check it on flight day.
MIN_SUN_WM2 = 300      # shortwave radiation in the prior 3 h that counts as "sunny enough to bask"
MAX_CLOUD_PCT = 50     # above this, assume turtles and ground are at the same temperature

# Turtle activity rules: empty on purpose. They must come from Tanya, not from us guessing.
ACTIVITY: dict = {}


def fetch_forecast(lat: float, lon: float, days: int = 3) -> dict:
    """Hourly forecast in UTC. Keys: hourly.time, hourly.<each HOURLY var>, daily.sunrise, daily.sunset."""
    q = urllib.parse.urlencode({"latitude": lat, "longitude": lon, "hourly": HOURLY, "daily": "sunrise,sunset",
                                "wind_speed_unit": "ms", "timezone": "GMT", "forecast_days": days})
    with urllib.request.urlopen(f"{FORECAST_URL}?{q}", timeout=20) as r:
        return json.load(r)


def urgency(hours_until_work: float) -> float:
    return 0.0 if hours_until_work < 0 else next((u for h, u in URGENCY if hours_until_work <= h), 0.1)


def flyable(hour: dict) -> bool:
    """Daylight, wind under MAX_WIND_MS, no precipitation."""
    raise NotImplementedError


def thermal_ok(hours: list[dict], i: int) -> bool:
    """Thermal rule v1 for hour i, using the hours before it (see constants above)."""
    raise NotImplementedError


def plan(site_id: str, lat: float, lon: float, zones: list[Zone]) -> list[FlightWindow]:
    """Score every flyable hour for every zone, merge consecutive good hours into windows,
    write plain-English reasons, return the top windows sorted by priority."""
    raise NotImplementedError
