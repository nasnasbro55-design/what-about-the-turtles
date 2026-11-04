"""Build a YOLO dataset of 640 px tiles cut at native drone resolution (no resizing: a 50 ft shell stays ~30 px).

    python3 -m turtles.detection.build_dataset <work> "<TNUX Turtles Data>" M --pass base    # no labels needed yet
    python3 -m turtles.detection.build_dataset <work> "<TNUX Turtles Data>" M --pass drone   # after labels.json
    python3 -m turtles.detection.build_dataset <work> "<TNUX Turtles Data>" M --pass neg     # 3 more plain negatives/photo
    python3 -m turtles.detection.build_dataset <work> "<TNUX Turtles Data>" F --pass drone   # F reuses M's base + neg tiles
    (--limit N: only N survey photos; --workers N; re-runnable, finished photos are skipped)

Model M never sees the TEST spots; model F sees everything.
base pass, per survey photo (all 1,536): 2 negative tiles + 3 synthetic tiles with GMU turtle/shell sprites pasted into
  the real ground (1-3 each), plus leaf/stick decoys that are NOT labeled.
tanya pass: 1 more synthetic tile per survey photo using Tanya's field photos (sprites/turtle/tanya_*.png).
drone pass: per labeled shell photo, 12 tiles around each shell + 4 without; per survey photo, 2 more synthetic tiles
  using shells cropped from the drone photos themselves (TEST crops only for F).
Needs <work>/frames.csv, <work>/labels.json, <work>/sprites/{turtle,distractor,drone}/.
"""
from __future__ import annotations

import csv, json, random, sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter

T = 640           # tile size
VAL = 0.1         # fraction of photos whose tiles go to val
SIZE_PX = [(0.6, 22, 40), (0.25, 13, 22), (0.15, 40, 64)]  # (share, min, max) sprite long side: 50-65 ft, 65-100 ft, <50 ft


def load_sprites(d: Path) -> list[Image.Image]:
    return [Image.open(p).convert("RGBA") for p in sorted(d.glob("*.png"))] if d.exists() else []


def bury(s: Image.Image, r: random.Random) -> Image.Image:
    """Erase part of the sprite from one side with a ragged edge: half-buried, behind a clod, under the silt fence."""
    w, h = s.size; keep = r.uniform(0.5, 0.85); m = Image.new("L", (w, h), 0); d = ImageDraw.Draw(m)
    pts = [(x, h * keep + r.uniform(-0.08, 0.08) * h) for x in np.linspace(0, w, 8)]
    d.polygon([(0, 0), (w, 0)] + pts[::-1], fill=255)
    m = m.rotate(r.uniform(0, 360), resample=Image.BILINEAR, fillcolor=255) if r.random() < 0.5 else m
    s.putalpha(ImageChops.multiply(s.getchannel("A"), m.filter(ImageFilter.GaussianBlur(1))))
    return s


def paste(bg: Image.Image, s: Image.Image, long_px: float, r: random.Random, xy=None, buried=False) -> list[float] | None:
    """Paste one sprite at long side long_px; returns its visible box [x0,y0,x1,y1] or None if it ended up invisible."""
    s = s.rotate(r.uniform(0, 360), resample=Image.BICUBIC, expand=True)
    s = s.transpose(Image.FLIP_LEFT_RIGHT) if r.random() < 0.5 else s
    bb = s.getchannel("A").point(lambda v: 255 if v > 40 else 0).getbbox()
    if not bb: return None
    s = s.crop(bb); k = long_px / max(s.size); s = s.resize((max(2, round(s.width * k)), max(2, round(s.height * k))), Image.LANCZOS)
    rgb = s.convert("RGB")
    rgb = ImageEnhance.Brightness(rgb).enhance(r.uniform(0.55, 1.25)); rgb = ImageEnhance.Contrast(rgb).enhance(r.uniform(0.65, 1.15))
    rgb = ImageEnhance.Color(rgb).enhance(r.uniform(0.75, 1.2))
    x, y = xy or (r.randrange(0, T - s.width), r.randrange(0, T - s.height))
    under = bg.crop((x, y, x + s.width, y + s.height))
    rgb = Image.blend(rgb, Image.new("RGB", s.size, tuple(np.array(under).reshape(-1, 3).mean(0).astype(int))), r.uniform(0, 0.18))  # pick up the ground's light/dust
    rgb = rgb.filter(ImageFilter.GaussianBlur(r.uniform(0, 0.7))); s = Image.merge("RGBA", (*rgb.split(), s.getchannel("A")))
    if buried: s = bury(s, r)
    if r.random() < 0.7:  # sun shadow
        sh = Image.new("RGBA", s.size, (0, 0, 0, 0)); sh.putalpha(s.getchannel("A").point(lambda v: int(v * r.uniform(0.25, 0.5))).filter(ImageFilter.GaussianBlur(1.5)))
        dx, dy = round(r.uniform(-0.25, 0.25) * s.width), round(r.uniform(0, 0.3) * s.height); bg.paste(sh, (x + dx, y + dy), sh)
    bg.paste(s, (x, y), s.getchannel("A").filter(ImageFilter.GaussianBlur(0.4)))
    vb = s.getchannel("A").point(lambda v: 255 if v > 90 else 0).getbbox()
    return [x + vb[0], y + vb[1], x + vb[2], y + vb[3]] if vb and (vb[2] - vb[0]) * (vb[3] - vb[1]) >= 25 else None


