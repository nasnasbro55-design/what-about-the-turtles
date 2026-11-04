"""Train the turtle detector on the Mac (Apple GPU).

    python3 -m turtles.detection.train <work> M [--model yolo11s.pt] [--epochs 40 | --hours 3] [--name m_v1] [--fraction 0.6] [--val-max 400]

--hours fits the whole run (LR schedule included) into that time - on the M4 (no dataloader workers on MPS) ~3.5 s per batch of 16.

Aerial settings: both flips (no "up" from above), no extra affine rotation (sprites are already rotated),
mild scale jitter (height varies 40-100 ft), mosaic on. One class: turtle. Best weights -> <work>/runs/<name>/weights/best.pt
"""
from __future__ import annotations

import sys
from pathlib import Path


def main(work: str, ds: str, *opts: str) -> None:
    from ultralytics import YOLO
    o = dict(zip(opts, opts[1:])); d = Path(work, "datasets", ds).resolve()
    vm = int(o.get("--val-max", 400)); val = sorted((d / "images" / "val").glob("*.jpg"))
    (d / "val_subset.txt").write_text("\n".join(str(p) for p in val[:: max(1, len(val) // vm)][:vm]) + "\n")  # a fixed sample: per-epoch val stays ~20 s
    (d / "data.yaml").write_text(f"path: {d}\ntrain: images/train\nval: val_subset.txt\nnames:\n  0: turtle\n")  # this machine's path
    YOLO(o.get("--model", "yolo11s.pt")).train(
        data=str(d / "data.yaml"), imgsz=640, epochs=int(o.get("--epochs", 40)), time=float(o["--hours"]) if "--hours" in o else None,
        batch=int(o.get("--batch", 16)), device=o.get("--device", "mps"), workers=6, patience=12,
        project=str(Path(work, "runs")), name=o.get("--name", f"{ds.lower()}_v1"), exist_ok=True,
        fliplr=0.5, flipud=0.5, degrees=0, scale=0.25, translate=0.1, mosaic=1.0, close_mosaic=8,
        hsv_h=0.01, hsv_s=0.4, hsv_v=0.35, plots=True, seed=7, cache=False, amp=False, fraction=float(o.get("--fraction", 1.0)))
    if (d / "preprocess.txt").exists():   # detector applies the same preprocessing (shadow lift) to every photo
        (Path(work, "runs", o.get("--name", f"{ds.lower()}_v1")) / "preprocess.txt").write_text((d / "preprocess.txt").read_text())


if __name__ == "__main__":
    main(*sys.argv[1:])
