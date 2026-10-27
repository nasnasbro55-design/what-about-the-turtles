"""F3 survey report: one survey -> a row for Tanya's records, one A.E.R.O. encounter record per turtle,
and a one-page HTML summary for Tanya and W.A. Hazel.

Encounter columns follow Olivia LoBalbo's Turtle Health Assessment form (Section 1 + disposition), plus the
time of day and temperature Tanya asked for. Photo checklist columns are left blank for the responder.

Run (Oct 24 Grayson visit, weather from the exported log):
    python3 -m turtles.report.survey_report --date 2026-10-24 --start 09:50 --end 12:35 \
        --weather "<logs>/weather_hourly.csv" --conditions "<logs>/conditions.json" \
        --observer "Nasrullah Hussain" --pilot "Logan Lavalette" --flight F-20261024-01
Add --alerts <alerts.json> for responder outcomes, or --fetch-weather instead of --weather.
Outputs go to turtles/report/out/ (gitignored): they describe a private site, so share via OneDrive, not git.
"""
from __future__ import annotations

import argparse, csv, html, io, json, math, urllib.parse, urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from turtles.contracts import Alert, Status, load
from turtles.rules import activity_note

LOCAL = ZoneInfo("America/New_York")
OUT = Path(__file__).parent / "out"
SITE_GEOJSON = Path(__file__).parents[1] / "planner" / "sites" / "grayson.geojson"

SURVEY_COLS = ["date", "site", "county_state", "start_time", "end_time", "time_of_day", "observer", "pilot",
               "flight_ids", "air_temp_f", "air_temp_c", "ground_temp_f", "weather", "cloud_pct", "wind",
               "ground", "rain_survey_in", "rain_prev_48h_in", "area_acres", "activity_note",
               "turtles_flagged", "turtles_confirmed", "turtles_relocated", "false_positives", "notes"]
ENCOUNTER_COLS = ["record_id", "date", "time", "encounter_type", "site", "county_state", "gps_lat", "gps_lon",
                  "coordinate_datum_precision", "observer_finder", "air_temp_c", "air_temp_f", "weather",
                  "substrate_habitat", "encounter_circumstances", "found_at", "species", "disposition",
                  "disposition_location", "disposition_time", "photo_dorsal", "photo_plastron", "photo_left",
                  "photo_right", "photo_head", "id_card_visible", "scale_visible", "notes"]


def f2c(f): return None if f is None else round((f - 32) * 5 / 9, 1)


def time_of_day(hhmm: str) -> str:
    h = int(hhmm[:2]); return "morning" if h < 12 else "midday" if h < 14 else "afternoon" if h < 18 else "evening"


def read_weather_csv(text: str) -> tuple[list[dict], dict]:
    """The exported weather_hourly.csv: hourly rows (°F, inches), then a blank line and daily rain."""
    hourly, daily, part = [], {}, 0
    for row in csv.reader(io.StringIO(text)):
        if not row: part = 1; continue
        if part == 0 and row[0] != "time": hourly.append(row)
        elif part == 0: keys = row
        elif row[0] != "date": daily[row[0]] = float(row[1] or 0)
    return [dict(zip(keys, r)) for r in hourly], daily


def fetch_weather(lat: float, lon: float, day: str) -> tuple[list[dict], dict]:
    """Same shape as read_weather_csv, from Open-Meteo (archive endpoint for older dates)."""
    d0 = date.fromisoformat(day)
    old = (date.today() - d0).days > 80
    q = urllib.parse.urlencode({"latitude": lat, "longitude": lon, "timezone": "America/New_York",
        "start_date": str(d0 - timedelta(days=2)), "end_date": day, "temperature_unit": "fahrenheit",
        "wind_speed_unit": "mph", "precipitation_unit": "inch", "daily": "precipitation_sum",
        "hourly": "temperature_2m,soil_temperature_0cm,cloud_cover,precipitation,wind_speed_10m"})
    url = ("https://archive-api.open-meteo.com/v1/archive?" if old else "https://api.open-meteo.com/v1/forecast?") + q
    d = json.load(urllib.request.urlopen(url, timeout=30))
    h = d["hourly"]
    hourly = [{k: str(h[k][i]) for k in h} for i in range(len(h["time"])) if h["time"][i].startswith(day)]
    return hourly, dict(zip(d["daily"]["time"], d["daily"]["precipitation_sum"]))


