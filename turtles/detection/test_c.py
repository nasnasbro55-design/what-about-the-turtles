"""Test C - fence-line simulation (reported separately; it is pasted, so never the headline).

Turtles mostly pace the silt fence trying to get out (Tanya). Test C puts a living-turtle shell 0.5-2 m inside the
traced fence line in survey leg 3 photos - straight-down 50 ft photos the models never trained on - and asks the
detector to find it. Protocol fixed before any result:
  * ground: every leg-3 photo the fence crosses (one turtle per photo, inside the photo by >= 100 px)
  * turtle: a real drone-photo shell from a ~50 ft hover photo (real camera, blur, scale), cut along its traced
    outline, re-skinned with the HELD-OUT skins (never used in training), random rotation, sun shadow to the NNW
    (10:40 EDT, Oct 24: sun ~150 deg), size from that photo's altitude
  * scoring: evaluate.py rules (center within max(20 px, half diagonal)), recall @0.25 + false alarms per photo

    python3 -m turtles.detection.test_c <work> "<TNUX Turtles Data>"          # -> <work>/test_c (photos + labels.json)
    python3 -m turtles.detection.evaluate <work> <work>/test_c <weights> --splits survey --spots 03_survey_part3 --labels <work>/test_c/labels.json --no-survey
"""
from __future__ import annotations

import csv, json, math, random, sys
from pathlib import Path

import cv2
import numpy as np

from turtles.backend.ingest import frame_from_photo
from turtles.detection.reskin import load_skins, outline, reskin
from turtles.geo import M_PER_DEG_LAT, gsd_m

FENCE = Path(__file__).parents[1] / "planner" / "sites" / "grayson.geojson"
SUN_SHADOW_AZ = 330.0   # shadows point NNW at ~10:40 EDT on Oct 24 (sun ~150 deg)


def latlon_to_pixel(f, lat: float, lon: float) -> tuple[float, float]:
    """Inverse of geo.pixel_to_latlon for a straight-down frame."""
    g = gsd_m(f.alt_m, f.hfov_deg, f.width_px); yaw = math.radians(f.yaw_deg)
    east, north = (lon - f.lon) * M_PER_DEG_LAT * math.cos(math.radians(f.lat)), (lat - f.lat) * M_PER_DEG_LAT
    return f.width_px / 2 + (east * math.cos(yaw) - north * math.sin(yaw)) / g, f.height_px / 2 + (-east * math.sin(yaw) - north * math.cos(yaw)) / g


def ground_dir_px(f, az_deg: float) -> np.ndarray:
    """Unit pixel vector of a ground direction (azimuth, degrees from north) in this frame."""
    a = math.radians(az_deg); dl = 1e-5
    p0, p1 = latlon_to_pixel(f, f.lat, f.lon), latlon_to_pixel(f, f.lat + dl * math.cos(a), f.lon + dl * math.sin(a) / math.cos(math.radians(f.lat)))
    v = np.subtract(p1, p0); return v / np.linalg.norm(v)


def inside(lat, lon, ring) -> bool:
    c = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
        if (y1 > lat) != (y2 > lat) and lon < (x2 - x1) * (lat - y1) / (y2 - y1) + x1: c = not c
    return c


def turtle_cutouts(work: str, data: str) -> list[np.ndarray]:
    """RGBA cut-outs (BGR + alpha) of real ~50 ft drone shells, re-skinned with held-out skins only."""
    lab, te, r, out = json.load(open(Path(work, "labels.json")))["labels"], load_skins(work, "test"), random.Random(11), []
    rows = {Path(x["path"]).name: x for x in csv.DictReader(open(Path(work, "frames.csv")))}
    for src, boxes in sorted(lab.items()):
        if not boxes or "_TEST_" in src or not 44 <= float(rows[Path(src).name]["alt_ft"]) <= 56: continue
        img = cv2.imread(str(Path(data, "flights", "drone_photos", src)))
        for b in boxes:
            new = reskin(img, b, r.choice(te), r)
            if new is img: continue                                          # untraceable shell: skip, never guess
            X0, Y0, m = outline(img, b); ys, xs = np.nonzero(m)
            c = new[Y0 + ys.min():Y0 + ys.max() + 1, X0 + xs.min():X0 + xs.max() + 1]
            a = cv2.GaussianBlur(m[ys.min():ys.max() + 1, xs.min():xs.max() + 1].astype(np.float32), (0, 0), 0.6)
            out.append(np.dstack([c, (a * 255).astype(np.uint8)]))
    return out


