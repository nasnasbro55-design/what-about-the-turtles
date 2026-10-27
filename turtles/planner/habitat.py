"""Turtle-likelihood heat map (F2), built from free USDA NAIP aerial imagery. Naz owns this.

NAIP has a near-infrared band, so NDVI = (NIR - Red) / (NIR + Red) shows vegetation:
trees ~0.5+, grass ~0.2-0.4, bare dirt / roads / roofs < 0.15.
The vegetation layer is also the input to the relocation guide (F1): "nearest habitat".

Setup once:  python3 -m pip install --user rasterio numpy
Run:         python3 -m turtles.planner.habitat --lat 38.80 --lon -77.62 [--site turtles/planner/sites/grayson.geojson]
--site is the cleared construction area, drawn by hand (e.g. on geojson.io). NAIP may predate clearing, so
inside it is treated as bare ground: likelihood there comes only from how close it is to the remaining woods.
Writes to turtles/planner/out/ (git-ignored): ndvi.tif, ndvi_preview.png, heatmap.geojson
"""
from __future__ import annotations

import argparse
import json
import math
import urllib.request
import warnings
from pathlib import Path

import numpy as np

STAC_SEARCH = "https://planetarycomputer.microsoft.com/api/stac/v1/search"   # free, no account needed
SAS_TOKEN = "https://planetarycomputer.microsoft.com/api/sas/v1/token/naip"
OUT = Path(__file__).parent / "out"

CELL_M, BUFFER_M = 10, 300   # grid cell size; area around the site center to map
VEG_LO, VEG_HI = 0.10, 0.50  # NDVI ramp: at or below LO = bare (score 0), at or above HI = full vegetation (1)
VEG_NDVI = 0.30              # a cell at or above this counts as habitat for the edge-distance layer
EDGE_M = 100                 # edge score fades to 0 this far from habitat (turtles leave cover into the site)
W_VEG, W_EDGE = 0.5, 0.5     # judgment calls: start equal, tune with Tanya, say so in the pitch
MIN_SHOW = 0.05              # cells below this are left out of the GeoJSON to keep it small


def bbox_around(lat: float, lon: float, buffer_m: float = BUFFER_M) -> tuple[float, float, float, float]:
    """(west, south, east, north) in degrees, buffer_m around a point."""
    dlat, dlon = buffer_m / 111_320, buffer_m / (111_320 * math.cos(math.radians(lat)))
    return lon - dlon, lat - dlat, lon + dlon, lat + dlat


