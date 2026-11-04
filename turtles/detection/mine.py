"""Hard-negative mining: run the model on survey photos (no turtles there); every box it fires becomes a negative tile.

    python3 -m turtles.detection.mine <work> "<TNUX Turtles Data>" <dataset M|F> <weights.pt> [--n 400] [--min 0.15]

Never mines survey leg 3 for model M: that leg is the untouched false-alarm test (evaluate.HOLDOUT_SURVEY).
Then retrain (continue from these weights). This teaches the model the site's own rocks, clods, pipe ends and shadows.
"""
from __future__ import annotations

import csv, os, random, sys
from pathlib import Path

from PIL import Image

from turtles.detection.evaluate import HOLDOUT_SURVEY, local

T = 640


def main(work: str, data: str, ds: str, weights: str, *opts: str) -> None:
    o = dict(zip(opts, opts[1:])); lo, n = float(o.get("--min", 0.15)), int(o.get("--n", 400))
    os.environ["AERO_WEIGHTS"] = weights
    from turtles.detection import detector
    sv = [local(f, data) for f in csv.DictReader(open(Path(work, "frames.csv"))) if f["split"] == "survey" and not (ds == "M" and f["folder"].startswith(HOLDOUT_SURVEY))]
    sv = sv[:: max(1, len(sv) // n)][:n]; out = Path(work, "datasets", ds); added = 0
    for i, path in enumerate(sv, 1):
        bs = [b for b in detector.boxes(path, conf=lo)]
        if not bs: continue
        im = Image.open(path).convert("RGB"); W, H = im.size
        for k, b in enumerate(bs):
            rr = random.Random(f"{path}{k}"); cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
            x = int(min(max(cx - rr.uniform(0.2, 0.8) * T, 0), W - T)); y = int(min(max(cy - rr.uniform(0.2, 0.8) * T, 0), H - T))
            name = f"hn_{Path(path).stem}_{k}"
            im.crop((x, y, x + T, y + T)).save(out / "images" / "train" / f"{name}.jpg", quality=90)
            (out / "labels" / "train" / f"{name}.txt").write_text(""); added += 1
        print(f"[{i}/{len(sv)}] {Path(path).name}: {len(bs)} false alarm(s)", flush=True)
    for c in (out / "labels").glob("*.cache"): c.unlink()
    print(f"{added} hard-negative tiles added to {out}")


if __name__ == "__main__":
    main(*sys.argv[1:])