def summarize_weather(hourly: list[dict], daily: dict, day: str, start: str, end: str) -> dict:
    """Averages over the survey hours, plus rain in the 2 days before."""
    hs = [h for h in hourly if h["time"][:10] == day and start[:2] <= h["time"][11:13] <= end[:2]] or hourly
    num = lambda k: [float(h[k]) for h in hs if h.get(k) not in (None, "", "None")]
    avg = lambda k: round(sum(v) / len(v), 1) if (v := num(k)) else None
    prev = [str(date.fromisoformat(day) - timedelta(days=i)) for i in (1, 2)]
    return {"air_temp_f": avg("temperature_2m"), "ground_temp_f": avg("soil_temperature_0cm"),
            "cloud_pct": avg("cloud_cover"), "wind_mph": avg("wind_speed_10m"),
            "rain_survey_in": round(sum(num("precipitation")), 2),
            "rain_prev_48h_in": round(sum(daily.get(d, 0) or 0 for d in prev), 2)}


def site_acres(path: Path = SITE_GEOJSON) -> float | None:
    if not path.exists(): return None
    ring = json.loads(path.read_text())["features"][0]["geometry"]["coordinates"][0]
    k = 111320; kl = k * math.cos(math.radians(ring[0][1]))
    a = sum(x1 * kl * y2 * k - x2 * kl * y1 * k for (x1, y1), (x2, y2) in zip(ring, ring[1:]))
    return round(abs(a) / 2 / 4046.86, 1)


def species_from(note: str) -> str:
    n = note.lower()
    return "Common snapping turtle" if "snap" in n else "Eastern box turtle" if "box" in n else ""


def encounter_rows(alerts: list[Alert], a: argparse.Namespace, wx: dict) -> list[dict]:
    rows = []
    for i, al in enumerate(x for x in alerts if x.status in (Status.CONFIRMED, Status.RELOCATED)):
        t = datetime.fromisoformat(al.created_at.replace("Z", "+00:00")).astimezone(LOCAL)
        moved = al.status == Status.RELOCATED
        rows.append({"record_id": f"{a.date}-{a.site_id}-{i + 1:02d}", "date": a.date, "time": t.strftime("%H:%M"),
            "encounter_type": "Field capture", "site": a.site_name, "county_state": a.county,
            "gps_lat": round(al.lat, 6), "gps_lon": round(al.lon, 6),
            "coordinate_datum_precision": "WGS84; drone GPS + camera geometry, about 3-5 m",
            "observer_finder": f"Drone survey ({a.pilot}); confirmed by responder", "air_temp_c": f2c(wx["air_temp_f"]),
            "air_temp_f": wx["air_temp_f"], "weather": a.wdesc, "substrate_habitat": "",
            "encounter_circumstances": f"Flagged by drone survey {al.flight_id} (score {al.score:.2f}); "
                                       f"{'relocated' if moved else 'confirmed'} by responder",
            "found_at": "Active construction site", "species": species_from(al.note),
            "disposition": "Released off site (relocated)" if moved else "Confirmed on site, not yet moved",
            "disposition_location": al.note if moved else "", "disposition_time": t.strftime("%H:%M") if moved else "",
            **{c: "" for c in ENCOUNTER_COLS[20:27]}, "notes": al.note})
    return rows