def main(work: str, data: str) -> None:
    ring = json.loads(FENCE.read_text())["features"][0]["geometry"]["coordinates"][0]
    out = Path(work, "test_c"); cdir = out / "cutouts"
    if not cdir.exists():                                                    # cache: same cut-outs every run
        cdir.mkdir(parents=True); [cv2.imwrite(str(cdir / f"{i:03d}.png"), c) for i, c in enumerate(turtle_cutouts(work, data))]
    cut = [cv2.imread(str(q), cv2.IMREAD_UNCHANGED) for q in sorted(cdir.glob("*.png"))]
    lf = out / "labels.json"; labels = json.load(open(lf))["labels"] if lf.exists() else {}
    for p in sorted(Path(data, "flights", "drone_photos").glob("03_survey_part3*/*_V.JPG")):
        r = random.Random(p.name)                                            # per-photo seed: resumable, same result every run
        if f"{p.parent.name}/{p.name}" in labels or (out / "skipped" / p.name).exists(): continue
        f = frame_from_photo(p, p.parent, "grayson", "C")
        if f is None: continue
        g = gsd_m(f.alt_m, f.hfov_deg, f.width_px); W, H = f.width_px, f.height_px
        pts = []   # fence points inside this photo, every ~1 m along each edge
        for (lo1, la1), (lo2, la2) in zip(ring, ring[1:]):
            n = max(2, int(math.dist((lo1 * 86000, la1 * 111320), (lo2 * 86000, la2 * 111320))))
            for t in np.linspace(0, 1, n):
                la, lo = la1 + t * (la2 - la1), lo1 + t * (lo2 - lo1); x, y = latlon_to_pixel(f, la, lo)
                if 150 < x < W - 150 and 150 < y < H - 150: pts.append((la, lo, la2 - la1, lo2 - lo1))
        if not pts: (out / "skipped").mkdir(exist_ok=True); (out / "skipped" / p.name).touch(); continue
        r.shuffle(pts); cx = None
        for la, lo, dla, dlo in pts:                                         # first fence point whose turtle stays >= 100 px inside the photo
            nx, ny = -dla, dlo; k = 1 / math.hypot(nx * M_PER_DEG_LAT, ny * M_PER_DEG_LAT * math.cos(math.radians(la)))
            d = r.uniform(0.5, 2.0)                                          # metres inside the fence
            cand = [(la + s_ * d * nx * k, lo + s_ * d * ny * k) for s_ in (1, -1)]
            tla, tlo = next((c for c in cand if inside(c[0], c[1], ring)), cand[0])
            x, y = latlon_to_pixel(f, tla, tlo)
            if 100 < x < W - 100 and 100 < y < H - 100: cx, cy = x, y; break
        if cx is None: (out / "skipped").mkdir(exist_ok=True); (out / "skipped" / p.name).touch(); continue
        img, t = cv2.imread(str(p)), cut[r.randrange(len(cut))]
        L = 0.13 / g * r.uniform(0.85, 1.15)                                  # ~13 cm shell at this altitude
        M = cv2.getRotationMatrix2D((t.shape[1] / 2, t.shape[0] / 2), r.uniform(0, 360), L / max(t.shape[:2]))
        side = int(max(t.shape[:2]) * L / max(t.shape[:2]) * 1.6) + 6; M[:, 2] += side / 2 - np.array([t.shape[1] / 2, t.shape[0] / 2])
        tw = cv2.warpAffine(t, M, (side, side), flags=cv2.INTER_AREA)
        a = tw[:, :, 3:].astype(float) / 255; x0, y0 = int(cx - side / 2), int(cy - side / 2)
        reg = img[y0:y0 + side, x0:x0 + side].astype(float)
        sv = ground_dir_px(f, SUN_SHADOW_AZ) * 0.35 * L                       # sun shadow, NNW, soft
        sh = cv2.GaussianBlur(cv2.warpAffine(a[:, :, 0], np.float32([[1, 0, sv[0]], [0, 1, sv[1]]]), (side, side)), (0, 0), 1.2)[:, :, None]
        reg = reg * (1 - 0.45 * sh * (1 - a)); reg = reg * (1 - a) + tw[:, :, :3] * a
        img[y0:y0 + side, x0:x0 + side] = np.clip(reg, 0, 255).astype(np.uint8)
        ys, xs = np.nonzero(a[:, :, 0] > 0.4); box = [int(x0 + xs.min()), int(y0 + ys.min()), int(x0 + xs.max() + 1), int(y0 + ys.max() + 1)]
        src = f"{p.parent.name}/{p.name}"; labels[src] = [box]
        dst = out / "flights" / "drone_photos" / src; dst.parent.mkdir(parents=True, exist_ok=True); cv2.imwrite(str(dst), img, [cv2.IMWRITE_JPEG_QUALITY, 95])
        json.dump({"labels": labels, "protocol": __doc__}, open(lf, "w")); print(src, box, flush=True)
    print(f"Test C: {len(labels)} leg-3 photos with a turtle {0.5}-{2.0} m inside the fence ({len(cut)} held-out-skin cut-outs) -> {out}")


if __name__ == "__main__":
    main(*sys.argv[1:3])
