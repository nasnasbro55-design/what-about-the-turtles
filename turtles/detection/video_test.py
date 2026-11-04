"""Live-feed test: run the detector on recorded HDMI feed clips (what live mode would see) -> VIDEO_RESULTS.md.

    python3 -m turtles.detection.video_test <work> "<TNUX Turtles Data>" <weights.pt> [--fps 2] [--lift]

Measures, per clip and overall: detector speed (ms per frame; live needs < 1000 / fps), detections per minute at
0.25 / 0.5 / 0.7 (Oct 30 clips: no turtle placed -> every detection is a false alarm unless a shell is confirmed
in the frame), and saves every frame with a detection >= 0.25 to <work>/eval/<model>_video/ for a human to check.
Resolution note: the feed is 1280 x 720, so a box turtle at 50 ft is ~8 px wide (vs ~32 px in the 5280 px photos).
"""
from __future__ import annotations

import os, sys, time
from pathlib import Path

TH = (0.25, 0.5, 0.7)


def main(work: str, data: str, weights: str, *opts: str) -> None:
    import cv2
    from PIL import Image
    o = dict(zip(opts, opts[1:])); fps = float(o.get("--fps", 2))
    os.environ["AERO_WEIGHTS"] = weights; os.environ["AERO_SHADOW_LIFT"] = "1" if "--lift" in opts else "0"
    from turtles.detection import detector
    out = Path(work, "eval", Path(weights).parent.parent.name + "_video" + ("_lift" if "--lift" in opts else "")); out.mkdir(parents=True, exist_ok=True)
    rows, tot = [], {"sec": 0.0, "frames": 0, "ms": 0.0, **{t: 0 for t in TH}}
    for clip in sorted(Path(data, "flights", "drone_videos").glob("*.mov")):
        cap = cv2.VideoCapture(str(clip)); src_fps, n = cap.get(cv2.CAP_PROP_FPS), int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        step, r = max(1, round(src_fps / fps)), {"clip": clip.name, "sec": n / src_fps, "frames": 0, "ms": 0.0, **{t: 0 for t in TH}}
        detector.boxes(Image.new("RGB", (1280, 720)))  # warm-up so model load isn't counted as speed
        for i in range(0, n, step):
            cap.set(cv2.CAP_PROP_POS_FRAMES, i); ok, f = cap.read()
            if not ok: break
            t0 = time.perf_counter(); b = detector.boxes(Image.fromarray(cv2.cvtColor(f, cv2.COLOR_BGR2RGB)), conf=min(TH)); r["ms"] += (time.perf_counter() - t0) * 1000
            r["frames"] += 1
            for t in TH: r[t] += sum(x[4] >= t for x in b)
            if any(x[4] >= min(TH) for x in b):
                for x0, y0, x1, y1, s in b: cv2.rectangle(f, (int(x0) - 6, int(y0) - 6), (int(x1) + 6, int(y1) + 6), (0, 0, 255), 2); cv2.putText(f, f"{s:.2f}", (int(x0), int(y0) - 10), 0, 0.6, (0, 0, 255), 2)
                cv2.imwrite(str(out / f"{clip.stem}_{i / src_fps:06.1f}s.jpg"), f)
        print(f"{clip.name}: {r['frames']} frames, {r['ms'] / max(1, r['frames']):.0f} ms/frame, detections @0.25: {r[0.25]}", flush=True)
        rows.append(r); [tot.__setitem__(k, tot[k] + r[k]) for k in tot]
    md = [f"# Live-feed test: `{out.name}`\n",
          f"Recorded HDMI feed (1280 x 720), Oct 30, {tot['sec'] / 60:.1f} min, sampled at {fps:g} frames/s. No turtle was placed for these clips,",
          "so every detection counts as a false alarm unless a person confirms a shell in the saved frame. A box turtle at 50 ft is ~8 px wide here.\n",
          "| Clip | Minutes | Frames | ms / frame | " + " | ".join(f"Detections/min @{t}" for t in TH) + " |", "|---|---|---|---|" + "---|" * len(TH)]
    for r in rows + [dict(tot, clip="ALL")]:
        md.append(f"| {r['clip']} | {r['sec'] / 60:.1f} | {r['frames']} | {r['ms'] / max(1, r['frames']):.0f} | " + " | ".join(f"{r[t] / max(r['sec'] / 60, 1e-9):.1f}" for t in TH) + " |")
    ms = tot["ms"] / max(1, tot["frames"])
    md += ["", f"**Real-time check:** {ms:.0f} ms per frame -> up to {1000 / ms:.1f} frames/s on this laptop (live needs >= {fps:g})." if ms else "",
           f"Frames with a detection are saved in `{out}` for a person to review."]
    (out / "VIDEO_RESULTS.md").write_text("\n".join(md) + "\n"); print("\n".join(md))


if __name__ == "__main__":
    main(*sys.argv[1:])
