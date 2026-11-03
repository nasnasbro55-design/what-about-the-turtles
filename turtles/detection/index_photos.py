"""Index every drone photo in the OneDrive flights folder -> frames.csv (one row per *_V.JPG).

    python3 -m turtles.detection.index_photos "<TNUX Turtles Data>" <work_dir>

Columns: folder, spot (0 = survey), split (survey | train | test), path, alt_ft, pitch, yaw (nadir-corrected),
lat, lon, utc. TEST folders are the held-out spots and are never used to train model M.
"""
from __future__ import annotations

import csv, re, sys
from pathlib import Path

from turtles.backend.ingest import read_xmp
from turtles.geo import nadir_yaw


def main(data: str, work: str) -> None:
    rows = []
    for p in sorted(Path(data, "flights", "drone_photos").rglob("*_V.JPG")):
        x, folder = read_xmp(p), p.parent.name
        spot = int(m.group(1)) if (m := re.search(r"_spot(\d)_", folder)) else 0
        rows.append(dict(folder=folder, spot=spot, split="survey" if not spot else "test" if "_TEST_" in folder else "train",
                         path=str(p), alt_ft=round(float(x["RelativeAltitude"]) * 3.281), pitch=float(x["GimbalPitchDegree"]),
                         yaw=nadir_yaw(float(x["GimbalYawDegree"]), float(x["GimbalRollDegree"])),
                         lat=float(x["GpsLatitude"]), lon=float(x["GpsLongitude"]), utc=x["UTCAtExposure"]))
    Path(work).mkdir(parents=True, exist_ok=True)
    with open(Path(work, "frames.csv"), "w", newline="") as f:
        csv.DictWriter(f, rows[0].keys()).writeheader(); csv.DictWriter(f, rows[0].keys()).writerows(rows)
    print(f"{len(rows)} photos -> {work}/frames.csv")


if __name__ == "__main__":
    main(*sys.argv[1:3])
