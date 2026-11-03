"""Score a trained model -> RESULTS.md. The test protocol is fixed BEFORE looking at any result (PROTOCOL below).

    python3 -m turtles.detection.evaluate <work> "<TNUX Turtles Data>" <weights.pt> [--splits test]

Shells: every hand-labeled shell in the held-out photos (rut, half buried, riprap), scored on the full 5280 x 3956
photo exactly as in a real flight (sliced 640 px tiles, overlaps merged). False alarms: all 139 photos of survey
leg 3, which model M never trained on in any form. 95% intervals are Wilson score intervals.
"""
from __future__ import annotations

import csv, json, math, os, sys
from collections import defaultdict
from pathlib import Path

TH = (0.25, 0.5, 0.7)
HEADLINE = 0.25            # the operating threshold, chosen before testing (fusion's floor)
TARGET = 0.70
HOLDOUT_SURVEY = "03_survey_part3"
PROTOCOL = f"""**Protocol (fixed before testing).** Headline = recall at score >= {HEADLINE} on every visible hand-labeled shell in the
3 held-out spots (rut, half buried, riprap), per photo, full-resolution photos, target {TARGET:.0%}. A detection counts as
a hit only if its center is within max(20 px, half the shell's box diagonal) of the labeled center; each shell can be
matched once. Model M never trained on these spots (no tiles, no shell cut-outs) or on survey leg 3 (false-alarm set).
Photos where no person could find the shell are excluded from recall and listed separately."""


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if not n: return float("nan"), float("nan")
    p = k / n; d = 1 + z * z / n; c = (p + z * z / (2 * n)) / d; h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0, c - h), min(1, c + h)


def band(ft: int) -> str:
    return "40-55 ft" if ft < 58 else "60-75 ft" if ft < 80 else "90-100 ft"


def match(gt: list, preds: list) -> int:
    used, hit = set(), 0
    for g in gt:
        gc, r = ((g[0] + g[2]) / 2, (g[1] + g[3]) / 2), max(20, math.hypot(g[2] - g[0], g[3] - g[1]) / 2)
        k = next((i for i, b in sorted(enumerate(preds), key=lambda e: -e[1][4]) if i not in used and math.dist(gc, ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)) <= r), None)
        if k is not None: used.add(k); hit += 1
    return hit


def main(work: str, data: str, weights: str, *opts: str) -> None:
    o = dict(zip(opts, opts[1:])); splits = o.get("--splits", "test").split(",")
    os.environ["AERO_WEIGHTS"] = weights
    from turtles.detection import detector
    frames = list(csv.DictReader(open(Path(work, "frames.csv")))); lab = json.load(open(Path(work, "labels.json")))["labels"]
    stats, spot_found, unseen, rows = defaultdict(lambda: {t: [0, 0, 0] for t in TH}), defaultdict(set), defaultdict(list), []
    for f in frames:
        src = f["path"].split("drone_photos/")[1]
        if f["split"] not in splits or src not in lab: continue
        preds, gt, spot = detector.boxes(f["path"], conf=min(TH)), lab[src], f["folder"].split("_DJI")[0]
        if not gt: unseen[spot].append(sum(b[4] >= HEADLINE for b in preds))
        for t in TH:
            p = [b for b in preds if b[4] >= t]; hit = match(gt, p)
            for key in ("ALL", spot, band(int(f["alt_ft"]))):
                s = stats[key][t]; s[0] += len(gt); s[1] += hit; s[2] += len(p)
            if t == HEADLINE and hit: spot_found[spot].add(src)
        rows.append(dict(src=src, gt=gt, preds=[[round(v, 3) for v in b] for b in preds]))
        print(src, len(gt), "shell(s),", sum(b[4] >= HEADLINE for b in preds), "pred(s)", flush=True)
    fa = []
    for f in (f for f in frames if f["folder"].startswith(HOLDOUT_SURVEY)):
        p = detector.boxes(f["path"], conf=min(TH)); fa.append(dict(src=f["path"], preds=[[round(v, 3) for v in b] for b in p]))
    out = Path(work, "eval", Path(weights).parent.parent.name if Path(weights).parent.name == "weights" else Path(weights).stem); out.mkdir(parents=True, exist_ok=True)
    json.dump(dict(rows=rows, survey=fa), open(out / "predictions.json", "w"))
    a = stats["ALL"][HEADLINE]; lo, hi = wilson(a[1], a[0])
    md = [f"# Detector results: `{out.name}`\n", PROTOCOL + "\n",
          f"## Headline: recall {a[1]}/{a[0]} = **{a[1] / a[0]:.0%}** (95% CI {lo:.0%}-{hi:.0%}) at score >= {HEADLINE} - target {TARGET:.0%}: "
          f"**{'MET' if a[1] / a[0] >= TARGET else 'NOT MET'}**\n",
          "| Group | Shells | " + " | ".join(f"Recall @{t} (95% CI) | Precision @{t}" for t in TH) + " |", "|---|---|" + "---|---|" * len(TH)]
    for key in ["ALL"] + sorted(k for k in stats if k != "ALL"):
        s = stats[key]; md.append(f"| {key} | {s[TH[0]][0]} | " + " | ".join(
            (f"{s[t][1] / s[t][0]:.0%} ({wilson(s[t][1], s[t][0])[0]:.0%}-{wilson(s[t][1], s[t][0])[1]:.0%}) | "
             f"{(s[t][1] / s[t][2]) if s[t][2] else float('nan'):.0%}") if s[t][0] else "- | -" for t in TH) + " |")
    md += ["", f"**False alarms, survey leg 3 ({len(fa)} photos never trained on, no turtles present):** " + ", ".join(
        f"{sum(sum(b[4] >= t for b in r['preds']) for r in fa) / max(1, len(fa)):.2f} per photo @{t}" for t in TH),
        "", "**Spot-level (secondary):** photos of each held-out spot in which the shell was found at least once @0.25: " + ", ".join(
        f"{k}: {len(v)}" for k, v in sorted(spot_found.items())),
        "", "**Photos where no person could find the shell** (not scored; detections @0.25 shown): " + (", ".join(
        f"{k}: {len(v)} photos, {sum(v)} detections" for k, v in sorted(unseen.items())) or "none")]
    (out / "RESULTS.md").write_text("\n".join(md) + "\n"); print("\n".join(md))


if __name__ == "__main__":
    main(*sys.argv[1:])
