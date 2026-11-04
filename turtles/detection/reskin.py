"""Re-skin the real drone shell: keep the real photo, ground, shadow and blur; replace only the shell's pixels with a
living Eastern box turtle carapace (dark brown with yellow/orange markings) from Tanya's and the GMU top-down photos.

Why: the test shell is sun-bleached bone - chalky white, the same look as the site's white rocks. No living box
turtle looks like that, so a detector trained on it learns "small white blob". Re-skinning keeps every real cue
(size, shape, lighting, camera) except the one that was wrong: color and pattern.

    python3 -m turtles.detection.reskin <work> "<TNUX Turtles Data>" --preview      # side-by-side check sheet
    python3 -m turtles.detection.reskin <work> "<TNUX Turtles Data>" [--variants 5]  # dataset RS + Test B photos
"""
from __future__ import annotations

import json, random, sys
from pathlib import Path

import cv2
import numpy as np

SKINS = ("tanya_Box", "tanya_Neigh", "tanya_TB", "Shell_2026")  # top-down carapace photos (live turtles + patterned shell)
CARAPACE_BGR = np.array([38.0, 62.0, 92.0])  # mean color of a dry living box turtle carapace: dark brown, warm (B, G, R)
ALBEDO = (0.35, 0.6)                          # living shell brightness relative to the bleached bone it replaces


def load_skins(work: str, part: str = "train") -> list[np.ndarray]:
    """RGBA carapace textures, BGR order. part='test': every 5th skin by name, never used for training (Test B);
    part='train': the rest; part='all'."""
    out = []
    names = [p for p in sorted(Path(work, "sprites", "turtle").glob("*.png")) if p.name.startswith(SKINS)]
    for i, p in enumerate(names):
        if part == "all" or (part == "test") == (i % 5 == 4):
            im = cv2.imread(str(p), cv2.IMREAD_UNCHANGED)
            if im is not None and im.shape[2] == 4: out.append(im)
    return out


