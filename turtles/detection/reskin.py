"""Re-skin the real drone shell as a living Eastern box turtle - only the shell's own pixels change.

Why (Naz's finding): the test shell is sun-bleached bone, chalky white like the site's white rocks. No living box
turtle looks like that, so a detector trained on it learns "small white blob".

How, per labeled shell:
  1. Trace the shell's exact outline (GrabCut seeded by the bright bleached core). If the outline can't be traced
     cleanly (deep shade), the shell is left as it is - never a guessed circle.
  2. Take a real carapace photo (Naz's, Tanya's, GMU shoot), rotate + stretch it so its outline matches the traced one.
  3. Exposure: the yellow markings come out about as bright as the soil around the shell, the dark scutes darker, and
     the real shell's own sun/shade side is kept. Pattern contrast is preserved; nothing outside the outline changes.
Models trained on this also see every image shadow-lifted first (detector.lift_shadows) - same at detection time.

    python3 -m turtles.detection.reskin <work> "<TNUX Turtles Data>" --preview      # check sheet: original | lifted re-skin
    python3 -m turtles.detection.reskin <work> "<TNUX Turtles Data>" [--variants 5]  # dataset RS + Test B photos
"""
from __future__ import annotations

import json, random, sys
from pathlib import Path

import cv2
import numpy as np

SKINS = ("tanya_Box", "tanya_Neigh", "tanya_TB", "Shell_2026")  # Naz's picks: Tanya's top shells + the GMU shell, natural colors
WARM = np.array([0.62, 0.9, 1.0])   # B:G:R balance of a dry box turtle carapace (warm brown/yellow, not blue)
TRIM_TOP = {"tanya_Box_turtle_top_shell_1is-1k.png": 0.14}   # fingers holding the shell at the top of the photo


def load_skins(work: str, part: str = "train") -> list[np.ndarray]:
    """RGBA carapaces (BGR), edges trimmed. part='test': every 5th by name - never used in training (Test B)."""
    out, names = [], [p for p in sorted(Path(work, "sprites", "turtle").glob("*.png")) if p.name.startswith(SKINS)]
    for i, p in enumerate(names):
        if part == "all" or (part == "test") == (i % 5 == 4):
            im = cv2.imread(str(p), cv2.IMREAD_UNCHANGED)
            if im is None or im.shape[2] != 4: continue
            a = cv2.erode((im[:, :, 3] > 128).astype(np.uint8), np.ones((5, 5), np.uint8))   # drop ragged cut-out edges
            n, lab, st, _ = cv2.connectedComponentsWithStats(a)
            if n < 2: continue
            im[:, :, 3] = (lab == 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))).astype(np.uint8) * 255
            # white balance only (pattern untouched): wet shells carry a blue sky cast; shift the average to warm brown
            px = im[:, :, :3][im[:, :, 3] > 0].astype(float).mean(0)
            im[:, :, :3] = np.clip(im[:, :, :3].astype(float) * (WARM / WARM.mean()) * (px.mean() / np.maximum(px, 1)), 0, 255).astype(np.uint8)
            if p.name in TRIM_TOP:
                ys = np.nonzero(im[:, :, 3])[0]; cut = int(ys.min() + TRIM_TOP[p.name] * (ys.max() - ys.min())); im[:cut, :, 3] = 0
            out.append(im)
    return out


