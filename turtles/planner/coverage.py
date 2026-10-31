"""F4 coverage map: which parts of the site did the drone actually see well enough to spot a turtle?

For every photo: read GPS, height and camera angle from the DJI metadata, project a grid of image blocks onto
the ground, and keep the blocks seen sharply enough (slant range <= 20 m, the detail of a straight-down 65 ft
shot, where a box turtle is still ~24 px). Each block also gets a greenness score: ground hidden under
green brush can't be checked from the air, even if the drone flew over it.

Output, over the site outline on a 4 m grid:
  * % of the site seen clearly, % seen but under vegetation, % never seen
  * out/coverage.geojson: cells to walk on foot (status "not_seen" or "vegetation"), plus walk-area summaries
  * out/coverage_summary.json

Run:  python3 -m turtles.planner.coverage --photos "<drone_photos folder>" --site turtles/planner/sites/grayson.geojson
Photos are read in place and never copied; out/ holds numbers only and is gitignored. Results are cached per
photo in out/coverage_cache.json, so reruns (or --limit batches) only process new photos.
"""
from __future__ import annotations

import argparse, glob, json, math, os, re
from pathlib import Path

import numpy as np
from PIL import Image

from turtles.geo import M_PER_DEG_LAT

OUT = Path(__file__).parent / "out"
FOCAL_PX, IMG_W, IMG_H = 3725.15, 5280, 3956  # Mavic 3E wide camera (CalibratedFocalLength)
MAX_RANGE_M = 20.0     # slant range limit = detail of a nadir 65 ft photo (turtle ~24 px)
GRID = (24, 18)        # image blocks per photo (columns, rows)
GREEN_EXG = 0.06       # pixel counts as green vegetation above this excess-green index
VEG_FRAC = 0.5         # a block is "under vegetation" if more than half its pixels are green
CELL_M = 4.0
MIN_PATCH_M2 = 150     # walk areas smaller than this are folded into the % but not listed
KEYS = ["GpsLatitude", "GpsLongitude", "RelativeAltitude", "GimbalYawDegree", "GimbalPitchDegree"]


def read_meta(path: str) -> dict | None:
    s = open(path, "rb").read(120_000).decode("latin1")
    v = {k: (m := re.search(k + r'="([-+0-9.]+)"', s)) and float(m.group(1)) for k in KEYS}
    return None if None in v.values() else v


def ground_offsets(u, v, h, pitch_deg, yaw_deg):
    """Image pixel offsets from center (u right, v down, px) -> ground (east, north, slant range) in meters.
    Camera at height h, tilted pitch_deg (−90 = straight down), facing yaw_deg. NaN where the ray misses the ground."""
    th = math.radians(-pitch_deg)                      # angle below the horizon
    axis, up = np.array([math.cos(th), math.sin(th)]), np.array([math.sin(th), -math.cos(th)])  # (forward, down)
    fwd = FOCAL_PX * axis[0] - v * up[0]
    down = FOCAL_PX * axis[1] - v * up[1]
    right = np.asarray(u, float)
    with np.errstate(divide="ignore", invalid="ignore"):
        t = np.where(down > 1e-9, h / down, np.nan)
    f, r = fwd * t, right * t
    y = math.radians(yaw_deg)
    east, north = f * math.sin(y) + r * math.cos(y), f * math.cos(y) - r * math.sin(y)
    return east, north, np.sqrt(f * f + r * r + h * h)


def green_fraction(img: Image.Image, grid=GRID) -> np.ndarray:
    """Fraction of green pixels per block, shape (rows, cols)."""
    a = np.asarray(img.convert("RGB").resize((grid[0] * 16, grid[1] * 16)), float)
    s = a.sum(2) + 1e-6
    exg = (2 * a[..., 1] - a[..., 0] - a[..., 2]) / s
    return (exg > GREEN_EXG).reshape(grid[1], 16, grid[0], 16).mean((1, 3))


