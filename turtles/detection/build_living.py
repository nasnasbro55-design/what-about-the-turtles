"""Dataset RL (model v3): dataset RS + photos of real LIVING box turtles (heads, legs, side views, Tanya's black-and-
yellow pattern) placed on survey legs 1-2 - what v2 never saw (Test D, Nov 5: v2 missed side views and black-and-yellow).

  * turtles: Test D's selection (test_d/selection.json) MINUS 6 held-out turtles (test_d/labels_holdout.json), fixed
    before this data was built; v3 is judged on Test B (unchanged) and on those 27 held-out Test D photos
  * ground: legs 1-2 only (every 3rd photo, offset 1 from RS's placements), test_d.ground_ok() spots; never leg 3
    (Test D's ground) or the TEST spots
  * 2 turtles per photo, one 640 px tile each, shadow-lifted, rotated, outline polygons; ~800 tiles, so pasted turtles
    stay a minority (RS: 1628 placement tiles of 7178)

    python3 -m turtles.detection.build_living <work> "<TNUX Turtles Data>"
    python3 -m turtles.detection.train <work> RL --hours 2.5 --model <work>/runs/rs_seg_v2/weights/last.pt --name rl_seg_v3
"""
from __future__ import annotations

import json, random, shutil, subprocess, sys
from pathlib import Path

import cv2

from turtles.backend.ingest import frame_from_photo
from turtles.detection.test_c import place
from turtles.detection.test_d import ground_ok, sprite


def main(work: str, data: str) -> None:
    from PIL import Image
    from turtles.detection.build_dataset import crop
    from turtles.detection.build_real import turn
    from turtles.detection.detector import lift_shadows
    from turtles.detection.reskin import save_seg, tile_polys
    rs, out = Path(work, "datasets", "RS"), Path(work, "datasets", "RL")
    if not (out / "images").exists():                                         # RS as-is (hard links: no extra disk)
        out.mkdir(parents=True)
        for sub in ("images", "labels"):
            if subprocess.run(["cp", "-al", str(rs / sub), str(out / sub)]).returncode: shutil.copytree(rs / sub, out / sub)
        shutil.copy(rs / "preprocess.txt", out / "preprocess.txt")
    hold = set(json.load(open(Path(work, "test_d", "labels_holdout.json")))["holdout_sprites"])
    keep = [n for n in json.load(open(Path(work, "test_d", "selection.json")))["keep"] if n not in hold]
    n = 0
    for p in sorted(Path(data, "flights", "drone_photos").glob("0[12]_survey_part*/*_V.JPG"))[1::3]:
        done = out / "labels" / "train" / f"{p.stem}_live_done"
        if done.exists(): continue
        r = random.Random("living" + p.name)
        try: f = frame_from_photo(p, p.parent, "grayson", "L")
        except ValueError: f = None                                          # e.g. a zeroed timestamp
        if f is None: done.touch(); continue
        img = cv2.imread(str(p)); boxes, outs = [], []
        for _ in range(2):
            spot = next(((x, y) for x, y in ((r.uniform(250, f.width_px - 250), r.uniform(250, f.height_px - 250)) for _ in range(30))
                         if ground_ok(img, x, y) is None and all(abs(x - (c[0] + c[2]) / 2) > 150 or abs(y - (c[1] + c[3]) / 2) > 150 for c in boxes)), None)
            if spot is None: continue                                        # (checked BEFORE pasting: no unlabeled turtle)
            b, o = place(img, f, sprite(Path(work, "sprites", "turtle", r.choice(keep)), img), *spot, r)
            boxes.append(b); outs.append(o)
        if not boxes: done.touch(); continue
        pil = Image.fromarray(cv2.cvtColor(lift_shadows(img), cv2.COLOR_BGR2RGB)); split = "val" if r.random() < 0.08 else "train"
        for j, b in enumerate(boxes):
            t, (x, y) = crop(pil, r, b); k = r.randrange(4); t, _ = turn(t, [], k)
            save_seg(out, split, f"{p.stem}_live{j}", t, tile_polys(outs, boxes, x, y, k)); n += 1
        done.touch(); print(p.name, n, flush=True)
    print(f"{n} new living-turtle tiles -> {out}")


if __name__ == "__main__":
    main(*sys.argv[1:])