def survey_row(alerts: list[Alert], a: argparse.Namespace, wx: dict, acres) -> dict:
    n = lambda s: sum(x.status == s for x in alerts)
    month = int(a.date[5:7])
    return {"date": a.date, "site": a.site_name, "county_state": a.county, "start_time": a.start, "end_time": a.end,
            "time_of_day": time_of_day(a.start), "observer": a.observer, "pilot": a.pilot, "flight_ids": a.flight,
            "air_temp_f": wx["air_temp_f"], "air_temp_c": f2c(wx["air_temp_f"]), "ground_temp_f": wx["ground_temp_f"],
            "weather": a.wdesc, "cloud_pct": wx["cloud_pct"], "wind": a.wind or (f"{wx['wind_mph']} mph" if wx["wind_mph"] else ""),
            "ground": a.ground, "rain_survey_in": wx["rain_survey_in"], "rain_prev_48h_in": wx["rain_prev_48h_in"],
            "area_acres": acres, "activity_note": activity_note(month, wx["air_temp_f"], wx["rain_survey_in"]),
            "turtles_flagged": len(alerts), "turtles_confirmed": n(Status.CONFIRMED) + n(Status.RELOCATED),
            "turtles_relocated": n(Status.RELOCATED), "false_positives": n(Status.FALSE_POSITIVE), "notes": a.notes}


def write_csv(path: Path, cols: list[str], rows: list[dict]) -> None:
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, cols); w.writeheader(); w.writerows(rows)


