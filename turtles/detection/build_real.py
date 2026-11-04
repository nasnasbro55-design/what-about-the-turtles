"""Dataset R: real shells only, no pasted sprites.

Why: model M (95% of its positives were pasted sprites) scores 0.84-0.87 on pasted shells and 0.00 on real shells,
even on tiles it trained on. It learned the look of pasting, not of a shell. R trains on what a flight actually sees.

    python3 -m turtles.detection.build_real <work> "<TNUX Turtles Data>" [--per-shell 60] [--neg 3000] [--val-spot 12_spot8]
    python3 -m turtles.detection.train <work> R --name r_v1 --hours 7

Positives: every hand-labeled shell outside the TEST spots, per_shell crops each (shell anywhere in the tile), each
  turned by a random multiple of 90 deg (valid from the air; training adds flips, color and scale jitter on top).
Negatives: 6 shell-free crops from each shell photo's own scene (that rut / mud / pipe is not a turtle) + `neg` real
  survey-ground tiles reused from datasets/M (M never used survey leg 3, so the false-alarm test stays clean).
Val: every tile from --val-spot (a whole spot the model never trains on) + 10% of the negatives.
TEST spots (rut, half buried, riprap) are never read: they stay the held-out test for evaluate.py.
"""
from __future__ import annotations

import json, os, random, shutil, sys
from pathlib import Path

from PIL import Image

from turtles.detection.build_dataset import T, boxes_in, crop, save

ROT = [None, Image.Transpose.ROTATE_90, Image.Transpose.ROTATE_180, Image.Transpose.ROTATE_270]


def turn(t: Image.Image, boxes: list, k: int) -> tuple[Image.Image, list]:
    """Rotate a T x T tile counter-clockwise by k * 90 deg, boxes with it."""
    for _ in range(k):
        t, boxes = t.transpose(ROT[1]), [[b[1], T - b[2], b[3], T - b[0]] for b in boxes]
    return t, boxes


def link(src: Path, dst: Path) -> None:
    try: os.link(src, dst)
    except OSError: shutil.copy2(src, dst)


def main(work: str, data: str, *opts: str) -> None:
    o = dict(zip(opts, opts[1:])); per, n_neg, val_spot = int(o.get("--per-shell", 60)), int(o.get("--neg", 3000)), o.get("--val-spot", "12_spot8")
    out = Path(work, "datasets", "R")
    if out.exists(): shutil.rmtree(out)
    for s in ("train", "val"): (out / "images" / s).mkdir(parents=True); (out / "labels" / s).mkdir(parents=True)
    lab = json.load(open(Path(work, "labels.json")))["labels"]
    count = {"train": [0, 0], "val": [0, 0]}
    shells = {k: v for k, v in lab.items() if v and "_TEST_" not in k}
    for src, boxes in sorted(shells.items()):
        split, name, r = "val" if src.startswith(val_spot) else "train", Path(src).stem, random.Random(src)
        im = Image.open(Path(data, "flights", "drone_photos", src)).convert("RGB")
        for j, b in enumerate(boxes):
            for i in range(per):
                t, (x, y) = crop(im, r, b); t, bx = turn(t, boxes_in(boxes, x, y), r.randrange(4))
                save(out, split, f"{name}_real{j}_{i}", t, bx); count[split][0] += 1
        for i in range(6):
            for _ in range(30):
                t, (x, y) = crop(im, r)
                if not boxes_in(boxes, x, y): save(out, split, f"{name}_scene{i}", turn(t, [], r.randrange(4))[0], []); count[split][1] += 1; break
        print(f"  {split:5s} {src}: {len(boxes)} shell(s)", flush=True)
    m = Path(work, "datasets", "M", "images", "train")
    negs = sorted(p for p in m.glob("*_neg*.jpg"))
    for k, p in enumerate(random.Random(7).sample(negs, min(n_neg, len(negs)))):
        split = "val" if k % 10 == 0 else "train"
        link(p, out / "images" / split / p.name); (out / "labels" / split / (p.stem + ".txt")).write_text(""); count[split][1] += 1
    (out / "data.yaml").write_text(f"path: {out.resolve()}\ntrain: images/train\nval: images/val\nnames:\n  0: turtle\n")
    for s, (pos, neg) in count.items(): print(f"{s}: {pos} real-shell tiles, {neg} empty tiles")
    print(f"-> {out}   next: python3 -m turtles.detection.train {work} R --name r_v1 --hours 7")


if __name__ == "__main__":
    main(*sys.argv[1:])
