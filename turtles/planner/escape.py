"""F6 fence-exit simulator: where do trapped turtles end up, and where would exit gaps free them?

Tanya (Oct 27): turtles trapped on a site walk to the silt fence and then *along* it, trying to escape.
So we simulate that on the real site:
  1. Hundreds of virtual turtles start inside the site outline and walk straight to the nearest fence.
  2. Along the fence they keep walking in one direction, with a pull downhill (USGS 3DEP terrain) and the
     occasional turn-around: uphill slopes make them turn back more often.
  3. Where they bunch up = trap points: check there first.
  4. Exit gaps: each candidate spot frees every turtle that would walk past it. We greedily pick the few gaps
     that free the most turtles. Gaps are never placed at low points, because runoff collects there and the
     silt fence must stay intact for erosion control (check final spots with Hazel's erosion-control lead).

Run on your Mac once (downloads terrain):  python3 -m turtles.planner.escape --fetch-dem
Then (any machine):                        python3 -m turtles.planner.escape
Writes out/dem.npz (terrain) and out/escape.json (fence, traps, gaps, sample tracks for pitch/escape_sim.html).
Model numbers are judgment calls, not field measurements: say so in the pitch.
"""
from __future__ import annotations

import argparse, io, json, math, urllib.parse, urllib.request
from pathlib import Path

import numpy as np

from turtles.geo import M_PER_DEG_LAT

OUT = Path(__file__).parent / "out"
SITE = Path(__file__).parent / "sites" / "grayson.geojson"
DEM_URL = "https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer/exportImage"
STEP_M = 2.0            # fence resolution and turtle step
N_TURTLES = 2000
WALK_M = 400            # how far a turtle walks along the fence (roughly a day or two of searching)
P_TURN = 0.02           # chance per step to turn around on flat ground
UPHILL_TURN = 4.0       # extra turn-around chance per unit uphill slope (10% grade -> +0.4)
LOW_POINT_M = 25        # a fence point is a drainage low if it's the lowest within this distance either way
NO_GAP_NEAR_LOW_M = 25  # keep gaps this far (along the fence) from drainage lows, so they read clearly as dry ground
N_GAPS = 3
SEED = 7


def fetch_dem(bbox, px: int = 800, path: Path = OUT / "dem.npz") -> Path:
    """USGS 3DEP elevation (1 m lidar where available) for bbox (W, S, E, N), in a lat/lon grid. Row 0 = north."""
    q = urllib.parse.urlencode({"bbox": ",".join(f"{v:.6f}" for v in bbox), "bboxSR": 4326, "imageSR": 4326,
                                "size": f"{px},{px}", "format": "tiff", "pixelType": "F32",
                                "interpolation": "RSP_BilinearInterpolation", "f": "image"})
    data = urllib.request.urlopen(f"{DEM_URL}?{q}", timeout=90).read()
    try:
        import rasterio
        with rasterio.MemoryFile(data) as m, m.open() as src:
            z = src.read(1).astype(float)
    except ImportError:
        from PIL import Image
        z = np.array(Image.open(io.BytesIO(data)), float)
    z[(z < -100) | (z > 3000)] = np.nan
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(path, z=z, bbox=np.array(bbox, float))
    return path


def site_ring(path: Path = SITE) -> list:
    return json.loads(Path(path).read_text())["features"][0]["geometry"]["coordinates"][0]


def ring_bbox(ring, pad_m: float = 60):
    r = np.array(ring); lat = r[:, 1].mean(); kl = M_PER_DEG_LAT * math.cos(math.radians(lat))
    return (r[:, 0].min() - pad_m / kl, r[:, 1].min() - pad_m / M_PER_DEG_LAT,
            r[:, 0].max() + pad_m / kl, r[:, 1].max() + pad_m / M_PER_DEG_LAT)


def sample_dem(dem: dict, lon, lat) -> np.ndarray:
    """Bilinear elevation at lon/lat from a fetched DEM grid."""
    z, (w, s, e, n) = dem["z"], dem["bbox"]
    H, W = z.shape
    fx = np.clip((np.asarray(lon) - w) / (e - w) * W - 0.5, 0, W - 1.001)
    fy = np.clip((n - np.asarray(lat)) / (n - s) * H - 0.5, 0, H - 1.001)
    x0, y0 = fx.astype(int), fy.astype(int); dx, dy = fx - x0, fy - y0
    return (z[y0, x0] * (1 - dx) * (1 - dy) + z[y0, x0 + 1] * dx * (1 - dy)
            + z[y0 + 1, x0] * (1 - dx) * dy + z[y0 + 1, x0 + 1] * dx * dy)