def shell_mask(crop: np.ndarray, box: tuple[int, int, int, int]) -> np.ndarray | None:
    """Full shell outline inside box (crop coords), or None if no shell can be found.
    1. Core: the bleached shell is the brightest blob in its box (Otsu on lightness, clearly above the soil).
    2. Grow by color, like Photoshop's magic wand: bone stays colorless (grey/white) even in its own shade, soil is
       brown - every connected pixel whose color (a*, b*) is closer to the core's than to the soil's joins the shell,
       however dark. Holes filled, 1 px rim added so no white edge survives."""
    x0, y0, x1, y1 = box; H, W = crop.shape[:2]
    lab_img = cv2.cvtColor(crop, cv2.COLOR_BGR2LAB).astype(float); L = lab_img[:, :, 0]; AB = lab_img[:, :, 1:]
    inbox = np.zeros((H, W), np.uint8); inbox[y0:y1, x0:x1] = 1
    ring = cv2.dilate(inbox, np.ones((17, 17), np.uint8)).astype(bool) & ~cv2.dilate(inbox, np.ones((5, 5), np.uint8)).astype(bool)
    t, _ = cv2.threshold(L[y0:y1, x0:x1].astype(np.uint8), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    core = ((L > max(t, np.median(L[ring]) + 15, np.percentile(L[ring], 90) + 3)) & inbox.astype(bool)).astype(np.uint8)
    core = cv2.morphologyEx(core, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    n, lab, st, cen = cv2.connectedComponentsWithStats(core)
    if n < 2 or st[1:, cv2.CC_STAT_AREA].max() < 12:     # deep shade: no bright core -> a colorless blob a bit above the shade
        S = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)[:, :, 1].astype(float)
        core = ((L > np.median(L[ring]) + 6) & (S < 0.7 * np.median(S[ring])) & inbox.astype(bool)).astype(np.uint8)
        core = cv2.morphologyEx(core, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8)); n, lab, st, cen = cv2.connectedComponentsWithStats(core)
        if n < 2: return None
    c = np.array([(x0 + x1) / 2, (y0 + y1) / 2]); diag = np.hypot(x1 - x0, y1 - y0)
    cand = [i for i in range(1, n) if st[i, cv2.CC_STAT_AREA] >= 12 and np.linalg.norm(cen[i] - c) < 0.6 * diag]
    if not cand: return None
    k = max(cand, key=lambda i: L[lab == i].mean() + 0.02 * st[i, cv2.CC_STAT_AREA])
    core = (lab == k).astype(np.uint8)
    # grow by color, but only into the shell's own shape: an oval around the bright core, 1.3x its size (the shaded side)
    if len(cv2.findNonZero(core)) < 5: return None
    (ex, ey), (ew, eh), ea = cv2.fitEllipse(cv2.findNonZero(core))
    oval = cv2.ellipse(np.zeros_like(core), ((ex, ey), (ew * 1.3 + 2, eh * 1.3 + 2), ea), 1, -1)
    bone_ab, soil_ab = np.median(AB[core > 0], 0), np.median(AB[ring], 0)
    S = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)[:, :, 1].astype(float); Lc = L[core > 0].mean()
    wall = (S < 0.8 * np.median(S[ring]) + 5) & (L > 0.42 * Lc) & (L < 0.85 * Lc)   # tilted view: the shell's grey side (cast shadow is < 0.3 Lc)
    # the near side of the dome faces the bottom of a tilted photo: let the grey side wall extend downward only
    below = cv2.ellipse(np.zeros_like(core), ((ex, ey + 0.55 * max(ew, eh) * 0.5), (ew * 1.15 + 2, eh * 1.7 + 4), ea), 1, -1)
    bone_like = ((np.linalg.norm(AB - bone_ab, axis=2) < np.linalg.norm(AB - soil_ab, axis=2)) & (oval > 0)) & (L > np.percentile(L[ring], 5))
    n2, lab2, _, _ = cv2.connectedComponentsWithStats((bone_like | (core > 0)).astype(np.uint8))
    m = np.isin(lab2, list(set(np.unique(lab2[core > 0])) - {0})).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    cnt, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE); m = cv2.drawContours(np.zeros_like(m), cnt, -1, 1, -1)
    if m.sum() > 1.9 * core.sum() + 30:                                      # ran away: use the shell's own fitted oval
        m = cv2.ellipse(np.zeros_like(core), ((ex, ey), (ew * 1.15 + 2, eh * 1.15 + 2), ea), 1, -1)
    # then add the side wall (grey, mid-bright, just below the top), connected to the shell, bounded below
    n3, lab3, _, _ = cv2.connectedComponentsWithStats(((wall & (below > 0)) | (m > 0)).astype(np.uint8))
    m = np.isin(lab3, list(set(np.unique(lab3[m > 0])) - {0})).astype(np.uint8)
    cnt, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE); m = cv2.drawContours(np.zeros_like(m), cnt, -1, 1, -1)
    m = cv2.dilate(m, np.ones((3, 3), np.uint8))
    return m if 15 <= m.sum() <= 1.0 * (x1 - x0) * (y1 - y0) + 40 and len(cv2.findNonZero(m)) >= 5 else None


