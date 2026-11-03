"""Cut turtle/shell sprites (RGBA PNG, transparent background) for copy-paste training.

    python3 -m turtles.detection.sprites gmu  "<TNUX Turtles Data>/training_photos" <work>/sprites/gmu
    python3 -m turtles.detection.sprites drone <work>/labels.json <work>/sprites/drone "<TNUX Turtles Data>" [train | train,test]

gmu:   background removal (rembg isnet) on the Oct 16 GMU shoot (live turtles + shell, close-up phone photos).
drone: crops of hand-labeled shells straight out of the drone photos, soft elliptical alpha. These are the
       most realistic sprites (real lighting, real lens, real scale) - TEST-split crops are excluded for model M.
Re-runnable: existing outputs are skipped.
"""
from __future__ import annotations

import json, sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

EXTS = {".jpg", ".jpeg", ".png", ".heic"}


def gmu(src: str, out: str) -> None:
    import cv2, pillow_heif
    from rembg import new_session, remove
    pillow_heif.register_heif_opener()
    Path(out).mkdir(parents=True, exist_ok=True)
    session = new_session("isnet-general-use")
    for p in sorted(q for q in Path(src).rglob("*") if q.suffix.lower() in EXTS):
        o = Path(out, f"{p.parent.name}_{p.stem}.png")
        if o.exists() or Path(str(o) + ".skip").exists(): continue
        im = Image.open(p).convert("RGB"); im.thumbnail((1600, 1600))
        a = np.array(remove(im, session=session, only_mask=True)) > 128
        n, lab, st, _ = cv2.connectedComponentsWithStats(a.astype(np.uint8))
        if n < 2: Path(str(o) + ".skip").touch(); continue
        k = 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA])); x, y, w, h, area = st[k]
        if not 0.005 < area / a.size < 0.6: Path(str(o) + ".skip").touch(); continue  # nothing found, or grabbed the scene
        rgba = np.dstack([np.array(im), (lab == k).astype(np.uint8) * 255])[y:y + h, x:x + w]
        s = Image.fromarray(rgba, "RGBA"); s.thumbnail((256, 256)); s.save(o); print(o.name, flush=True)


def drone(labels: str, out: str, data: str, splits: str = "train,test") -> None:
    Path(out).mkdir(parents=True, exist_ok=True)
    d = json.load(open(labels))
    meta = {it["src"]: it for it in d["items"]}
    for src, boxes in d["labels"].items():
        if meta[src]["split"] not in splits.split(","): continue
        im = None
        for i, (x0, y0, x1, y1) in enumerate(boxes):
            o = Path(out, f"{Path(src).stem}_{i}.png")
            if o.exists(): continue
            im = im or Image.open(Path(data, "flights", "drone_photos", src)).convert("RGB")
            m = max(4, round(0.15 * max(x1 - x0, y1 - y0)))  # a little ground around the shell, faded out
            c = im.crop((x0 - m, y0 - m, x1 + m, y1 + m))
            a = Image.new("L", c.size, 0)
            ImageDraw.Draw(a).ellipse((m * 0.5, m * 0.5, c.width - m * 0.5, c.height - m * 0.5), fill=255)
            c.putalpha(a.filter(ImageFilter.GaussianBlur(m * 0.4))); c.save(o)


if __name__ == "__main__":
    {"gmu": gmu, "drone": drone}[sys.argv[1]](*sys.argv[2:])