def photo_samples(path: str, meta: dict, grid=GRID) -> list | None:
    """[(lat, lon, green_frac), ...] for image blocks within MAX_RANGE_M."""
    with Image.open(path) as im:
        im.draft("RGB", (IMG_W // 8, IMG_H // 8))   # fast JPEG decode at 1/8 size
        g = green_fraction(im, grid)
    cols, rows = grid
    u = ((np.arange(cols) + 0.5) / cols - 0.5) * IMG_W
    v = ((np.arange(rows) + 0.5) / rows - 0.5) * IMG_H
    U, V = np.meshgrid(u, v)
    e, n, rng = ground_offsets(U, V, meta["RelativeAltitude"], meta["GimbalPitchDegree"], meta["GimbalYawDegree"])
    ok = np.isfinite(rng) & (rng <= MAX_RANGE_M)
    lat0, lon0 = meta["GpsLatitude"], meta["GpsLongitude"]
    kl = M_PER_DEG_LAT * math.cos(math.radians(lat0))
    return [[round(lat0 + nn / M_PER_DEG_LAT, 7), round(lon0 + ee / kl, 7), round(float(gg), 2)]
            for ee, nn, gg in zip(e[ok], n[ok], g[ok])]


def scan(folders: list[str], cache_path: Path, limit: int | None = None) -> dict:
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    todo = [f for d in folders for f in sorted(glob.glob(os.path.join(d, "**", "*_V.JPG"), recursive=True))
            if os.path.basename(f) not in cache]
    for i, f in enumerate(todo[:limit]):
        m = read_meta(f)
        cache[os.path.basename(f)] = photo_samples(f, m) if m else []
        if i % 100 == 99: cache_path.write_text(json.dumps(cache))
    cache_path.write_text(json.dumps(cache))
    left = max(0, len(todo) - (limit or len(todo)))
    print(f"{len(cache)} photos cached, {left} still to scan")
    return cache


def inside(lon, lat, ring) -> np.ndarray:
    lon, lat, c = np.asarray(lon), np.asarray(lat), np.zeros(np.shape(lon), bool)
    for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
        with np.errstate(divide="ignore", invalid="ignore"):
            c ^= ((y1 > lat) != (y2 > lat)) & (lon < (x2 - x1) * (lat - y1) / (y2 - y1) + x1)
    return c


def coverage(samples: np.ndarray, ring: list) -> dict:
    """samples: (n, 3) lat, lon, green. Returns grid status over the site and summary numbers."""
    ring = np.array(ring)
    lat0 = ring[:, 1].mean(); kl = M_PER_DEG_LAT * math.cos(math.radians(lat0))
    lon_min, lat_min = ring[:, 0].min(), ring[:, 1].min()
    W = int((ring[:, 0].max() - lon_min) * kl / CELL_M) + 1
    H = int((ring[:, 1].max() - lat_min) * M_PER_DEG_LAT / CELL_M) + 1
    cj, ci = np.meshgrid(np.arange(W), np.arange(H))
    clon, clat = lon_min + (cj + .5) * CELL_M / kl, lat_min + (ci + .5) * CELL_M / M_PER_DEG_LAT
    site = inside(clon, clat, ring.tolist())
    seen, green = np.zeros((H, W)), np.zeros((H, W))
    if len(samples):
        j = ((samples[:, 1] - lon_min) * kl / CELL_M).astype(int); i = ((samples[:, 0] - lat_min) * M_PER_DEG_LAT / CELL_M).astype(int)
        ok = (i >= 0) & (i < H) & (j >= 0) & (j < W)
        np.add.at(seen, (i[ok], j[ok]), 1); np.add.at(green, (i[ok], j[ok]), samples[ok, 2])
    with np.errstate(invalid="ignore"):
        gmean = np.where(seen > 0, green / np.maximum(seen, 1), np.nan)
    status = np.full((H, W), "", object)
    status[site & (seen == 0)] = "not_seen"
    status[site & (seen > 0) & (gmean > VEG_FRAC)] = "vegetation"
    status[site & (seen > 0) & ~(gmean > VEG_FRAC)] = "clear"
    n = site.sum() or 1
    pct = {k: round(100 * float((status == k).sum()) / n, 1) for k in ("clear", "vegetation", "not_seen")}
    return {"status": status, "clon": clon, "clat": clat, "kl": kl, "pct": pct, "site_cells": int(n)}


def patches(status: np.ndarray) -> list[np.ndarray]:
    """Connected groups of cells that need walking (4-neighbour flood fill)."""
    need = np.isin(status, ["not_seen", "vegetation"]); seen = np.zeros_like(need); out = []
    for i0, j0 in zip(*np.nonzero(need)):
        if seen[i0, j0]: continue
        stack, cells = [(i0, j0)], []; seen[i0, j0] = True
        while stack:
            i, j = stack.pop(); cells.append((i, j))
            for a, b in ((i + 1, j), (i - 1, j), (i, j + 1), (i, j - 1)):
                if 0 <= a < need.shape[0] and 0 <= b < need.shape[1] and need[a, b] and not seen[a, b]:
                    seen[a, b] = True; stack.append((a, b))
        out.append(np.array(cells))
    return out


def to_geojson(cov: dict) -> tuple[dict, list]:
    st, clon, clat, kl = cov["status"], cov["clon"], cov["clat"], cov["kl"]
    dx, dy = CELL_M / 2 / kl, CELL_M / 2 / M_PER_DEG_LAT
    sq = lambda lo, la: [[[round(lo - dx, 7), round(la - dy, 7)], [round(lo + dx, 7), round(la - dy, 7)],
                          [round(lo + dx, 7), round(la + dy, 7)], [round(lo - dx, 7), round(la + dy, 7)], [round(lo - dx, 7), round(la - dy, 7)]]]
    feats = [{"type": "Feature", "properties": {"status": str(st[i, j])}, "geometry": {"type": "Polygon", "coordinates": sq(clon[i, j], clat[i, j])}}
             for i, j in zip(*np.nonzero(np.isin(st, ["not_seen", "vegetation"])))]
    areas = []
    for p in sorted(patches(st), key=len, reverse=True):
        m2 = len(p) * CELL_M ** 2
        if m2 < MIN_PATCH_M2: continue
        la, lo = float(clat[p[:, 0], p[:, 1]].mean()), float(clon[p[:, 0], p[:, 1]].mean())
        kinds = st[p[:, 0], p[:, 1]]
        why = "under vegetation" if (kinds == "vegetation").mean() > 0.5 else "not seen by the drone"
        areas.append({"lat": round(la, 6), "lon": round(lo, 6), "area_m2": int(m2), "why": why})
        feats.append({"type": "Feature", "properties": {"status": "walk_area", "area_m2": int(m2), "why": why,
                      "name": f"Walk this: {int(m2)} m², {why}"}, "geometry": {"type": "Point", "coordinates": [round(lo, 6), round(la, 6)]}})
    return {"type": "FeatureCollection", "features": feats}, areas


def main(argv=None):
    ap = argparse.ArgumentParser(description="F4: what the drone could and couldn't check")
    ap.add_argument("--photos", action="append", required=True, help="folder of DJI photos (repeatable)")
    ap.add_argument("--site", default=str(Path(__file__).parent / "sites" / "grayson.geojson"))
    ap.add_argument("--limit", type=int, help="scan at most N new photos this run")
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args(argv)
    a.out.mkdir(parents=True, exist_ok=True)
    cache = scan(a.photos, a.out / "coverage_cache.json", a.limit)
    samples = np.array([s for v in cache.values() for s in v] or np.zeros((0, 3)), float).reshape(-1, 3)
    ring = json.loads(Path(a.site).read_text())["features"][0]["geometry"]["coordinates"][0]
    cov = coverage(samples, ring)
    fc, areas = to_geojson(cov)
    p = cov["pct"]
    summary = {"photos": len(cache), "site_acres": round(cov["site_cells"] * CELL_M ** 2 / 4046.86, 1), **{f"pct_{k}": v for k, v in p.items()},
               "headline": f"The drone checked {p['clear']:.0f}% of the site clearly. Walk the rest on foot: "
                           f"{p['vegetation']:.0f}% is under vegetation and {p['not_seen']:.0f}% was never in view.",
               "walk_areas": areas}
    (a.out / "coverage.geojson").write_text(json.dumps(fc))
    (a.out / "coverage_summary.json").write_text(json.dumps(summary, indent=1))
    print(summary["headline"]); print(f"{len(areas)} walk areas over {MIN_PATCH_M2} m². Files in {a.out}")
    return summary


if __name__ == "__main__":
    main()