def shell_mask(crop: np.ndarray, box: tuple[int, int, int, int]) -> np.ndarray:
    """Shell pixels inside box (crop coords): the bright blob if the shell is lit, else the ellipse inscribed in the box."""
    x0, y0, x1, y1 = box; m = np.zeros(crop.shape[:2], np.uint8)
    ell = np.zeros_like(m); cv2.ellipse(ell, ((x0 + x1) // 2, (y0 + y1) // 2), (max(2, (x1 - x0) // 2), max(2, (y1 - y0) // 2)), 0, 0, 360, 255, -1)
    L = cv2.cvtColor(crop, cv2.COLOR_BGR2LAB)[:, :, 0].astype(float)
    ring = cv2.dilate(ell, np.ones((15, 15), np.uint8)) & ~cv2.dilate(ell, np.ones((5, 5), np.uint8))
    bright = ((L > np.median(L[ring > 0]) + 15) & (cv2.dilate(ell, np.ones((5, 5), np.uint8)) > 0)).astype(np.uint8) * 255
    n, lab, st, _ = cv2.connectedComponentsWithStats(bright)
    if n > 1:
        k = 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))
        if st[k, cv2.CC_STAT_AREA] >= max(25, 0.12 * (ell > 0).sum()):   # a lit shell: color only the shell itself
            m = cv2.morphologyEx((lab == k).astype(np.uint8) * 255, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
            return cv2.dilate(m, np.ones((3, 3), np.uint8))
    small = np.zeros_like(m)   # shell in shade: loose hand boxes include ground, so use a smaller centered oval
    cv2.ellipse(small, ((x0 + x1) // 2, (y0 + y1) // 2), (max(2, int((x1 - x0) * 0.33)), max(2, int((y1 - y0) * 0.33))), 0, 0, 360, 255, -1)
    return small


def reskin(img: np.ndarray, box: list[int], skin: np.ndarray, r: random.Random) -> np.ndarray:
    """img (BGR, full photo) with the shell in box re-colored by skin. Box/geometry unchanged."""
    x0, y0, x1, y1 = box; pad = 12
    X0, Y0, X1, Y1 = max(0, x0 - pad), max(0, y0 - pad), min(img.shape[1], x1 + pad), min(img.shape[0], y1 + pad)
    crop = img[Y0:Y1, X0:X1].astype(float); m = shell_mask(img[Y0:Y1, X0:X1], (x0 - X0, y0 - Y0, x1 - X0, y1 - Y0))
    ys, xs = np.nonzero(m)
    if len(xs) < 6: return img
    bx0, by0, bx1, by1 = xs.min(), ys.min(), xs.max() + 1, ys.max() + 1
    s = skin[:, :, :3]; a = skin[:, :, 3]
    M = cv2.getRotationMatrix2D((s.shape[1] / 2, s.shape[0] / 2), r.uniform(0, 360), 1.0)
    s, a = cv2.warpAffine(s, M, s.shape[1::-1], borderMode=cv2.BORDER_REFLECT), cv2.warpAffine(a, M, a.shape[1::-1])
    yy, xx = np.nonzero(a > 128); s = s[yy.min():yy.max() + 1, xx.min():xx.max() + 1]   # tight carapace, rotated
    tex = cv2.resize(s, (bx1 - bx0, by1 - by0), interpolation=cv2.INTER_AREA).astype(float)
    tex *= CARAPACE_BGR / tex.reshape(-1, 3).mean(0)                     # warm brown overall, keeps the skin's own pattern
    tex = cv2.GaussianBlur(tex, (0, 0), r.uniform(0.6, 1.0))              # same softness as the 50 ft photo
    inside = m[by0:by1, bx0:bx1] > 0
    orig = img[Y0:Y1, X0:X1].astype(float)[by0:by1, bx0:bx1].mean(2)      # the real light on this shell, pixel by pixel
    t_l = tex.mean(2)
    # living carapace is much darker than bleached bone: keep the photo's light/shade, scaled down to turtle albedo
    new = np.clip(tex / max(1.0, t_l[inside].mean()) * (orig * r.uniform(*ALBEDO))[:, :, None], 0, 255)
    alpha = cv2.GaussianBlur(m[by0:by1, bx0:bx1].astype(float) / 255, (3, 3), 0.7)[:, :, None]
    crop[by0:by1, bx0:bx1] = crop[by0:by1, bx0:bx1] * (1 - alpha) + new * alpha
    out = img.copy(); out[Y0:Y1, X0:X1] = np.clip(crop, 0, 255).astype(np.uint8); return out


def build(work: str, data: str, *opts: str) -> None:
    """Dataset RS: like R (real shells, no pasting) but each shell photo is re-skinned `--variants` times with training
    skins; the original bleached version is kept too (old turtles fade toward tan). Negatives: R's, linked.
    Test B: TEST photos re-skinned once (fixed seed) with held-out skins -> <work>/test_b/flights/drone_photos/..."""
    import os, shutil
    from PIL import Image
    from turtles.detection.build_dataset import boxes_in, crop, save
    from turtles.detection.build_real import turn
    o = dict(zip(opts, opts[1:])); V, per = int(o.get("--variants", 5)), int(o.get("--per-shell", 15))
    lab = json.load(open(Path(work, "labels.json")))["labels"]; tr, te = load_skins(work, "train"), load_skins(work, "test")
    out, R = Path(work, "datasets", "RS"), Path(work, "datasets", "R")
    if out.exists(): shutil.rmtree(out)
    for s in ("train", "val"): (out / "images" / s).mkdir(parents=True); (out / "labels" / s).mkdir(parents=True)
    n = {"pos": 0, "neg": 0}
    for src, boxes in sorted((k, v) for k, v in lab.items() if v):
        img, r = cv2.imread(str(Path(data, "flights", "drone_photos", src))), random.Random(src)
        if "_TEST_" in src:   # Test B copy: same photo, shells re-skinned with held-out skins, labels unchanged
            b_img = img
            for b in boxes: b_img = reskin(b_img, b, r.choice(te), r)
            dst = Path(work, "test_b", "flights", "drone_photos", src); dst.parent.mkdir(parents=True, exist_ok=True); cv2.imwrite(str(dst), b_img, [cv2.IMWRITE_JPEG_QUALITY, 95])
            continue
        split = "val" if src.startswith("12_spot8") else "train"
        for v in range(V + 1):   # v = 0: original bleached shell; 1..V: living-turtle skins
            im = img
            if v:
                for b in boxes: im = reskin(im, b, r.choice(tr), r)
            pil = Image.fromarray(cv2.cvtColor(im, cv2.COLOR_BGR2RGB))
            for j, b in enumerate(boxes):
                for i in range(per if v else per // 2):
                    t, (x, y) = crop(pil, r, b); t, bx = turn(t, boxes_in(boxes, x, y), r.randrange(4))
                    save(out, split, f"{Path(src).stem}_v{v}_{j}_{i}", t, bx); n["pos"] += 1
        print(f"  {split:5s} {src}", flush=True)
    for d in ("train", "val"):
        for p in (R / "images" / d).glob("*.jpg"):
            if "_real" not in p.name:
                q = out / "images" / d / p.name
                try: os.link(p, q)
                except OSError: shutil.copy2(p, q)
                (out / "labels" / d / (p.stem + ".txt")).write_text(""); n["neg"] += 1
    (out / "data.yaml").write_text(f"path: {out.resolve()}\ntrain: images/train\nval: images/val\nnames:\n  0: turtle\n")
    print(f"RS: {n['pos']} shell tiles (bleached + {V} living-skin versions each), {n['neg']} empty tiles. Test B photos -> {work}/test_b")


def preview(work: str, data: str, *opts: str) -> None:
    lab, skins, r, rows = json.load(open(Path(work, "labels.json")))["labels"], load_skins(work, "all"), random.Random(1), []
    for src, boxes in [(k, v) for k, v in sorted(lab.items()) if v and "_TEST_" not in k][::3][:10]:
        img = cv2.imread(str(Path(data, "flights", "drone_photos", src))); b = boxes[0]
        new = reskin(img, b, r.choice(skins), r); cx, cy = (b[0] + b[2]) // 2, (b[1] + b[3]) // 2
        c = lambda im: cv2.resize(im[cy - 60:cy + 60, cx - 60:cx + 60], (240, 240), interpolation=cv2.INTER_NEAREST)
        rows.append(np.hstack([c(img), np.full((240, 4, 3), 255, np.uint8), c(new)]))
    cv2.imwrite(str(Path(work, "reskin_check.jpg")), np.vstack([np.hstack(rows[i:i + 2]) if i + 1 < len(rows) else np.hstack([rows[i], np.zeros_like(rows[i])]) for i in range(0, len(rows), 2)]))
    print(f"{len(skins)} skins, {len(rows)} previews -> {work}/reskin_check.jpg")


if __name__ == "__main__":
    (preview if "--preview" in sys.argv else build)(*[a for a in sys.argv[1:] if a != "--preview"])