class Fence:
    """The site outline as points every STEP_M, in local meters, with elevation."""
    def __init__(self, ring, elev_fn):
        r = np.array(ring, float)
        self.lat0, self.lon0 = r[:, 1].mean(), r[:, 0].mean()
        self.kl = M_PER_DEG_LAT * math.cos(math.radians(self.lat0))
        xy = np.c_[(r[:, 0] - self.lon0) * self.kl, (r[:, 1] - self.lat0) * M_PER_DEG_LAT]
        pts = []
        for a, b in zip(xy, xy[1:]):
            n = max(1, int(np.hypot(*(b - a)) // STEP_M))
            pts += [a + (b - a) * k / n for k in range(n)]
        self.xy = np.array(pts)
        lon, lat = self.to_lonlat(self.xy)
        z = np.asarray(elev_fn(lon, lat), float)
        z = np.where(np.isfinite(z), z, np.nanmean(z) if np.isfinite(z).any() else 0)
        k = 3  # smooth over ~14 m so DEM noise doesn't create fake traps
        self.z = np.convolve(np.r_[z[-k:], z, z[:k]], np.ones(2 * k + 1) / (2 * k + 1), "valid")
        self.n = len(self.xy)

    def to_lonlat(self, xy):
        return self.lon0 + xy[:, 0] / self.kl, self.lat0 + xy[:, 1] / M_PER_DEG_LAT

    def inside(self, x, y):
        c = np.zeros(np.shape(x), bool); P = np.r_[self.xy, self.xy[:1]]
        for (x1, y1), (x2, y2) in zip(P, P[1:]):
            with np.errstate(divide="ignore", invalid="ignore"):
                c ^= ((y1 > y) != (y2 > y)) & (x < (x2 - x1) * (y - y1) / (y2 - y1) + x1)
        return c

    def lows(self) -> np.ndarray:
        w = int(LOW_POINT_M / STEP_M)
        idx = (np.arange(self.n)[:, None] + np.arange(-w, w + 1)) % self.n
        return np.flatnonzero(self.z <= self.z[idx].min(1) + 1e-9)


def simulate(f: Fence, n=N_TURTLES, walk_m=WALK_M, seed=SEED):
    """Returns starts (n,2), fence arrival index (n,), visited (n, f.n) bool, final fence index (n,), paths (list of idx arrays)."""
    rng = np.random.default_rng(seed)
    lo, hi = f.xy.min(0), f.xy.max(0); starts = []
    while len(starts) < n:
        p = rng.uniform(lo, hi, (n, 2)); starts += list(p[f.inside(p[:, 0], p[:, 1])])
    starts = np.array(starts[:n])
    arrive = np.argmin(((starts[:, None, :] - f.xy[None]) ** 2).sum(2), 1)  # straight to the nearest fence point
    steps = int(walk_m / STEP_M)
    visited = np.zeros((n, f.n), bool); final = np.empty(n, int); paths = []
    for t in range(n):
        s, d = arrive[t], rng.choice((-1, 1))
        dz_fwd = f.z[(s + 1) % f.n] - f.z[s]
        if rng.random() < 0.7: d = -1 if dz_fwd > 0 else 1        # first choice leans downhill
        path = [s]
        for _ in range(steps):
            nxt = (s + d) % f.n
            slope = (f.z[nxt] - f.z[s]) / STEP_M
            if rng.random() < P_TURN + UPHILL_TURN * max(slope, 0): d = -d; nxt = (s + d) % f.n
            s = nxt; path.append(s)
        path = np.array(path); visited[t, path] = True; final[t] = s; paths.append(path)
    return starts, arrive, visited, final, paths


def choose_gaps(f: Fence, visited: np.ndarray, k=N_GAPS):
    """Greedy max-coverage: a gap at fence point v frees every turtle whose walk passes v."""
    banned = np.zeros(f.n, bool); w = int(NO_GAP_NEAR_LOW_M / STEP_M)
    for i in f.lows():
        banned[(np.arange(i - w, i + w + 1)) % f.n] = True
    freed = np.zeros(visited.shape[0], bool); gaps = []
    for _ in range(k):
        gain = (visited & ~freed[:, None]).sum(0); gain[banned] = -1
        for g in gaps:  # gaps need spacing: no two within 40 m
            gain[(np.arange(g - 20, g + 21)) % f.n] = -1
        v = int(np.argmax(gain))
        if gain[v] <= 0: break
        freed |= visited[:, v]; gaps.append(v)
    return gaps, banned


def traps(f: Fence, final: np.ndarray, k=3, spacing_m=60):
    """Fence points where the most turtles end up (smoothed over ~10 m), spaced apart."""
    h = np.bincount(final, minlength=f.n).astype(float)
    h = np.convolve(np.r_[h[-2:], h, h[:2]], np.ones(5), "valid")
    out = []
    for i in np.argsort(-h):
        if len(out) == k or h[i] <= 0: break
        if all(min(abs(i - j), f.n - abs(i - j)) * STEP_M >= spacing_m for j in out): out.append(int(i))
    return out, h


def run(ring, dem: dict | None, n=N_TURTLES, n_tracks=250):
    elev = (lambda lo, la: sample_dem(dem, lo, la)) if dem is not None else (lambda lo, la: np.zeros(np.shape(lo)))
    f = Fence(ring, elev)
    starts, arrive, visited, final, paths = simulate(f, n)
    gaps, banned = choose_gaps(f, visited)
    tr, h = traps(f, final)
    freed, curve = np.zeros(n, bool), [0.0]
    for g in gaps:
        freed |= visited[:, g]; curve.append(round(100 * freed.mean(), 1))
    ll = lambda idx: [[round(float(a), 7), round(float(b), 7)] for a, b in zip(*f.to_lonlat(f.xy[np.atleast_1d(idx)]))]
    fence_ll = ll(np.arange(f.n))
    lows = f.lows()
    tracks = []
    for t in range(min(n_tracks, n)):
        s0 = starts[t]; a = f.xy[arrive[t]]; L = np.hypot(*(a - s0)); m = max(1, int(L // STEP_M))
        lead = [s0 + (a - s0) * j / m for j in range(m)]
        lon, lat = f.to_lonlat(np.array(lead)) if lead else ([], [])
        tracks.append({"lead": [[round(float(x), 7), round(float(y), 7)] for x, y in zip(lon, lat)],
                       "fence": paths[t][::2].tolist(), "freed_by": next((gaps.index(g) for g in gaps if visited[t, g]), None)})
    # same turtles on flat ground: shows the pile-ups come from the terrain, not from chance or fence shape
    f0 = Fence(ring, lambda lo, la: np.zeros(np.shape(lo)))
    _, _, _, final0, paths0 = simulate(f0, n)
    tr0, h0 = traps(f0, final0)
    flat = {"tracks": [paths0[t][::2].tolist() for t in range(min(n_tracks, n))],
            "max_share_pct": round(100 * float(h0.max()) / n, 1), "terrain_max_share_pct": round(100 * float(h.max()) / n, 1)}
    zf = f.z
    return {"flat": flat, "turtles": n, "walk_m": WALK_M, "step_m": STEP_M, "fence": fence_ll,
            "fence_elev_m": [round(float(z), 2) for z in zf], "terrain": dem.get("source", "USGS 3DEP") if dem is not None else "flat (no DEM)",
            "relief_m": round(float(zf.max() - zf.min()), 1),
            "traps": [{"fence_idx": int(i), "lonlat": ll(i)[0], "share_pct": round(100 * float(h[i]) / n, 1), "elev_m": round(float(zf[i]), 1)} for i in tr],
            "gaps": [{"fence_idx": int(g), "lonlat": ll(g)[0], "freed_cum_pct": curve[j + 1], "elev_m": round(float(zf[g]), 1)} for j, g in enumerate(gaps)],
            "drainage_lows": ll(lows), "freed_curve_pct": curve, "tracks": tracks}


def summary(res) -> str:
    g = res["gaps"]
    lines = [f"{res['turtles']} virtual turtles, {res['walk_m']} m of fence-walking each, terrain: {res['terrain']} "
             f"({res['relief_m']} m of relief along the fence)."]
    lines += [f"Trap {i + 1}: {t['share_pct']}% of turtles end up here ({t['lonlat'][1]:.5f}, {t['lonlat'][0]:.5f})." for i, t in enumerate(res["traps"])]
    lines += [f"Gap {i + 1} at ({x['lonlat'][1]:.5f}, {x['lonlat'][0]:.5f}): {x['freed_cum_pct']}% of turtles walk out on their own." for i, x in enumerate(g)]
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="F6: fence-exit simulator")
    ap.add_argument("--site", default=str(SITE)); ap.add_argument("--fetch-dem", action="store_true")
    ap.add_argument("--turtles", type=int, default=N_TURTLES); ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args(argv)
    ring = site_ring(a.site); a.out.mkdir(parents=True, exist_ok=True)
    dem_path = a.out / "dem.npz"
    if a.fetch_dem:
        fetch_dem(ring_bbox(ring), path=dem_path)
        d = np.load(dem_path); z = d["z"]
        print(f"Terrain: {z.shape[1]}x{z.shape[0]} px, {np.nanmin(z):.1f}-{np.nanmax(z):.1f} m. Saved {dem_path}")
    dem = dict(np.load(dem_path)) if dem_path.exists() else None
    res = run(ring, dem, a.turtles)
    (a.out / "escape.json").write_text(json.dumps(res))
    print(summary(res)); print(f"Files in {a.out}")
    return res


if __name__ == "__main__":
    main()
