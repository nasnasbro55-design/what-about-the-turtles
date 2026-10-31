"""F1 relocation guide: after the drone finds a turtle, tell the responder where to carry it and why.

Rules are Tanya Finch's (email of Oct 27, 2026), applied to the F2 heat map's NDVI cells:
  * Target the closest suitable habitat off site, usually just over the fence. No fixed distance cap.
  * Most turtles walk along the fence: if it was heading off site, keep that direction; if it was heading
    deeper into the site, ignore the heading. Unknown heading: best nearby habitat.
  * Good: dense cover (trees, brush, leaf litter). Acceptable: open vegetation. Avoid roads, other construction,
    and (for box turtles) putting them in water.
  * Snapping turtles / any turtle that can't close its shell: beside water, not in it.
  * Best of all (Olivia): if it's nearly out and heading that way, let it walk out on its own.

Run:  python3 -m turtles.planner.relocation --lat 38.7935 --lon -77.6470 [--heading 270] [--species snapping]
      python3 -m turtles.planner.relocation --alerts alerts.json --id <alert_id>
Needs turtles/planner/out/heatmap.geojson from habitat.py (rerun it once so cells carry "ndvi").
Writes out/relocation.geojson (turtle, target and arrow) to check on geojson.io.
"""
from __future__ import annotations

import argparse, json, math
from dataclasses import asdict
from pathlib import Path

import numpy as np

from turtles.contracts import Alert, RelocationSuggestion, load
from turtles.geo import M_PER_DEG_LAT

HEATMAP = Path(__file__).parent / "out" / "heatmap.geojson"
COVER_NDVI, HABITAT_NDVI = 0.45, 0.30  # summer values; capped per scene below (leaf-off imagery reads much lower)
COVER_PCT, HABITAT_PCT = 75, 50         # ...at the 75th / 50th percentile of the land around the site
BARE_NDVI, WATER_NDVI = 0.12, 0.0       # roads, roofs, bare dirt / open water: low in any season
OPEN_PENALTY = 1 / 0.6  # open vegetation counts as 1.7x farther than dense cover (judgment call)
ROAD_M, ROAD_PENALTY = 20, 2.0  # habitat this close to bare ground (road, roof, other construction) counts 2x farther
BESIDE_WATER_M = 15             # aquatic turtles: a dry cell this close to water
HEADING_CONE_DEG, HEADING_SLACK = 60, 1.5  # follow its heading if habitat that way is at most 1.5x the best option
WALK_OUT_M = 15
ASPECT = 10.0  # grid cell size (m) for neighbour lookups (matches habitat.CELL_M)
COMPASS = ["north", "northeast", "east", "southeast", "south", "southwest", "west", "northwest"]
AQUATIC = {"snapping", "aquatic"}


def load_cells(path: Path = HEATMAP) -> dict:
    feats = json.loads(Path(path).read_text())["features"]
    if feats and "ndvi" not in feats[0]["properties"]:
        raise SystemExit("Heat map cells have no 'ndvi': rerun python3 -m turtles.planner.habitat ... --site ...")
    ring = np.array([f["geometry"]["coordinates"][0][:4] for f in feats])  # (n, 4, 2) lon/lat
    lon, lat = ring[..., 0].mean(1), ring[..., 1].mean(1)
    ndvi, on = np.array([f["properties"]["ndvi"] for f in feats]), np.array([f["properties"].get("on_site", False) for f in feats])
    off = ndvi[~on & (ndvi >= WATER_NDVI)]
    return {"lat": lat, "lon": lon, "ndvi": ndvi, "on_site": on,
            "cover": min(COVER_NDVI, float(np.percentile(off, COVER_PCT))) if off.size else COVER_NDVI,
            "habitat": min(HABITAT_NDVI, float(np.percentile(off, HABITAT_PCT))) if off.size else HABITAT_NDVI}


def _near(mask, x, y, r_m) -> np.ndarray:
    """True where a cell has a `mask` cell within about r_m (grid-key lookup, fast for thousands of cells)."""
    keys = {(int(round(a / ASPECT)), int(round(b / ASPECT))) for a, b in zip(x[mask], y[mask])}
    r = int(math.ceil(r_m / ASPECT))
    offs = [(i, j) for i in range(-r, r + 1) for j in range(-r, r + 1) if (i * i + j * j) * ASPECT ** 2 <= r_m ** 2]
    return np.array([any((int(round(a / ASPECT)) + i, int(round(b / ASPECT)) + j) in keys for i, j in offs)
                     for a, b in zip(x, y)], bool) if keys else np.zeros(x.size, bool)


