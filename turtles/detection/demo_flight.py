"""Make a flyable demo folder from a Test B spot: the painted (living-turtle simulation) photos with the original
drone metadata (GPS, altitude, gimbal, time - the DJI XMP/EXIF the pipeline needs) spliced back in.

    python3 -m turtles.detection.demo_flight <work> "<TNUX Turtles Data>" 07_spot4_half_buried_TEST_DJI538 <out folder>

Simulation, not a live turtle: say so on stage.
"""
from __future__ import annotations

import shutil, sys
from pathlib import Path


def header(b: bytes) -> bytes:
    """SOI + every APPn segment (EXIF, XMP) of a JPEG."""
    i, out = 2, bytearray(b[:2])
    while b[i] == 0xFF and 0xE0 <= b[i + 1] <= 0xEF:
        n = int.from_bytes(b[i + 2:i + 4], "big"); out += b[i:i + 2 + n]; i += 2 + n
    return bytes(out)


def body(b: bytes) -> bytes:
    """Everything after SOI and the APPn segments."""
    i = 2
    while b[i] == 0xFF and 0xE0 <= b[i + 1] <= 0xEF: i += 2 + int.from_bytes(b[i + 2:i + 4], "big")
    return b[i:]


def main(work: str, data: str, folder: str, out: str) -> None:
    src, dst = Path(work, "test_b", "flights", "drone_photos", folder), Path(out); dst.mkdir(parents=True, exist_ok=True)
    for p in sorted(src.glob("*_V.JPG")):
        orig = Path(data, "flights", "drone_photos", folder, p.name).read_bytes()
        (dst / p.name).write_bytes(header(orig) + body(p.read_bytes()))
    print(f"{len(list(dst.glob('*_V.JPG')))} demo photos (painted shells + original drone metadata) -> {dst}")


if __name__ == "__main__":
    main(*sys.argv[1:5])
