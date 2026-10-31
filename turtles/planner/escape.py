"""F6 fence-exit simulator (v2, rebuilt from the Oct 30 meeting with Tanya Finch and Olivia LoBalbo).

What they told us, and how the model uses it:
  * Turtles come from anywhere on the site and head their own way (internal GPS: nest, water, birthplace).
    Topography doesn't steer them. In fall the general trend is toward woodland/higher ground to overwinter,
    but individuals vary.  -> each turtle gets its own heading; FALL_WOODS_SHARE of them aim at the nearest woods.
  * At the silt fence they walk along it looking for an exit, roughly 50-100 ft, then give up and hunker down,
    usually within 6-10 ft of the fence.  -> walk WALK_FT along the fence in the direction closest to their heading.
  * Corners funnel turtles from two fence lines; they hesitate there and look around before moving on.
    -> a ramp at a corner is found more often (P_USE_CORNER) than one on a straight run (P_USE_STRAIGHT).
  * Exit method on the table at W.A. Hazel: mound dirt over the fence every 100-150 ft. Silt fence handles sheet flow,
    so ramps don't need to avoid low points.  -> we test that proposal against ramps at corners.
  * Deterrents (noise, smell) are unknown. -> "what if" multipliers: a deterrent that keeps turtles searching longer.

Numbers marked (judgment) are ours, not field measurements: say so in the pitch, and swap in Dr. Ben Reed's data.
Run:  python3 -m turtles.planner.escape        (needs out/heatmap.geojson for the woods; no internet)
Writes out/escape.json for pitch/escape_sim.html.
"""
from __future__ import annotations

import argparse, json, math
from pathlib import Path

import numpy as np

from turtles.geo import M_PER_DEG_LAT

OUT = Path(__file__).parent / "out"
SITE = Path(__file__).parent / "sites" / "grayson.geojson"
HEATMAP = OUT / "heatmap.geojson"
FT = 0.3048
STEP_M = 2.0
N_TURTLES = 2000
WALK_FT = (50, 100)          # Tanya: at least 50-100 ft along the fence before giving up
FALL_WOODS_SHARE = 0.5       # (judgment) share of turtles aiming for the nearest woods in fall; the rest random
HEADING_NOISE_DEG = 35       # (judgment) individuals vary
P_USE_STRAIGHT = 0.6         # (judgment) chance a turtle walking past a ramp on a straight run climbs it
P_USE_CORNER = 0.9           # (judgment) higher at corners, where they hesitate and look around
P_CORNER_STOP = 0.5          # (judgment) Tanya/Olivia: they hesitate at corners; half give up and hunker there
RAMP_HALF_M = 2.0            # a ramp catches turtles passing within 2 m of its center
CORNER_MAX_DEG = 120         # outward-pointing fence corners sharper than this funnel turtles
CORNER_SPACING_M = 30
DETERRENT_MULT = (1.0, 1.5, 2.0)  # what-if: a deterrent keeps turtles searching 1.5x / 2x as far
SEED = 7


def site_ring(path: Path = SITE) -> list:
    return json.loads(Path(path).read_text())["features"][0]["geometry"]["coordinates"][0]


