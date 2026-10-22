"""Planner tests on a fake forecast - no internet needed.  Run from the repo root:  python3 -m pytest -q"""
from dataclasses import asdict
from datetime import datetime, timezone

from turtles.contracts import FlightWindow, Zone, from_dict
from turtles.planner.planner import flyable, hours_from, plan, thermal_ok

NOW = datetime(2026, 10, 25, 0, tzinfo=timezone.utc)  # Sat Oct 24, 8 PM Eastern


def fake_forecast(days=2, **override):
    """Clear, calm, sunny days. Sunrise 11:30Z, sunset 22:20Z (~7:30 AM / 6:20 PM Eastern).
    Ground warmer than air until 19:00Z, then cooling below it (a thermal window late afternoon).
    override: {"precipitation": {"2026-10-25T15:00": 1.2}, ...} sets single hours."""
    times = [f"2026-10-{25 + d}T{h:02d}:00" for d in range(days) for h in range(24)]
    day = lambda t: 11 <= int(t[11:13]) <= 22
    cols = {"time": times,
            "temperature_2m": [20.0] * len(times),
            "soil_temperature_0cm": [22.0 if int(t[11:13]) < 19 else 18.0 for t in times],
            "shortwave_radiation": [500.0 if day(t) else 0.0 for t in times],
            "cloud_cover": [20.0] * len(times),
            "precipitation": [0.0] * len(times),
            "wind_speed_10m": [3.0] * len(times)}
    for var, hours in override.items():
        for t, v in hours.items():
            cols[var][times.index(t)] = v
    return {"hourly": cols, "daily": {"sunrise": [f"2026-10-{25 + d}T11:30" for d in range(days)],
                                      "sunset": [f"2026-10-{25 + d}T22:20" for d in range(days)]}}


def zone(zid="Z1", starts="2026-10-26T11:00:00Z", work="clearing"):
    return Zone(zid, "test", "Test lot", [[38.76, -77.52]], work, starts)


def hour(**kw):
    return {"time": "2026-10-25T15:00", "sunrise": "2026-10-25T11:30", "sunset": "2026-10-25T22:20",
            "wind_speed_10m": 3.0, "precipitation": 0.0, **kw}


def test_flyable():
    assert flyable(hour())
    assert flyable(hour(wind_speed_10m=0.0))           # calm air is fine
    assert not flyable(hour(time="2026-10-25T03:00"))  # night
    assert not flyable(hour(wind_speed_10m=9.5))       # too windy
    assert not flyable(hour(precipitation=0.4))        # raining
    assert not flyable(hour(wind_speed_10m=None))      # missing data = don't fly


def test_thermal_ok():
    hrs = hours_from(fake_forecast())
    i = lambda t: next(n for n, h in enumerate(hrs) if h["time"] == t)
    assert thermal_ok(hrs, i("2026-10-25T20:00"))       # sunny before, ground cooler than air
    assert not thermal_ok(hrs, i("2026-10-25T15:00"))   # ground still warmer than air
    assert not thermal_ok(hrs, 0)                        # no hours before it
    cloudy = hours_from(fake_forecast(cloud_cover={"2026-10-25T20:00": 90.0}))
    assert not thermal_ok(cloudy, i("2026-10-25T20:00"))


def test_plan_windows_are_valid_and_sorted():
    ws = plan("test", 38.76, -77.52, [zone()], forecast=fake_forecast(), now=NOW)
    assert ws, "a sunny day before clearing should give at least one window"
    for w in ws:
        from_dict(FlightWindow, asdict(w))  # matches the contract
        assert w.start < w.end <= "2026-10-26T11:00:00Z"
        assert len(w.reasons) >= 3
    assert [w.priority for w in ws] == sorted((w.priority for w in ws), reverse=True)
    best = ws[0]
    assert best.thermal_ok and best.priority == 1.0  # under 24 h to clearing + thermal window
    assert best.start == "2026-10-25T19:00:00Z" and best.end == "2026-10-25T22:20:00Z"  # merged, capped at sunset


def test_plan_skips_rain_night_and_past_hours():
    rain = {f"2026-10-25T{h:02d}:00": 2.0 for h in range(24)}
    ws = plan("test", 38.76, -77.52, [zone(starts="2026-10-26T00:00:00Z")],
              forecast=fake_forecast(precipitation=rain), now=NOW)
    assert ws == []
    later = datetime(2026, 10, 25, 20, tzinfo=timezone.utc)
    assert all(w.start >= "2026-10-25T20:00:00Z"
               for w in plan("test", 38.76, -77.52, [zone()], forecast=fake_forecast(), now=later))


def test_sooner_work_ranks_first():
    ws = plan("test", 38.76, -77.52, [zone("SOON"), zone("LATER", starts="2026-10-31T11:00:00Z")],
              forecast=fake_forecast(), now=NOW)
    assert ws[0].zone_id == "SOON"
    assert max(w.priority for w in ws if w.zone_id == "LATER") < ws[0].priority
