"""Test D - independent living-turtle simulation (protocol: <work>/TEST_D_PROTOCOL.md, fixed before it was built).

Photos of real living box turtles the final model never trained on (GMU live-turtle cut-outs, Naz's silt-fence
turtle, Tanya's field turtles; chosen by eye before scoring -> <work>/test_d/selection.json) pasted once each into
survey leg 3 photos (straight-down ~50 ft, never trained on). Same paste as Test C (13 cm +-15%, random rotation,
NNW sun shadow); the turtle keeps its own colors, only a global brightness match to the photo.
Placement (v2, after Naz's review of v1): only on ground a turtle could be standing on - bare soil, mud, gravel,
rock, sparse low ground. ground_ok() rejects grass, man-made colors, dark/bright flat areas and straight edges;
then every placement is checked by eye up close and bad spots go in rejected_spots.json (next spot is used);
a photo that fails the eye check 3 times is dropped (no honest ground in it).
All of this is done BEFORE any detector runs on Test D. Not covered: turtles partly hidden in grass.

    python3 -m turtles.detection.test_d <work> "<TNUX Turtles Data>"          # -> <work>/test_d (photos + labels.json + review sheets)
    python3 -m turtles.detection.evaluate <work> <work>/test_d <weights> --splits survey --spots 03_survey_part3 --labels <work>/test_d/labels.json --no-survey
"""
from __future__ import annotations

import json, random, sys
from pathlib import Path

import cv2
import numpy as np

from turtles.backend.ingest import frame_from_photo
from turtles.detection.test_c import place


def sprite(p: Path, img: np.ndarray) -> np.ndarray:
    """Cut-out with its brightness scaled toward this photo's mean (clipped to 0.75-1.25x). No color change."""
    t = cv2.imread(str(p), cv2.IMREAD_UNCHANGED); a = t[:, :, 3] > 128
    L = lambda im: cv2.cvtColor(im, cv2.COLOR_BGR2LAB)[:, :, 0].astype(float)
    k = np.clip(L(cv2.resize(img, None, fx=0.1, fy=0.1)).mean() / max(1.0, L(t[:, :, :3])[a].mean()), 0.75, 1.25)
    t[:, :, :3] = np.clip(t[:, :, :3].astype(float) * k, 0, 255).astype(np.uint8); return t


def ground_ok(img: np.ndarray, cx: float, cy: float, r: int = 60) -> str | None:
    """Why this spot is NOT plausible ground for a walking turtle, or None if it is. Checks a 2r patch:
    green vegetation (a pasted turtle would float on top of grass), saturated man-made colors (containers, cones,
    blue pipe), large dark or bright flat areas (black pipe, fence fabric, white containers), long straight edges."""
    x, y = int(cx), int(cy); pt = img[y - r:y + r, x - r:x + r]; b, g, rd = [pt[:, :, i].astype(int) for i in range(3)]
    hsv = cv2.cvtColor(pt, cv2.COLOR_BGR2HSV)
    if ((2 * g - rd - b) > 25).mean() > 0.08: return "green vegetation"
    if ((hsv[:, :, 1] > 140) & (hsv[:, :, 2] > 90)).mean() > 0.03: return "saturated man-made color"
    if (hsv[:, :, 2] < 40).mean() > 0.4: return "large dark flat area"
    if (hsv[:, :, 2] > 225).mean() > 0.15: return "large bright flat area"
    ln = cv2.HoughLinesP(cv2.Canny(cv2.cvtColor(pt, cv2.COLOR_BGR2GRAY), 60, 160), 1, np.pi / 180, 60, minLineLength=int(1.4 * r), maxLineGap=4)
    return "long straight edge" if ln is not None else None


def main(work: str, data: str) -> None:
    out = Path(work, "test_d"); keep = json.load(open(out / "selection.json"))["keep"]
    rej = json.load(open(out / "rejected_spots.json")) if (out / "rejected_spots.json").exists() else {}   # by-eye rejections: {photo: [try numbers]}
    lf = out / "labels.json"; d = json.load(open(lf)) if lf.exists() else {"labels": {}, "sprite": {}, "try": {}}
    for p in sorted(Path(data, "flights", "drone_photos").glob("03_survey_part3*/*_V.JPG")):
        src = f"{p.parent.name}/{p.name}"
        if src in d["labels"] and d["try"][src] not in rej.get(src, []): continue
        if len(rej.get(src, [])) >= 3: d["labels"].pop(src, None); d["sprite"].pop(src, None); d["try"].pop(src, None); continue   # failed the eye check 3 times: mostly man-made, dropped
        f = frame_from_photo(p, p.parent, "grayson", "D")
        if f is None or not 13.4 <= f.alt_m <= 17.1: continue                # straight-down ~50 ft photos only
        r, img = random.Random("D" + p.name), cv2.imread(str(p))              # per-photo seed: same result every run
        name = keep[r.randrange(len(keep))]
        spots = [(r.uniform(250, f.width_px - 250), r.uniform(250, f.height_px - 250)) for _ in range(60)]
        k = next((i for i, (x, y) in enumerate(spots) if i not in rej.get(src, []) and ground_ok(img, x, y) is None), None)
        d["labels"].pop(src, None); d["sprite"].pop(src, None); d["try"].pop(src, None)
        if k is None: print(src, "no plausible ground: photo not used", flush=True); json.dump(d, open(lf, "w"), indent=0); continue
        box, _ = place(img, f, sprite(Path(work, "sprites", "turtle", name), img), *spots[k], r)
        d["labels"][src], d["sprite"][src], d["try"][src] = [box], name, k
        dst = out / "flights" / "drone_photos" / src; dst.parent.mkdir(parents=True, exist_ok=True); cv2.imwrite(str(dst), img, [cv2.IMWRITE_JPEG_QUALITY, 95])
        d["protocol"] = __doc__; json.dump(d, open(lf, "w"), indent=0); print(src, box, "try", k, name[:24], flush=True)
    json.dump(d, open(lf, "w"), indent=0)
    print(f"Test D: {len(d['labels'])} leg-3 photos with one living turtle -> {out}")


if __name__ == "__main__":
    main(*sys.argv[1:])
