"""Score a trained model on hand-labeled drone photos -> RESULTS.md (recall first: a missed turtle is the costly error).

    python3 -m turtles.detection.evaluate <work> "<TNUX Turtles Data>" <weights.pt> [--splits test] [--survey 200]

A prediction hits a labeled shell if its center is within max(20 px, half the shell's diagonal) of the shell center.
Recall/precision at score 0.25 / 0.5 / 0.7, by spot and height. --survey N also runs N evenly spaced survey photos
(no turtles) and reports false alarms per photo; their boxes are saved for hard-negative mining.
"""
from __future__ import annotations

import csv, json, math, os, sys
from collections import defaultdict
from pathlib import Path

TH = (0.25, 0.5, 0.7)


def band(ft: int) -> str:
    return "40-55 ft" if ft < 58 else "60-75 ft" if ft < 80 else "90-100 ft"


def main(work: str, data: str, weights: str, *opts: str) -> None:
    o = dict(zip(opts, opts[1:])); splits = o.get("--splits", "test").split(","); n_survey = int(o.get("--survey", 0))
    os.environ["AERO_WEIGHTS"] = weights
    from turtles.detection import detector
    frames = list(csv.DictReader(open(Path(work, "frames.csv")))); lab = json.load(open(Path(work, "labels.json")))["labels"]
    rows, stats = [], defaultdict(lambda: {t: [0, 0, 0] for t in TH})  # [gt, hit, preds]
    for f in frames:
        src = f["path"].split("drone_photos/")[1]
        if f["split"] not in splits or src not in lab: continue
        preds, gt = detector.boxes(f["path"], conf=min(TH)), lab[src]
        for t in TH:
            p = [b for b in preds if b[4] >= t]; used = set(); hit = 0
            for g in gt:
                gc, r = ((g[0] + g[2]) / 2, (g[1] + g[3]) / 2), max(20, math.hypot(g[2] - g[0], g[3] - g[1]) / 2)
                k = next((i for i, b in sorted(enumerate(p), key=lambda e: -e[1][4]) if i not in used and math.dist(gc, ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)) <= r), None)
                if k is not None: used.add(k); hit += 1
            for key in ("ALL", f["folder"].split("_DJI")[0], band(int(f["alt_ft"]))):
                s = stats[key][t]; s[0] += len(gt); s[1] += hit; s[2] += len(p)
        rows.append(dict(src=src, gt=gt, preds=[[round(v, 3) for v in b] for b in preds]))
        print(src, len(gt), "shell(s),", sum(b[4] >= 0.25 for b in preds), "pred(s)", flush=True)
    fa = []
    if n_survey:
        sv = [f for f in frames if f["split"] == "survey"]; sv = sv[:: max(1, len(sv) // n_survey)][:n_survey]
        for f in sv:
            p = detector.boxes(f["path"], conf=0.15); fa.append(dict(src=f["path"], preds=[[round(v, 3) for v in b] for b in p]))
            print("survey", Path(f["path"]).name, len([b for b in p if b[4] >= 0.25]), flush=True)
    out = Path(work, "eval", Path(weights).stem); out.mkdir(parents=True, exist_ok=True)
    json.dump(dict(rows=rows, survey=fa), open(out / "predictions.json", "w"))
    md = [f"# Detector results: `{Path(weights).stem}` on {'+'.join(splits)} photos\n",
          "Hit = predicted center within max(20 px, half the shell diagonal) of the labeled shell. Recall first.\n",
          "| Group | Shells | " + " | ".join(f"Recall @{t} | Precision @{t}" for t in TH) + " |", "|---|---|" + "---|---|" * len(TH)]
    for key in ["ALL"] + sorted(k for k in stats if k != "ALL"):
        s = stats[key]; md.append(f"| {key} | {s[TH[0]][0]} | " + " | ".join(
            f"{s[t][1] / s[t][0]:.0%} | {(s[t][1] / s[t][2]) if s[t][2] else float('nan'):.0%}" if s[t][0] else "- | -" for t in TH) + " |")
    if fa:
        md += ["", f"**False alarms on {len(fa)} survey photos (no turtles present):** " + ", ".join(
            f"{sum(sum(b[4] >= t for b in r['preds']) for r in fa) / len(fa):.2f}/photo @{t}" for t in TH)]
    (out / "RESULTS.md").write_text("\n".join(md) + "\n"); print("\n".join(md))


if __name__ == "__main__":
    main(*sys.argv[1:])