class Fence:
    """The site outline as points every STEP_M in local meters, with outward-pointing corners."""
    def __init__(self, ring):
        r = np.array(ring, float)
        self.lat0, self.lon0 = r[:, 1].mean(), r[:, 0].mean()
        self.kl = M_PER_DEG_LAT * math.cos(math.radians(self.lat0))
        xy = np.c_[(r[:, 0] - self.lon0) * self.kl, (r[:, 1] - self.lat0) * M_PER_DEG_LAT]
        pts = []
        for a, b in zip(xy, xy[1:]):
            m = max(1, int(np.hypot(*(b - a)) // STEP_M))
            pts += [a + (b - a) * k / m for k in range(m)]
        self.xy = np.array(pts); self.n = len(self.xy)
        self.corners, self.corner_deg = self._corners()

    def to_lonlat(self, xy):
        xy = np.atleast_2d(xy)
        return self.lon0 + xy[:, 0] / self.kl, self.lat0 + xy[:, 1] / M_PER_DEG_LAT

    def to_xy(self, lon, lat):
        return np.c_[(np.asarray(lon) - self.lon0) * self.kl, (np.asarray(lat) - self.lat0) * M_PER_DEG_LAT]

    def inside(self, x, y):
        c = np.zeros(np.shape(x), bool); P = np.r_[self.xy, self.xy[:1]]
        for (x1, y1), (x2, y2) in zip(P, P[1:]):
            with np.errstate(divide="ignore", invalid="ignore"):
                c ^= ((y1 > y) != (y2 > y)) & (x < (x2 - x1) * (y - y1) / (y2 - y1) + x1)
        return c

    def _corners(self):
        P, n, k = self.xy, self.n, 8   # compare directions +-16 m either side
        i = np.arange(n); a = P[(i - k) % n] - P; b = P[(i + k) % n] - P
        ang = np.degrees(np.arccos(np.clip((a * b).sum(1) / (np.linalg.norm(a, axis=1) * np.linalg.norm(b, axis=1) + 1e-9), -1, 1)))
        area = 0.5 * np.sum(P[:, 0] * np.roll(P[:, 1], -1) - np.roll(P[:, 0], -1) * P[:, 1])
        cross = a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0]
        outward = cross > 0 if area < 0 else cross < 0   # tip points away from the site
        cand = np.flatnonzero(outward & (ang < CORNER_MAX_DEG)); picks = []
        for c in cand[np.argsort(ang[cand])]:
            if all(self.gap(c, j) * STEP_M > CORNER_SPACING_M for j in picks): picks.append(int(c))
        return picks, [float(ang[c]) for c in picks]

    def gap(self, i, j):
        d = abs(int(i) - int(j)); return min(d, self.n - d)


def woods_xy(f: Fence, heatmap: Path = HEATMAP) -> np.ndarray:
    """Off-site dense-cover cells from the F2 heat map (same scene-calibrated threshold as F1)."""
    if not Path(heatmap).exists(): return np.zeros((0, 2))
    from turtles.planner.relocation import load_cells
    c = load_cells(heatmap); m = ~c["on_site"] & (c["ndvi"] >= c["cover"])
    return f.to_xy(c["lon"][m], c["lat"][m])


def hit_fence(f: Fence, start, heading_rad):
    """First fence point hit walking straight from start along heading (ray-segment intersection)."""
    d = np.array([math.sin(heading_rad), math.cos(heading_rad)])
    A, B = f.xy, np.roll(f.xy, -1, 0); e = B - A; w = A - start
    den = d[0] * e[:, 1] - d[1] * e[:, 0]
    with np.errstate(divide="ignore", invalid="ignore"):
        t = (w[:, 0] * e[:, 1] - w[:, 1] * e[:, 0]) / den
        u = (w[:, 0] * d[1] - w[:, 1] * d[0]) / den
    ok = (np.abs(den) > 1e-9) & (t > 0) & (u >= 0) & (u <= 1)
    if not ok.any(): return int(np.argmin(np.hypot(*(A - start).T))), 0.0
    j = int(np.flatnonzero(ok)[np.argmin(t[ok])]); return j, float(t[j])


def simulate(f: Fence, woods: np.ndarray, n=N_TURTLES, seed=SEED, max_mult=max(DETERRENT_MULT)):
    rng = np.random.default_rng(seed)
    lo, hi = f.xy.min(0), f.xy.max(0); starts = []
    while len(starts) < n:
        p = rng.uniform(lo, hi, (n, 2)); starts += list(p[f.inside(p[:, 0], p[:, 1])])
    starts = np.array(starts[:n]); T = []
    for s in starts:
        if len(woods) and rng.random() < FALL_WOODS_SHARE:
            v = woods[np.argmin(((woods - s) ** 2).sum(1))] - s; h = math.atan2(v[0], v[1]); kind = "woods"
        else:
            h = rng.uniform(0, 2 * math.pi); kind = "random"
        h += math.radians(rng.normal(0, HEADING_NOISE_DEG))
        j, dist = hit_fence(f, s, h)
        tang = f.xy[(j + 1) % f.n] - f.xy[j]
        step = 1 if tang @ np.array([math.sin(h), math.cos(h)]) >= 0 else -1
        walk = rng.uniform(*WALK_FT) * FT
        steps = int(round(walk * max_mult / STEP_M))
        path = (j + step * np.arange(steps + 1)) % f.n
        stop = steps  # corner hesitation: some turtles give up at the first corner they reach
        at = [k for k, x in enumerate(path) if k > 0 and any(f.gap(x, c) == 0 for c in f.corners)]
        if at and rng.random() < P_CORNER_STOP: stop = at[0]
        T.append({"start": s, "heading": h, "kind": kind, "hit": j, "lead_m": dist, "dir": step,
                  "walk_steps": min(int(round(walk / STEP_M)), stop), "stop": stop, "path": path,
                  "u": rng.random(steps + 1)})
    return T


def exit_step(f: Fence, tr: dict, ramps: list, corner_set: set, steps: int) -> int:
    """Index along the turtle's fence walk where it climbs a ramp, or -1."""
    if not ramps: return -1
    R = np.array(ramps); r = int(round(RAMP_HALF_M / STEP_M)); last = None
    for k, idx in enumerate(tr["path"][:steps + 1]):
        d = np.abs(R - idx); d = np.minimum(d, f.n - d)
        near = R[d <= r]
        if near.size and near[0] != last:
            last = near[0]
            p = P_USE_CORNER if any(f.gap(near[0], c) <= 3 for c in corner_set) else P_USE_STRAIGHT
            if tr["u"][k] < p: return k
    return -1


def evenly(f: Fence, spacing_m: float, offset_m: float = 0) -> list:
    k = max(1, int(round(spacing_m / STEP_M)))
    return sorted({int((int(offset_m / STEP_M) + i * k) % f.n) for i in range(int(math.ceil(f.n / k)))})


def scenarios(f: Fence):
    c = f.corners
    fill = sorted(set(c) | {i for i in evenly(f, 150 * FT) if all(f.gap(i, j) * STEP_M > 20 for j in c)})
    return [("none", "No exits", []),
            ("every150", "Dirt ramps every 150 ft (Hazel's proposal)", evenly(f, 150 * FT)),
            ("every100", "Dirt ramps every 100 ft (Hazel's proposal)", evenly(f, 100 * FT)),
            ("corners", f"Ramps only at the {len(c)} corners", list(c)),
            ("corners150", "Corners + every 150 ft between them", fill)]


def run(ring, heatmap: Path = HEATMAP, n=N_TURTLES, n_tracks=250):
    f = Fence(ring); woods = woods_xy(f, heatmap)
    T = simulate(f, woods, n); cs = set(f.corners)
    final = np.array([t["path"][t["walk_steps"]] for t in T])
    near_corner = np.array([min(f.gap(x, c) for c in f.corners) * STEP_M <= 15 if f.corners else False for x in final])
    corner_len_share = (len(f.corners) * 31 / f.n) if f.corners else 0  # fence length within 15 m of a corner
    ll = lambda idx: [[round(float(a), 7), round(float(b), 7)] for a, b in zip(*f.to_lonlat(f.xy[np.atleast_1d(idx)]))]
    scen = []
    for key, title, ramps in scenarios(f):
        res = {"key": key, "title": title, "ramps": [int(r) for r in ramps], "n_ramps": len(ramps), "escaped_pct": {}, "exit_step": {}}
        for m in DETERRENT_MULT:
            ex = [exit_step(f, t, ramps, cs, min(t["stop"], int(round(t["walk_steps"] * m)))) for t in T]
            res["escaped_pct"][str(m)] = round(100 * float(np.mean([e >= 0 for e in ex])), 1)
            res["exit_step"][str(m)] = ex[:n_tracks]
        res["per_ramp"] = round(res["escaped_pct"]["1.0"] / max(1, len(ramps)), 2)
        scen.append(res)
    tracks = []
    for t in T[:n_tracks]:
        L = max(1, int(t["lead_m"] // STEP_M)); hd = np.array([math.sin(t["heading"]), math.cos(t["heading"])])
        lead = [t["start"] + hd * t["lead_m"] * k / L for k in range(L)]
        lon, lat = f.to_lonlat(np.array(lead))
        tracks.append({"lead": [[round(float(a), 7), round(float(b), 7)] for a, b in zip(lon, lat)],
                       "fence": [int(x) for x in t["path"][:t["stop"] + 1]], "walk": t["walk_steps"], "kind": t["kind"]})
    return {"version": 2, "turtles": n, "walk_ft": list(WALK_FT), "fence_m": round(f.n * STEP_M),
            "fence": ll(np.arange(f.n)), "corners": [{"fence_idx": c, "lonlat": ll(c)[0], "angle_deg": round(a)} for c, a in zip(f.corners, f.corner_deg)],
            "woods_share": FALL_WOODS_SHARE, "deterrent_mult": list(DETERRENT_MULT),
            "hunker_near_corner_pct": round(100 * float(near_corner.mean()), 1),
            "corner_fence_share_pct": round(100 * corner_len_share, 1),
            "scenarios": scen, "tracks": tracks}


def summary(r) -> str:
    out = [f"{r['turtles']} virtual turtles, {r['walk_ft'][0]}-{r['walk_ft'][1]} ft of fence-walking, {r['fence_m']} m of fence, "
           f"{len(r['corners'])} corners.",
           f"Hunker down within 15 m of a corner: {r['hunker_near_corner_pct']}% of turtles (corners are {r['corner_fence_share_pct']}% of the fence)."]
    for s in r["scenarios"][1:]:
        e = s["escaped_pct"]
        out.append(f"{s['title']}: {s['n_ramps']} ramps -> {e['1.0']}% walk out "
                   f"(deterrent 1.5x: {e['1.5']}%, 2x: {e['2.0']}%), {s['per_ramp']}% per ramp")
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description="F6: fence-exit simulator (v2)")
    ap.add_argument("--site", default=str(SITE)); ap.add_argument("--heatmap", default=str(HEATMAP))
    ap.add_argument("--turtles", type=int, default=N_TURTLES); ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args(argv); a.out.mkdir(parents=True, exist_ok=True)
    r = run(site_ring(a.site), Path(a.heatmap), a.turtles)
    (a.out / "escape.json").write_text(json.dumps(r)); print(summary(r)); print(f"Files in {a.out}")
    return r


if __name__ == "__main__":
    main()