def edge_xy(bg: Image.Image, r: random.Random, pad: int) -> tuple[int, int] | None:
    """A spot on a strong edge (rut wall, fence line, clod) - where turtles hide and detectors get fooled."""
    g = np.array(bg.convert("L").filter(ImageFilter.FIND_EDGES).filter(ImageFilter.GaussianBlur(3)), dtype=float)[pad:T - pad, pad:T - pad]
    if g.max() <= 0: return None
    i = r.choices(range(g.size), weights=(g.ravel() ** 2), k=1)[0]
    return i % g.shape[1] + pad // 2, i // g.shape[1] + pad // 2


def save(out: Path, split: str, name: str, im: Image.Image, boxes: list) -> None:
    im.save(out / "images" / split / f"{name}.jpg", quality=r_q(name))
    (out / "labels" / split / f"{name}.txt").write_text("".join(
        f"0 {(b[0] + b[2]) / 2 / T:.6f} {(b[1] + b[3]) / 2 / T:.6f} {(b[2] - b[0]) / T:.6f} {(b[3] - b[1]) / T:.6f}\n" for b in boxes))


def r_q(name: str) -> int:
    return 80 + random.Random(name).randrange(15)  # varied JPEG quality, the live feed and phone uploads will be compressed


def crop(im: Image.Image, r: random.Random, must=None) -> tuple[Image.Image, tuple[int, int]]:
    """Random T x T crop; if must=[x0,y0,x1,y1] it contains that box (anywhere, with margin)."""
    W, H = im.size
    if must:
        x = r.randint(min(max(0, must[2] + 8 - T), W - T), min(W - T, max(0, must[0] - 8)))
        y = r.randint(min(max(0, must[3] + 8 - T), H - T), min(H - T, max(0, must[1] - 8)))
    else:
        x, y = r.randrange(0, W - T), r.randrange(0, H - T)
    return im.crop((x, y, x + T, y + T)), (x, y)


def boxes_in(boxes: list, x: int, y: int) -> list:
    """Labels that fall inside the tile at (x, y), clipped; drop ones less than half inside."""
    out = []
    for b in boxes:
        c = [max(b[0] - x, 0), max(b[1] - y, 0), min(b[2] - x, T), min(b[3] - y, T)]
        if c[2] > c[0] and c[3] > c[1] and (c[2] - c[0]) * (c[3] - c[1]) >= 0.5 * (b[2] - b[0]) * (b[3] - b[1]): out.append(c)
    return out


S: dict = {}


def init(work: str, mode: str) -> None:
    S["gmu"] = load_sprites(Path(work, "sprites", "turtle")); S["drone"] = load_sprites(Path(work, "sprites", "drone_" + mode))
    S["tanya"] = [load_sprites(Path(work, "sprites", "turtle"))[i] for i, p in enumerate(sorted(Path(work, "sprites", "turtle").glob("*.png"))) if p.name.startswith("tanya_")]
    S["decoy"] = load_sprites(Path(work, "sprites", "distractor"))