def outline(img: np.ndarray, box: list[int]) -> tuple[int, int, np.ndarray]:
    """(X0, Y0, mask) - the shell's traced outline near box, in full-image coords; an oval inside the box if untraceable
    (label only, never painted)."""
    x0, y0, x1, y1 = box; pad = 24
    X0, Y0, X1, Y1 = max(0, x0 - pad), max(0, y0 - pad), min(img.shape[1], x1 + pad), min(img.shape[0], y1 + pad)
    m = shell_mask(img[Y0:Y1, X0:X1], (x0 - X0, y0 - Y0, x1 - X0, y1 - Y0))
    if m is None:
        m = cv2.ellipse(np.zeros((Y1 - Y0, X1 - X0), np.uint8), ((x0 + x1) // 2 - X0, (y0 + y1) // 2 - Y0), (max(2, int(0.4 * (x1 - x0))), max(2, int(0.4 * (y1 - y0)))), 0, 0, 360, 1, -1)
    return X0, Y0, m


def reskin(img: np.ndarray, box: list[int], skin: np.ndarray, r: random.Random) -> np.ndarray:
    """img (BGR, full photo) with the shell in box re-skinned by skin. Returns img unchanged if it can't trace the shell."""
    x0, y0, x1, y1 = box; pad = 24
    X0, Y0, X1, Y1 = max(0, x0 - pad), max(0, y0 - pad), min(img.shape[1], x1 + pad), min(img.shape[0], y1 + pad)
    crop = img[Y0:Y1, X0:X1]; m = shell_mask(crop, (x0 - X0, y0 - Y0, x1 - X0, y1 - Y0))
    if m is None: return img
    (cx, cy), (mw, mh), ang = cv2.fitEllipse(cv2.findNonZero(m))
    s, a = skin[:, :, :3], skin[:, :, 3]
    (sx, sy), (sw, sh), sang = cv2.fitEllipse(cv2.findNonZero((a > 128).astype(np.uint8)))
    # affine: skin ellipse -> shell ellipse (rotate skin axis onto shell axis, stretch to shell size, random 180 flip)
    t = np.deg2rad(ang - sang + r.choice([0, 180]))
    R = np.array([[np.cos(t), -np.sin(t)], [np.sin(t), np.cos(t)]])
    S_in = np.array([[np.cos(np.deg2rad(sang)), np.sin(np.deg2rad(sang))], [-np.sin(np.deg2rad(sang)), np.cos(np.deg2rad(sang))]])
    A = np.array([[np.cos(np.deg2rad(sang)), -np.sin(np.deg2rad(sang))], [np.sin(np.deg2rad(sang)), np.cos(np.deg2rad(sang))]]) @ np.diag([1.15 * mw / sw, 1.15 * mh / sh]) @ S_in
    M2 = R @ A; M = np.hstack([M2, (np.array([cx, cy]) - M2 @ np.array([sx, sy]))[:, None]])
    ws = cv2.warpAffine(s, M, (crop.shape[1], crop.shape[0]), flags=cv2.INTER_AREA, borderMode=cv2.BORDER_REFLECT).astype(float)
    wa = cv2.warpAffine(a, M, (crop.shape[1], crop.shape[0]), flags=cv2.INTER_LINEAR) > 64
    inside = m > 0                                                            # the whole traced shell, nothing outside it
    ws = cv2.GaussianBlur(ws, (0, 0), 0.45)                                   # camera softness at 50 ft, pattern kept
    # exposure: the light that actually fell on this shell (its own pixels, sun or shade), living shell 55-80% of bone
    L = cv2.cvtColor(crop, cv2.COLOR_BGR2LAB)[:, :, 0].astype(float)
    sl = cv2.cvtColor(np.clip(ws, 0, 255).astype(np.uint8), cv2.COLOR_BGR2LAB)[:, :, 0].astype(float)
    gain = L[inside].mean() * r.uniform(0.55, 0.8) / max(1.0, sl[inside].mean())
    shade = np.clip((L / max(1.0, L[inside].mean())) ** 0.5, 0.75, 1.25)[:, :, None]   # keep its lit / shaded side
    new = np.clip(ws * gain * shade, 0, 255)
    alpha = cv2.GaussianBlur(inside.astype(float), (0, 0), 0.5)[:, :, None]
    out = img.copy(); out[Y0:Y1, X0:X1] = np.clip(crop * (1 - alpha) + new * alpha, 0, 255).astype(np.uint8)
    return out


def tile_polys(outs: list, boxes: list, x: int, y: int, k: int, T: int = 640) -> list[np.ndarray]:
    """Polygons (tile px, after k x 90 deg CCW turns) of the shells whose box is >= half inside the tile at (x, y)."""
    from turtles.detection.build_dataset import boxes_in
    polys = []
    for (X0, Y0, m), b in zip(outs, boxes):
        if not boxes_in([b], x, y): continue
        t = np.zeros((T, T), np.uint8); h, w = m.shape
        ax0, ay0, ax1, ay1 = max(X0, x), max(Y0, y), min(X0 + w, x + T), min(Y0 + h, y + T)
        if ax1 <= ax0 or ay1 <= ay0: continue
        t[ay0 - y:ay1 - y, ax0 - x:ax1 - x] = m[ay0 - Y0:ay1 - Y0, ax0 - X0:ax1 - X0]
        t = np.ascontiguousarray(np.rot90(t, k))                                 # same turn as the tile (PIL ROTATE_90 = CCW)
        cnt, _ = cv2.findContours(t, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if cnt: c = max(cnt, key=cv2.contourArea); polys.append(c.reshape(-1, 2)) if len(c) >= 3 else None
    return polys


def save_seg(out: Path, split: str, name: str, im, polys: list, T: int = 640) -> None:
    im.save(out / "images" / split / f"{name}.jpg", quality=88 + random.Random(name).randrange(8))
    (out / "labels" / split / f"{name}.txt").write_text("".join("0 " + " ".join(f"{v / T:.5f}" for v in p.ravel()) + "\n" for p in polys))


def build(work: str, data: str, *opts: str) -> None:
    """Dataset RS: real shell photos (bleached original + `--variants` living-turtle re-skins), all shadow-lifted before
    cropping, plus R's empty tiles shadow-lifted the same way. Test B: TEST photos re-skinned once with held-out skins."""
    import shutil
    from PIL import Image
    from turtles.detection.build_dataset import boxes_in, crop, save
    from turtles.detection.build_real import turn
    from turtles.detection.detector import lift_shadows
    o = dict(zip(opts, opts[1:])); V, per = int(o.get("--variants", 5)), int(o.get("--per-shell", 15))
    lab = json.load(open(Path(work, "labels.json")))["labels"]; tr, te = load_skins(work, "train"), load_skins(work, "test")
    out, R = Path(work, "datasets", "RS"), Path(work, "datasets", "R")
    if out.exists(): shutil.rmtree(out)
    if Path(work, "test_b").exists(): shutil.rmtree(Path(work, "test_b"))
    for s in ("train", "val"): (out / "images" / s).mkdir(parents=True); (out / "labels" / s).mkdir(parents=True)
    (out / "preprocess.txt").write_text("lift\n")
    n = {"pos": 0, "neg": 0, "skinned": 0, "kept": 0}
    for src in (k for k, v in lab.items() if not v and "_TEST_" in k):        # Test B keeps the no-visible-shell photos too (unscored, as in A)
        dst = Path(work, "test_b", "flights", "drone_photos", src); dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(Path(data, "flights", "drone_photos", src), dst)
    for src, boxes in sorted((k, v) for k, v in lab.items() if v):
        img, r = cv2.imread(str(Path(data, "flights", "drone_photos", src))), random.Random(src)
        if "_TEST_" in src:
            b_img = img
            for b in boxes: b_img = reskin(b_img, b, r.choice(te), r)
            dst = Path(work, "test_b", "flights", "drone_photos", src); dst.parent.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(dst), b_img, [cv2.IMWRITE_JPEG_QUALITY, 95]); continue
        split = "val" if src.startswith("12_spot8") else "train"
        outs = [outline(img, b) for b in boxes]                                 # the shell's outline -> polygon labels (shape)
        for v in range(V + 1):
            im = img
            if v:
                for b in boxes:
                    new = reskin(im, b, r.choice(tr), r); n["skinned" if new is not im else "kept"] += 1; im = new
            pil = Image.fromarray(cv2.cvtColor(lift_shadows(im), cv2.COLOR_BGR2RGB))
            for j, b in enumerate(boxes):
                for i in range(per if v else per // 2):
                    t, (x, y) = crop(pil, r, b); k = r.randrange(4); t, _ = turn(t, [], k)
                    save_seg(out, split, f"{Path(src).stem}_v{v}_{j}_{i}", t, tile_polys(outs, boxes, x, y, k)); n["pos"] += 1
        print(f"  {split:5s} {src}", flush=True)
    for d in ("train", "val"):
        for p in (R / "images" / d).glob("*.jpg"):
            if "_real" not in p.name:
                cv2.imwrite(str(out / "images" / d / p.name), lift_shadows(cv2.imread(str(p))), [cv2.IMWRITE_JPEG_QUALITY, 90])
                (out / "labels" / d / (p.stem + ".txt")).write_text(""); n["neg"] += 1
    (out / "data.yaml").write_text(f"path: {out.resolve()}\ntrain: images/train\nval: images/val\nnames:\n  0: turtle\n")
    print(f"RS (segmentation: shell outlines as polygons): {n['pos']} shell tiles, {n['neg']} empty tiles (all shadow-lifted); re-skinned {n['skinned']} shells, "
          f"{n['kept']} left bleached (outline not traceable). Test B -> {work}/test_b")


def preview(work: str, data: str, *opts: str) -> None:
    """Original | re-skinned | re-skinned + shadow-lifted (what the model sees), for training spots and Test B."""
    from turtles.detection.detector import lift_shadows
    lab, skins, r, rows = json.load(open(Path(work, "labels.json")))["labels"], load_skins(work, "all"), random.Random(2), []
    picks = [(k, v) for k, v in sorted(lab.items()) if v and "_TEST_" not in k][::3][:8] + [(k, v) for k, v in sorted(lab.items()) if v and "_TEST_" in k][::3][:4]
    for src, boxes in picks:
        img = cv2.imread(str(Path(data, "flights", "drone_photos", src))); b = boxes[0]; new = reskin(img, b, r.choice(skins), r)
        cx, cy = (b[0] + b[2]) // 2, (b[1] + b[3]) // 2; c = lambda im: cv2.resize(im[cy - 45:cy + 45, cx - 45:cx + 45], (180, 180), interpolation=cv2.INTER_NEAREST)
        row = np.hstack([c(img), np.full((180, 3, 3), 255, np.uint8), c(new), np.full((180, 3, 3), 255, np.uint8), c(lift_shadows(new))])
        cv2.putText(row, ("TEST " if "_TEST_" in src else "") + ("" if new is not img else "untouched"), (3, 14), 0, 0.45, (0, 255, 255), 1); rows.append(row)
    cv2.imwrite(str(Path(work, "reskin_check.jpg")), np.vstack([np.hstack(rows[i:i + 2]) if i + 1 < len(rows) else np.hstack([rows[i], np.zeros_like(rows[i])]) for i in range(0, len(rows), 2)]))
    print(f"{len(skins)} skins -> {work}/reskin_check.jpg")


if __name__ == "__main__":
    (preview if "--preview" in sys.argv else build)(*[a for a in sys.argv[1:] if a != "--preview"])