def find_naip(bbox) -> list[dict]:
    """STAC items from the newest NAIP year that covers the bbox (several tiles if it straddles an edge)."""
    req = urllib.request.Request(STAC_SEARCH, data=json.dumps({"collections": ["naip"], "bbox": list(bbox), "limit": 100}).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        items = json.load(r)["features"]
    if not items:
        raise SystemExit("No NAIP imagery found for that area - check the lat/lon.")
    year = max(i["properties"]["datetime"][:4] for i in items)
    return [i for i in items if i["properties"]["datetime"][:4] == year]


def read_ndvi(items: list[dict], bbox):
    """Read only the bbox window from the cloud (no full-tile download). Returns (ndvi, transform, crs, year)."""
    import rasterio
    from rasterio.merge import merge
    from rasterio.warp import transform_bounds
    with urllib.request.urlopen(SAS_TOKEN, timeout=30) as r:
        token = json.load(r)["token"]
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR"):
        srcs = [rasterio.open(f"{i['assets']['image']['href']}?{token}") for i in items]
        arr, transform = merge(srcs, bounds=transform_bounds("EPSG:4326", srcs[0].crs, *bbox), indexes=[1, 4])  # red, NIR
        crs = srcs[0].crs
        for s in srcs:
            s.close()
    red, nir = arr.astype("float32")
    return (nir - red) / np.maximum(nir + red, 1), transform, crs, items[0]["properties"]["datetime"][:4]


def to_cells(ndvi: np.ndarray, transform, cell_m: float = CELL_M):
    """Average the ~0.6 m NDVI pixels into cell_m grid cells. Returns (cells, cell_transform)."""
    from rasterio.transform import Affine
    k = max(1, round(cell_m / transform.a))
    h, w = ndvi.shape[0] // k * k, ndvi.shape[1] // k * k
    return ndvi[:h, :w].reshape(h // k, k, w // k, k).mean(axis=(1, 3)), transform * Affine.scale(k)


def edge_distance_m(habitat: np.ndarray, cell_m: float, max_m: float) -> np.ndarray:
    """Distance from each cell to the nearest habitat cell (8-neighbour steps), inf beyond max_m."""
    dist, front = np.full(habitat.shape, np.inf), habitat.copy()
    for step in range(int(max_m // cell_m) + 1):
        dist[front & np.isinf(dist)] = step * cell_m
        p = np.pad(front, 1)
        front = (p[1:-1, 1:-1] | p[:-2, 1:-1] | p[2:, 1:-1] | p[1:-1, :-2] | p[1:-1, 2:]
                 | p[:-2, :-2] | p[:-2, 2:] | p[2:, :-2] | p[2:, 2:])
    return dist


def site_mask(site_geojson: str | Path, shape, cell_transform, crs) -> np.ndarray:
    """True for grid cells whose center falls inside the site polygon(s) (Polygon / MultiPolygon / Feature(Collection))."""
    from rasterio.warp import transform as reproject
    g = json.loads(Path(site_geojson).read_text())
    geoms = [f["geometry"] for f in g["features"]] if g["type"] == "FeatureCollection" else [g.get("geometry", g)]
    rings = [p[0] for x in geoms for p in ([x["coordinates"]] if x["type"] == "Polygon" else x["coordinates"])]
    rows, cols = np.mgrid[0:shape[0], 0:shape[1]]
    px, py = (np.asarray(v) for v in cell_transform * (cols.ravel() + 0.5, rows.ravel() + 0.5))
    inside = np.zeros(px.size, bool)
    for ring in rings:
        rx, ry = (np.asarray(v) for v in reproject("EPSG:4326", crs, [q[0] for q in ring], [q[1] for q in ring]))
        hit = np.zeros(px.size, bool)
        for x1, y1, x2, y2 in zip(rx, ry, np.roll(rx, -1), np.roll(ry, -1)):  # ray casting
            hit ^= ((y1 > py) != (y2 > py)) & (px < (x2 - x1) * (py - y1) / (y2 - y1 + 1e-12) + x1)
        inside |= hit
    return inside.reshape(shape)


def likelihood(cells: np.ndarray, cell_m: float = CELL_M, cleared: np.ndarray | None = None):
    """Per-cell turtle likelihood 0-1, plus the layers behind it (for the reasons).
    cleared: cells inside the construction site - no longer habitat, whatever the (older) imagery says."""
    cleared = np.zeros(cells.shape, bool) if cleared is None else cleared
    veg = np.where(cleared, 0, np.clip((cells - VEG_LO) / (VEG_HI - VEG_LO), 0, 1))
    dist = edge_distance_m((cells >= VEG_NDVI) & ~cleared, cell_m, EDGE_M)
    edge = np.where(np.isinf(dist), 0, 1 - dist / EDGE_M)
    raw = W_VEG * veg + W_EDGE * edge
    return raw / raw.max() if raw.max() > 0 else raw, veg, dist


def heatmap_geojson(cells: np.ndarray, cell_transform, crs, site_id: str, year: str = "",
                    cleared: np.ndarray | None = None) -> dict:
    """GeoJSON FeatureCollection of grid cells with likelihood + reasons (same shape as mock/heatmap.geojson)."""
    from rasterio.warp import transform as reproject
    cleared = np.zeros(cells.shape, bool) if cleared is None else cleared
    lik, veg, dist = likelihood(cells, abs(cell_transform.a), cleared)
    rows, cols = np.mgrid[0:cells.shape[0] + 1, 0:cells.shape[1] + 1]
    xs, ys = cell_transform * (cols.ravel(), rows.ravel())
    lon, lat = (np.round(np.array(v).reshape(rows.shape), 7) for v in reproject(crs, "EPSG:4326", xs, ys))
    feats = []
    for r, c in zip(*np.nonzero(lik >= MIN_SHOW)):
        ring = [[lon[r + a, c + b], lat[r + a, c + b]] for a, b in ((0, 0), (0, 1), (1, 1), (1, 0), (0, 0))]
        why = (([f"Cleared site, {dist[r, c]:.0f} m from the woods: turtles wander in from the edge"] if np.isfinite(dist[r, c])
                else ["Cleared site, far from cover"]) if cleared[r, c] else
               [f"Vegetation (NDVI {cells[r, c]:.2f}): likely turtle habitat"] if veg[r, c] >= 0.5 else
               [f"{dist[r, c]:.0f} m from vegetation: turtles leaving cover cross here"] if np.isfinite(dist[r, c]) and dist[r, c] > 0 else
               [f"Edge of vegetation (NDVI {cells[r, c]:.2f})"])
        feats.append({"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[[float(x), float(y)] for x, y in ring]]},
                      "properties": {"likelihood": round(float(lik[r, c]), 3), "reasons": why, "on_site": bool(cleared[r, c]),
                                     "ndvi": round(float(cells[r, c]), 3)}})
    return {"type": "FeatureCollection", "name": f"{site_id} turtle likelihood (NAIP {year} NDVI, {CELL_M} m grid)", "features": feats}


def save(ndvi, transform, crs, fc, out: Path = OUT) -> None:
    import rasterio
    out.mkdir(parents=True, exist_ok=True)
    with rasterio.open(out / "ndvi.tif", "w", driver="GTiff", height=ndvi.shape[0], width=ndvi.shape[1], count=1,
                       dtype="float32", crs=crs, transform=transform, compress="deflate") as f:
        f.write(ndvi, 1)
    with warnings.catch_warnings():  # PNG has no georeferencing; that's fine for a preview
        warnings.simplefilter("ignore")
        with rasterio.open(out / "ndvi_preview.png", "w", driver="PNG", height=ndvi.shape[0], width=ndvi.shape[1],
                           count=1, dtype="uint8") as f:
            lo, hi = np.percentile(ndvi, (2, 98))  # stretch contrast so woods vs. dirt is easy to see
            f.write((np.clip((ndvi - lo) / max(hi - lo, 1e-6), 0, 1) * 255).astype("uint8"), 1)  # brighter = greener
    (out / "heatmap.geojson").write_text(json.dumps(fc) + "\n")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Turtle-likelihood heat map from NAIP NDVI")
    ap.add_argument("--lat", type=float, required=True)
    ap.add_argument("--lon", type=float, required=True)
    ap.add_argument("--buffer", type=float, default=BUFFER_M, help="meters around the point (default 300)")
    ap.add_argument("--site-id", default="grayson")
    ap.add_argument("--site", help="GeoJSON outline of the cleared construction area")
    a = ap.parse_args()
    bbox = bbox_around(a.lat, a.lon, a.buffer)
    items = find_naip(bbox)
    print(f"NAIP {items[0]['properties']['datetime'][:4]}: {len(items)} tile(s): {', '.join(i['id'] for i in items)}")
    ndvi, transform, crs, year = read_ndvi(items, bbox)
    cells, cell_tr = to_cells(ndvi, transform)
    cleared = site_mask(a.site, cells.shape, cell_tr, crs) if a.site else None
    fc = heatmap_geojson(cells, cell_tr, crs, a.site_id, year, cleared)
    if cleared is not None:
        print(f"Site outline: {cleared.sum()} cells ({cleared.sum() * cell_tr.a ** 2 / 4047:.0f} acres) treated as cleared")
    save(ndvi, transform, crs, fc)
    lik = [f["properties"]["likelihood"] for f in fc["features"]]
    print(f"NDVI {ndvi.shape[1]}x{ndvi.shape[0]} px at {transform.a:.2f} m; {cells.size} cells, {len(lik)} shown, "
          f"{sum(v >= 0.7 for v in lik)} high (>= 0.7). Files in {OUT}")