def do_photo(job: tuple) -> int:
    kind, path, boxes, name, out, split, pas = job
    out = Path(out); r = random.Random(name + pas); done = out / "labels" / split / f"{name}_{pas}_done"
    if done.exists(): return 0
    im = Image.open(path).convert("RGB"); n = 0
    if kind == "survey":
        for i in {"base": range(2), "neg": range(2, 5)}.get(pas, ()):
            t, _ = crop(im, r)
            for _ in range(r.choice([0, 0, 1, 2])): paste(t, r.choice(S["decoy"]), r.uniform(15, 60), r)
            save(out, split, f"{name}_neg{i}", t, []); n += 1
        for i in {"base": range(3), "drone": range(2), "tanya": range(1)}.get(pas, ()):
            t, _ = crop(im, r); bx = []
            for _ in range(r.choice([1, 1, 1, 2, 3])):
                L = r.uniform(*r.choices([(a, b) for _, a, b in SIZE_PX], weights=[p for p, _, _ in SIZE_PX])[0]); xy = edge_xy(t, r, int(L) + 4) if r.random() < 0.4 else None
                b = paste(t, r.choice(S[{"base": "gmu", "drone": "drone", "tanya": "tanya"}[pas]]), L, r, xy, buried=r.random() < 0.35)
                if b: bx.append(b)
            for _ in range(r.choice([0, 1, 2])): paste(t, r.choice(S["decoy"]), r.uniform(15, 60), r)
            save(out, split, f"{name}_{dict(base='syn', drone='dsyn', tanya='tsyn')[pas]}{i}", t, bx); n += 1
    elif boxes:  # a hand-labeled shell photo (photos where nobody could find the shell are skipped, never used as "empty")
        for j, b in enumerate(boxes):
            for i in range(12):
                t, (x, y) = crop(im, r, b); save(out, split, f"{name}_pos{j}_{i}", t, boxes_in(boxes, x, y)); n += 1
        for i in range(4):
            for _ in range(20):
                t, (x, y) = crop(im, r)
                if not boxes_in(boxes, x, y): save(out, split, f"{name}_bg{i}", t, []); n += 1; break
    done.touch()
    return n


def main(work: str, data: str, mode: str, *opts: str) -> None:
    o = dict(zip(opts, opts[1:])); limit = int(o["--limit"]) if "--limit" in o else None; pas = o.get("--pass", "base")
    out = Path(work, "datasets", mode)
    for s in ("train", "val"): (out / "images" / s).mkdir(parents=True, exist_ok=True); (out / "labels" / s).mkdir(parents=True, exist_ok=True)
    frames = list(csv.DictReader(open(Path(work, "frames.csv"))))
    lab = json.load(open(Path(work, "labels.json")))["labels"] if Path(work, "labels.json").exists() else {}
    jobs = []
    for f in frames:
        name = Path(f["path"]).stem; split = "val" if random.Random(name).random() < VAL else "train"
        if f["split"] == "survey" and mode == "M" and f["folder"].startswith("03_survey_part3"): continue  # untouched false-alarm test set
        if f["split"] == "survey": jobs.append(("survey", f["path"], [], name, str(out), split, pas))
        elif pas == "drone" and (f["split"] == "train" or mode == "F") and (src := f["path"].split("drone_photos/")[1]) in lab:
            jobs.append(("shell", f["path"], lab[src], name, str(out), split, pas))
    if pas == "drone" and not load_sprites(Path(work, "sprites", "drone_" + mode)): sys.exit(f"no sprites in {work}/sprites/drone_{mode} - run sprites.py drone first")
    if pas in ("base", "neg") and mode == "F" and Path(work, "datasets", "M").exists():  # same base tiles as M: hard-link instead of rebuilding
        import os
        for f in Path(work, "datasets", "M").rglob("*"):
            if f.is_file() and (any(t in f.name for t in ("_syn", "_neg", "_base_done", "_neg_done")) and "_dsyn" not in f.name):
                d = out / f.relative_to(Path(work, "datasets", "M")); d.exists() or os.link(f, d)
        jobs = []
    jobs = [j for j in jobs if j[0] == "shell"] + [j for j in jobs if j[0] == "survey"][:limit]
    with ProcessPoolExecutor(int(o.get("--workers", 4)), initializer=init, initargs=(work, mode)) as ex:
        n = sum(ex.map(do_photo, jobs, chunksize=4))
    (out / "data.yaml").write_text(f"path: {out.resolve()}\ntrain: images/train\nval: images/val\nnames:\n  0: turtle\n")
    print(f"{n} new tiles from {len(jobs)} photos -> {out}")


if __name__ == "__main__":
    main(*sys.argv[1:])
