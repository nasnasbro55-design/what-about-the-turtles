"""Detection track for a recorded drone video, for the app's flight-video screen (GET /videos).

    python3 -m turtles.backend.video_track <drone video .MP4> <db folder> --name turtle_B_2026-11-06 \
        --title "Turtle B, Nov 6" --caption "..." [--fps 1]

Writes <db folder>/videos/<name>.mp4 (1280 px H.264 that phones play; needs ffmpeg) and <name>.json: the detector's
boxes (source pixels, score >= 0.25) for one frame every 1/fps seconds. This runs after landing, not live: at ~1.6 s per
4K frame on the laptop the detector is slower than real time, and the app says so. Uses AERO_WEIGHTS like the server.
--frames <folder of t_0001.jpg ...> uses already-extracted frames (1/fps apart, first at 0 s) instead of decoding the video.
"""
from __future__ import annotations

import json, os, shutil, subprocess, sys, time
from pathlib import Path

FLOOR = 0.25   # boxes kept in the track; the app shows >= 0.5 by default with a switch for all


def track(frames, fps: float, boxes) -> tuple[list[dict], float]:
    """frames: iterable of PIL images in time order -> [{t, boxes: [[x0, y0, x1, y1, score], ...]}], ms per frame."""
    out, ms = [], 0.0
    for i, im in enumerate(frames):
        t0 = time.perf_counter(); b = boxes(im, conf=FLOOR); ms += (time.perf_counter() - t0) * 1000
        out.append({"t": round(i / fps, 2), "boxes": [[round(x0), round(y0), round(x1), round(y1), round(s, 3)] for x0, y0, x1, y1, s in b]})
    return out, ms / max(1, len(out))


def main(video: str, db_dir: str, *opts: str) -> None:
    o = dict(zip(opts, opts[1:])); fps = float(o.get("--fps", 1)); name = o.get("--name", Path(video).stem)
    out = Path(db_dir, "videos"); out.mkdir(parents=True, exist_ok=True)
    from PIL import Image
    from turtles.detection import detector
    if "--frames" in o:
        files = sorted(Path(o["--frames"]).glob("*.jpg")); size = Image.open(files[0]).size
        frames = (Image.open(f).convert("RGB") for f in files)
    else:
        import cv2
        cap = cv2.VideoCapture(video); src_fps, n = cap.get(cv2.CAP_PROP_FPS), int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        size = (int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
        def grab():
            for k in range(int(n / src_fps * fps)):
                cap.set(cv2.CAP_PROP_POS_FRAMES, round(k / fps * src_fps)); ok, f = cap.read()
                if not ok: return
                yield Image.fromarray(cv2.cvtColor(f, cv2.COLOR_BGR2RGB))
        frames = grab()
    rows, ms = track(frames, fps, detector.boxes)
    mp4 = out / f"{name}.mp4"
    if not mp4.exists() and shutil.which("ffmpeg"):
        subprocess.run(["ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-i", video, "-vf", "scale=1280:-2", "-c:v", "libx264",
                        "-preset", "veryfast", "-crf", "26", "-pix_fmt", "yuv420p", "-an", "-movflags", "+faststart", str(mp4)], check=True)
    meta = {"title": o.get("--title", name), "caption": o.get("--caption", ""), "recorded": o.get("--recorded", ""),
            "model": detector.MODEL_VERSION, "source": Path(video).name, "src_size": list(size), "sample_fps": fps,
            "ms_per_frame": round(ms), "floor": FLOOR, "frames": rows}
    (out / f"{name}.json").write_text(json.dumps(meta))
    hits = [r["t"] for r in rows if any(b[4] >= 0.5 for b in r["boxes"])]
    print(f"{len(rows)} frames, {ms:.0f} ms/frame, model {meta['model']}; frames with a box >= 0.5: {len(hits)}"
          + (f" ({hits[0]:.0f}-{hits[-1]:.0f} s)" if hits else "") + f"\n-> {out / (name + '.json')}" + ("" if mp4.exists() else "\n(no ffmpeg: copy a 1280 px H.264 .mp4 there yourself)"))


if __name__ == "__main__":
    main(*sys.argv[1:])
