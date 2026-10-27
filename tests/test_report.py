"""F3 survey report tests - no internet needed.  python3 -m pytest -q"""
import csv
from pathlib import Path

from turtles.report.survey_report import (ENCOUNTER_COLS, SURVEY_COLS, main, read_weather_csv, summarize_weather,
                                          time_of_day)
from turtles.rules import activity_note

MOCK = Path(__file__).parents[1] / "turtles" / "architecture" / "mock" / "alerts.json"
WX = """time,temperature_2m,soil_temperature_0cm,cloud_cover,shortwave_radiation,precipitation,wind_speed_10m,wind_gusts_10m
2026-10-24T09:00,41.5,45.5,100,153.0,0.0,1.2,3.1
2026-10-24T10:00,48.5,54.9,12,303.0,0.0,2.9,5.4
2026-10-24T11:00,53.5,60.7,3,493.0,0.0,2.7,6.5
2026-10-24T12:00,57.4,63.1,0,607.0,0.0,0.7,6.3

date,rain_inches
2026-10-22,0.0
2026-10-23,0.1
2026-10-24,0.0
"""


def test_weather_summary_uses_survey_hours_and_prior_rain():
    wx = summarize_weather(*read_weather_csv(WX), "2026-10-24", "10:00", "12:35")
    assert wx["air_temp_f"] == 53.1 and wx["rain_prev_48h_in"] == 0.1 and wx["rain_survey_in"] == 0


def test_activity_follows_tanyas_rules():
    assert "dormant" in activity_note(11, 70)
    assert "below" in activity_note(10, 53)
    assert "inside" in activity_note(6, 75)
    assert "rain" in activity_note(7, 70, rain_in=0.3)


def test_time_of_day():
    assert [time_of_day(t) for t in ("09:50", "12:10", "15:00")] == ["morning", "midday", "afternoon"]


def test_report_files(tmp_path):
    wx = tmp_path / "w.csv"; wx.write_text(WX)
    s, enc = main(["--date", "2026-10-24", "--start", "09:50", "--end", "12:35", "--weather", str(wx),
                   "--alerts", str(MOCK), "--observer", "Naz", "--pilot", "Logan", "--out", str(tmp_path)])
    assert s["turtles_relocated"] <= s["turtles_confirmed"] <= s["turtles_flagged"]
    assert len(enc) == s["turtles_confirmed"] and all(r["coordinate_datum_precision"] for r in enc)
    rows = list(csv.DictReader(open(tmp_path / "encounters_2026-10-24_grayson.csv")))
    assert list(rows[0]) == ENCOUNTER_COLS if rows else True
    assert list(next(csv.DictReader(open(tmp_path / "survey_2026-10-24_grayson.csv")))) == SURVEY_COLS
    assert "Turtle survey report" in (tmp_path / "report_2026-10-24_grayson.html").read_text()


def test_no_turtles_survey(tmp_path):
    s, enc = main(["--date", "2026-10-24", "--start", "09:50", "--end", "12:35", "--out", str(tmp_path)])
    assert enc == [] and s["turtles_flagged"] == 0
    assert "No turtles found" in (tmp_path / "report_2026-10-24_grayson.html").read_text()