def compass(bearing: float) -> str:
    return COMPASS[int((bearing + 22.5) % 360 // 45)]


def suggest(alert_id: str, lat: float, lon: float, cells: dict, heading_deg: float | None = None,
            species: str = "box", max_m: float = 600) -> RelocationSuggestion:
    kl = M_PER_DEG_LAT * math.cos(math.radians(lat))
    x, y = (cells["lon"] - lon) * kl, (cells["lat"] - lat) * M_PER_DEG_LAT
    keep = np.hypot(x, y) <= max_m + ROAD_M
    x, y, ndvi, on = x[keep], y[keep], cells["ndvi"][keep], cells["on_site"][keep]
    cover_t, hab_t = cells.get("cover", COVER_NDVI), cells.get("habitat", HABITAT_NDVI)
    d, brg = np.hypot(x, y), (np.degrees(np.arctan2(x, y)) + 360) % 360
    water = ndvi < WATER_NDVI
    bare = ~on & ~water & (ndvi < BARE_NDVI)
    aquatic = species.lower() in AQUATIC
    if aquatic:
        cand, cost = ~on & ~water & _near(water, x, y, BESIDE_WATER_M), d.copy()
    else:
        cand = ~on & (ndvi >= hab_t)
        cost = d * np.where(ndvi >= cover_t, 1.0, OPEN_PENALTY)
    road = _near(bare, x, y, ROAD_M)
    cost = np.where(road, cost * ROAD_PENALTY, cost)
    cand &= d <= max_m
    handling = ("Snapping turtles are defensive on land: keep hands away from the head and call Tanya if unsure."
                if aquatic else "Support the bottom of the shell (hold it like a hamburger) and keep it upright.")
    here = int(np.argmin(d))
    if d[here] <= ASPECT and not on[here] and (ndvi[here] >= hab_t or aquatic and _near(water, x, y, BESIDE_WATER_M)[here]):
        return RelocationSuggestion(alert_id, lat, lon, 0.0, 0.0, [
            "Already off site in habitat: leave it where it is.", "Check the silt fence nearby so it can't wander back in."])
    if not cand.any():
        return RelocationSuggestion(alert_id, lat, lon, 0.0, 0.0, [
            f"No {'water' if aquatic else 'habitat'} mapped within {max_m:.0f} m: hold the turtle safely and call Tanya.", handling])
    idx = np.flatnonzero(cand)
    best = idx[np.argmin(cost[idx])]
    why_heading = None
    if heading_deg is not None:
        diff = np.abs((brg[idx] - heading_deg + 180) % 360 - 180)
        cone = idx[diff <= HEADING_CONE_DEG]
        if cone.size and cost[cone].min() <= HEADING_SLACK * cost[best]:
            best, why_heading = cone[np.argmin(cost[cone])], f"Same direction it was walking ({compass(heading_deg)})."
        else:
            why_heading = (f"It was heading {compass(heading_deg)}, deeper into the site or away from habitat, "
                           "so take it to the nearest good edge instead.")
    dist, b = float(d[best]), float(brg[best])
    what = ("beside the water (not in it)" if aquatic else
            "dense cover (trees, brush or leaf litter)" if ndvi[best] >= cover_t else
            "open vegetation (the best cover close by)")
    reasons = [f"Carry it {dist:.0f} m {compass(b)} to {what}."]
    if dist <= WALK_OUT_M and not aquatic:
        reasons.append("It's nearly out: if it's already heading this way, give it room to walk off on its own.")
    if why_heading:
        reasons.append(why_heading)
    reasons.append("Close to a road or bare ground: set it down on the far side of the cover, away from vehicles."
                   if road[best] else "Away from roads and other construction.")
    reasons.append(handling)
    return RelocationSuggestion(alert_id, round(float(cells["lat"][keep][best]), 7), round(float(cells["lon"][keep][best]), 7),
                                round(dist, 1), round(b, 1), reasons)


def to_geojson(s: RelocationSuggestion, lat: float, lon: float) -> dict:
    pt = lambda la, lo, name: {"type": "Feature", "properties": {"name": name}, "geometry": {"type": "Point", "coordinates": [lo, la]}}
    return {"type": "FeatureCollection", "features": [
        pt(lat, lon, "turtle"), pt(s.target_lat, s.target_lon, "move here"),
        {"type": "Feature", "properties": {"name": s.reasons[0]},
         "geometry": {"type": "LineString", "coordinates": [[lon, lat], [s.target_lon, s.target_lat]]}}]}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="F1: where to move a turtle")
    ap.add_argument("--lat", type=float); ap.add_argument("--lon", type=float)
    ap.add_argument("--alerts"); ap.add_argument("--id")
    ap.add_argument("--heading", type=float, help="direction it was walking, degrees from north")
    ap.add_argument("--species", default="box", help="box (default), snapping, aquatic")
    ap.add_argument("--heatmap", default=str(HEATMAP))
    ap.add_argument("--points", help="GeoJSON of turtle points (batch mode): writes --out with one suggestion per point")
    ap.add_argument("--out", help="batch output JSON (used by pitch/voice_assistant.html)")
    a = ap.parse_args()
    if a.points:
        cells = load_cells(a.heatmap); pack = []
        for i, f in enumerate(json.loads(Path(a.points).read_text())["features"]):
            lon, lat = f["geometry"]["coordinates"][:2]; pr = f.get("properties", {})
            label = pr.get("name") or (f"Spot {pr['spot']}: {pr['ground']}" if "spot" in pr else f"Pin {i + 1}")
            sp = "snapping" if "snap" in str(pr.get("note", "")).lower() else a.species
            s = suggest(str(pr.get("alert_id", f"pin-{i + 1}")), lat, lon, cells, a.heading, sp)
            aq = suggest(s.alert_id, lat, lon, cells, a.heading, "snapping")
            pack.append({"alert_id": s.alert_id, "label": label, "lat": lat, "lon": lon, "suggestion": asdict(s),
                         "suggestion_snapping": asdict(aq)})
        out = Path(a.out or Path(a.heatmap).parent / "relocations.json"); out.write_text(json.dumps(pack, indent=1))
        print(f"{len(pack)} suggestions -> {out}"); raise SystemExit
    if a.alerts:
        al = next(x for x in load(Alert, a.alerts) if x.alert_id == a.id)
        aid, lat, lon = al.alert_id, al.lat, al.lon
        if "snap" in al.note.lower(): a.species = "snapping"
    else:
        aid, lat, lon = "manual", a.lat, a.lon
    s = suggest(aid, lat, lon, load_cells(a.heatmap), a.heading, a.species)
    print(json.dumps(asdict(s), indent=2))
    out = Path(a.heatmap).parent / "relocation.geojson"
    out.write_text(json.dumps(to_geojson(s, lat, lon)) + "\n")
    print(f"Map: {out}")