def render_html(s: dict, enc: list[dict]) -> str:
    e = lambda v: html.escape("" if v is None else str(v))
    stat = lambda n, label: f'<div class="stat"><b>{e(n)}</b><span>{label}</span></div>'
    rows = "".join(f"<tr><td>{e(r['time'])}</td><td>{e(r['species'] or 'Turtle')}</td><td>{e(r['gps_lat'])}, {e(r['gps_lon'])}</td>"
                   f"<td>{e(r['disposition'])}</td><td>{e(r['disposition_location'])}</td></tr>" for r in enc)
    table = (f"<table><tr><th>Time</th><th>Species</th><th>Location</th><th>Outcome</th><th>Moved to</th></tr>{rows}</table>"
             if enc else "<p class='none'>No turtles found on this survey.</p>")
    cond = [("Survey", f"{s['start_time']}–{s['end_time']} ({s['time_of_day']})"), ("Observer", s["observer"]),
            ("Pilot", s["pilot"]), ("Air temperature", f"{s['air_temp_f']}°F ({s['air_temp_c']}°C)"),
            ("Ground temperature", f"{s['ground_temp_f']}°F"), ("Weather", f"{s['weather']}, {s['cloud_pct']}% cloud"),
            ("Wind", s["wind"]), ("Ground", s["ground"]),
            ("Rain", f"{s['rain_survey_in']} in during survey, {s['rain_prev_48h_in']} in in the 2 days before"),
            ("Area covered", f"{s['area_acres']} acres" if s["area_acres"] else "")]
    dl = "".join(f"<dt>{k}</dt><dd>{e(v)}</dd>" for k, v in cond if v not in (None, ""))
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>Turtle survey {e(s['date'])}</title>
<style>body{{font:15px/1.5 -apple-system,Helvetica,Arial,sans-serif;color:#1d2a17;max-width:820px;margin:32px auto;padding:0 16px}}
h1{{margin:0;font-size:26px}}.sub{{color:#5b6b52;margin:2px 0 20px}}.stats{{display:flex;gap:12px;flex-wrap:wrap;margin:16px 0}}
.stat{{flex:1;min-width:120px;background:#eef3e8;border-radius:10px;padding:12px}}.stat b{{display:block;font-size:28px}}
.stat span{{color:#5b6b52;font-size:13px}}.note{{background:#4f5f2b;color:#fff;border-radius:10px;padding:12px 14px}}
dl{{display:grid;grid-template-columns:180px 1fr;gap:4px 12px}}dt{{color:#5b6b52}}dd{{margin:0}}
table{{width:100%;border-collapse:collapse;margin-top:8px}}th,td{{text-align:left;padding:6px 8px;border-bottom:1px solid #dde5d5;font-size:14px}}
.none{{color:#5b6b52}}footer{{margin-top:28px;font-size:12px;color:#7a8770}}@media print{{body{{margin:0}}}}</style></head><body>
<h1>Turtle survey report</h1><p class="sub">{e(s['site'])} · {e(s['county_state'])} · {e(s['date'])}</p>
<div class="stats">{stat(s['turtles_flagged'], 'flagged by the drone')}{stat(s['turtles_confirmed'], 'confirmed turtles')}
{stat(s['turtles_relocated'], 'moved to safety')}{stat(s['false_positives'], 'false alarms')}</div>
<p class="note">{e(s['activity_note'])}</p><h2>Conditions</h2><dl>{dl}</dl><h2>Turtles</h2>{table}
{f"<h2>Notes</h2><p>{e(s['notes'])}</p>" if s['notes'] else ""}
<footer>Generated by What About the Turtles (TNUX, George Mason University). Encounter records follow the A.E.R.O. Turtle
Health Assessment, Section 1. Weather: Open-Meteo.</footer></body></html>"""


def main(argv=None):
    ap = argparse.ArgumentParser(description="F3: survey report for Tanya's records")
    ap.add_argument("--date", required=True); ap.add_argument("--start", required=True); ap.add_argument("--end", required=True)
    ap.add_argument("--site-id", default="grayson"); ap.add_argument("--site-name", default="Grayson Overlook")
    ap.add_argument("--county", default="Prince William County, VA")
    ap.add_argument("--lat", type=float, default=38.7942); ap.add_argument("--lon", type=float, default=-77.6481)
    ap.add_argument("--observer", default=""); ap.add_argument("--pilot", default=""); ap.add_argument("--flight", default="")
    ap.add_argument("--alerts", help="Alert JSON with responder outcomes (omit for a survey with no flags)")
    ap.add_argument("--weather", help="exported weather_hourly.csv"); ap.add_argument("--fetch-weather", action="store_true")
    ap.add_argument("--conditions", help="field conditions.json (weather, wind, ground)")
    ap.add_argument("--site", type=Path, default=SITE_GEOJSON, help="site outline GeoJSON, for area")
    ap.add_argument("--notes", default=""); ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args(argv)
    c = json.loads(Path(a.conditions).read_text()) if a.conditions else {}
    a.wdesc, a.wind, a.ground = c.get("weather", ""), c.get("wind", ""), c.get("ground", "")
    hourly, daily = (fetch_weather(a.lat, a.lon, a.date) if a.fetch_weather
                     else read_weather_csv(Path(a.weather).read_text()) if a.weather else ([], {}))
    wx = summarize_weather(hourly, daily, a.date, a.start, a.end) if hourly else dict.fromkeys(
        ["air_temp_f", "ground_temp_f", "cloud_pct", "wind_mph", "rain_survey_in", "rain_prev_48h_in"])
    if wx["air_temp_f"] is None and "temp_f" in c: wx["air_temp_f"] = c["temp_f"]
    alerts = load(Alert, a.alerts) if a.alerts else []
    s, enc = survey_row(alerts, a, wx, site_acres(a.site)), encounter_rows(alerts, a, wx)
    a.out.mkdir(parents=True, exist_ok=True)
    stem = f"{a.date}_{a.site_id}"
    write_csv(a.out / f"survey_{stem}.csv", SURVEY_COLS, [s])
    write_csv(a.out / f"encounters_{stem}.csv", ENCOUNTER_COLS, enc)
    (a.out / f"report_{stem}.html").write_text(render_html(s, enc))
    print(f"{s['activity_note']}\n{s['turtles_flagged']} flagged, {s['turtles_confirmed']} confirmed, "
          f"{s['turtles_relocated']} relocated. Files in {a.out}")
    return s, enc


if __name__ == "__main__":
    main()
