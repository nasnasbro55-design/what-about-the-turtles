"""Flight planner: where and when to survey. Naz owns this - spec in README.md next to this file.

plan(site_id, lat, lon, zones) -> list[FlightWindow], best first.

Try it on the mock zones (needs internet):  python3 -m turtles.planner.planner
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from turtles.contracts import FlightWindow, Zone

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"  # free, no key for non-commercial use
HOURLY = "temperature_2m,soil_temperature_0cm,shortwave_radiation,cloud_cover,precipitation,wind_speed_10m"
LOCAL = ZoneInfo("America/New_York")  # reasons are written in site-local time; everything else is UTC

# Can we fly? The M3E handles ~12 m/s wind; stay well under. Daylight only.
MAX_WIND_MS, MAX_PRECIP_MM = 8.0, 0.0

# How urgent is a zone, by hours until equipment arrives. Past the last step: 0.1. Work already started: 0.
URGENCY = ((24, 1.0), (72, 0.7), (168, 0.4))

# Thermal rule v1 - a HYPOTHESIS from our Oct 13 test (turtle visible when warmer than the ground:
# after basking, or as the ground cools late in the day; invisible when overcast). Check it on flight day.
MIN_SUN_WM2 = 300      # shortwave radiation in the prior 3 h that counts as "sunny enough to bask"
MAX_CLOUD_PCT = 50     # above this, assume turtles and ground are at the same temperature

# Turtle activity rules: empty on purpose. They must come from Tanya (rules email Q8-12), not from us guessing.
ACTIVITY: dict = {}

TOP_PER_ZONE = 3


def fetch_forecast(lat: float, lon: float, days: int = 7) -> dict:
    """Hourly forecast in UTC. Keys: hourly.time, hourly.<each HOURLY var>, daily.sunrise, daily.sunset."""
    q = urllib.parse.urlencode({"latitude": lat, "longitude": lon, "hourly": HOURLY, "daily": "sunrise,sunset",
                                "wind_speed_unit": "ms", "timezone": "GMT", "forecast_days": days})
    with urllib.request.urlopen(f"{FORECAST_URL}?{q}", timeout=20) as r:
        return json.load(r)


def hours_from(fc: dict) -> list[dict]:
    """Open-Meteo's columns -> one dict per hour, with that day's sunrise/sunset attached."""
    h, d = fc["hourly"], fc["daily"]
    sun = {r[:10]: (r, s) for r, s in zip(d["sunrise"], d["sunset"])}
    return [{**{k: h[k][i] for k in h}, "sunrise": sun[h["time"][i][:10]][0], "sunset": sun[h["time"][i][:10]][1]}
            for i in range(len(h["time"]))]


def utc(s: str) -> datetime:
    """'2026-10-22T14:00' or '2026-10-27T11:00:00Z' -> aware UTC datetime."""
    return datetime.fromisoformat(s.replace("Z", "")).replace(tzinfo=timezone.utc)


def urgency(hours_until_work: float) -> float:
    return 0.0 if hours_until_work < 0 else next((u for h, u in URGENCY if hours_until_work <= h), 0.1)


def flyable(hour: dict) -> bool:
    """Daylight, wind under MAX_WIND_MS, no precipitation. Missing data = don't fly."""
    w, p = hour["wind_speed_10m"], hour["precipitation"]
    return hour["sunrise"] <= hour["time"] <= hour["sunset"] and None not in (w, p) and w <= MAX_WIND_MS and p <= MAX_PRECIP_MM


def thermal_ok(hours: list[dict], i: int) -> bool:
    """Thermal rule v1 for hour i: sunny in the 3 h before, not overcast now, ground cooler than the air."""
    h, sun = hours[i], [x["shortwave_radiation"] or 0 for x in hours[max(0, i - 3):i]]
    return (bool(sun) and max(sun) >= MIN_SUN_WM2 and None not in (h["cloud_cover"], h["soil_temperature_0cm"], h["temperature_2m"])
            and h["cloud_cover"] <= MAX_CLOUD_PCT and h["soil_temperature_0cm"] < h["temperature_2m"])


def activity(hours: list[dict], i: int) -> tuple[float, str | None]:
    """Tanya's turtle-activity rules -> (multiplier, reason). 1.0 until she answers."""
    return 1.0, None


def _when(t: datetime) -> str:
    return t.astimezone(LOCAL).strftime("%a %b %-d, %-I:%M %p")


def plan(site_id: str, lat: float, lon: float, zones: list[Zone],
         forecast: dict | None = None, now: datetime | None = None) -> list[FlightWindow]:
    """Score every flyable hour for every zone, merge consecutive good hours into windows,
    write plain-English reasons, return the top windows sorted by priority."""
    hours = hours_from(forecast or fetch_forecast(lat, lon))
    now = (now or datetime.now(timezone.utc)).replace(minute=0, second=0, microsecond=0)
    out = []
    for z in zones:
        ws, runs = utc(z.work_starts), []
        for i, h in enumerate(hours):
            t = utc(h["time"])
            if t < now or t >= ws or not flyable(h):
                continue
            th, (act, act_why) = thermal_ok(hours, i), activity(hours, i)
            p = urgency((ws - t).total_seconds() / 3600) * (0.6 + 0.4 * th) * act
            if runs and runs[-1]["end"] == t and runs[-1]["thermal"] == th:  # extend the current window
                r = runs[-1]
                r.update(end=t + timedelta(hours=1), p=max(r["p"], p), wind=max(r["wind"], h["wind_speed_10m"]))
                r["why"] |= {act_why} - {None}
            else:
                runs.append({"start": t, "end": t + timedelta(hours=1), "p": p, "thermal": th,
                             "wind": h["wind_speed_10m"], "sunset": utc(h["sunset"]), "why": {act_why} - {None}})
        for r in sorted(runs, key=lambda r: -r["p"])[:TOP_PER_ZONE]:
            days = (ws - r["start"]).total_seconds() / 86400
            out.append(FlightWindow(
                window_id=f"W-{z.zone_id}-{r['start']:%Y%m%d%H}", site_id=site_id, zone_id=z.zone_id,
                start=f"{r['start']:%Y-%m-%dT%H:%M:%SZ}", end=f"{min(r['end'], r['sunset']):%Y-%m-%dT%H:%M:%SZ}",
                priority=round(r["p"], 2), thermal_ok=r["thermal"],
                reasons=[f"{z.work.capitalize()} starts {_when(ws)} "
                         + ("(less than a day away)" if days < 1 else f"(in {days:.0f} day{'s' * (round(days) != 1)})"),
                         "Sunny earlier and the ground is cooling below air temperature: good thermal window"
                         if r["thermal"] else "Turtles unlikely to stand out on thermal (cloudy, no recent sun, or ground still warm): RGB only",
                         f"Dry, wind up to {r['wind']:.0f} m/s", *sorted(r["why"])]))
    return sorted(out, key=lambda w: (-w.priority, w.start))


if __name__ == "__main__":
    from pathlib import Path
    from turtles.contracts import load
    zones = load(Zone, Path(__file__).resolve().parents[1] / "architecture" / "mock" / "zones.json")
    for w in plan("grayson-mock", 38.76, -77.52, zones)[:8]:
        s, e = utc(w.start[:-1]).astimezone(LOCAL), utc(w.end[:-1]).astimezone(LOCAL)
        print(f"{w.priority:.2f}  {w.zone_id}  {s:%a %-I:%M %p}-{e:%-I:%M %p}  thermal={w.thermal_ok}")
        print("      " + "\n      ".join(w.reasons))
