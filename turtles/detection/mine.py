"""Hard-negative mining: every box the model fires on a survey photo (no turtles there) becomes a negative tile.

    python3 -m turtles.detection.mine <work> <dataset M|F> <eval dir with predictions.json> [--min 0.15]

Then retrain. This is what teaches the model the site's own rocks, clods, pipe ends and shadows.
"""
from __future__ import annotations

import json, random, sys
from pathlib import Path

from PIL import Image

T = 640


def main(work: str, ds: str, ev: str, *opts: str) -> None:
    lo = float(dict(zip(opts, opts[1:])).get("--min", 0.15)); out = Path(work, "datasets", ds); n = 0
    for r in json.load(open(Path(ev, "predictions.json")))["survey"]:
        im = None
        for k, b in enumerate(p for p in r["preds"] if p[4] >= lo):
            im = im or Image.open(r["src"]).convert("RGB"); W, H = im.size; rr = random.Random(f"{r['src']}{k}")
            cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
            x = int(min(max(cx - rr.uniform(0.2, 0.8) * T, 0), W - T)); y = int(min(max(cy - rr.uniform(0.2, 0.8) * T, 0), H - T))
            name = f"hn_{Path(r['src']).stem}_{k}"
            im.crop((x, y, x + T, y + T)).save(out / "images" / "train" / f"{name}.jpg", quality=90)
            (out / "labels" / "train" / f"{name}.txt").write_text(""); n += 1
    print(f"{n} hard-negative tiles added to {out}")


if __name__ == "__main__":
    main(*sys.argv[1:])
