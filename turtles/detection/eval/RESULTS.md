# A.E.R.O. detector - results (Nov 4-5, 2026)

Final model: `rs_seg_v2` - YOLO11s segmentation, 640 px tiles at native drone resolution, every photo shadow-lifted
(CLAHE) before detection. Weights stay in OneDrive (trained on W.A. Hazel imagery). Scoring rules were fixed before
any test ran (`evaluate.py`): a detection counts only if its center lies within max(20 px, half the shell's box
diagonal) of the hand-labeled center; each shell matched once; 95% ranges are Wilson intervals.

## The finding that shaped everything

Our only test object was a **sun-bleached shell: bone, chalky white**. From 50 ft it looks like the site's white rocks,
and no living box turtle looks like it (living carapaces are dark brown/black with yellow-orange markings). Models
trained on it learned "small white blob" and fired on rocks. So the final model is trained for **living turtles**: the
real drone shells, traced along their exact outline and repainted in place with real carapace patterns (Tanya's
rescues, the GMU shell), plus outline polygons (shape), plus placed turtles on survey legs 1-2, plus mined false alarms.

## Results

| Test | What it measures | rs_seg_v2 (final) | rs_seg_v1 (this morning) |
|---|---|---|---|
| **B - headline** | Real shells at the 3 held-out spots (rut, half buried, riprap), repainted in place with 3 skins **never used in training** | **13/23 = 57%** (95% CI 37-74%) at score >= 0.25; 52% at >= 0.5; confident (>= 0.7) detections are right 78% of the time | 6/23 = 26% |
| B by spot | rut / half buried / riprap | **7/8 (88%)** / 5/11 (45%) / 1/4 | 1/8 / 4/11 / 1/4 |
| A | The same held-out spots, real bleached-bone shell, unmodified | 0/23 - by design: the model ignores bone-white objects | 0/23 |
| C - supporting only | Living-turtle cut-outs placed on 59 never-trained survey-leg-3 photos (natural ground; 20 man-made placements excluded before scoring) | 58/59 (98%) - **not independent**: the final training data used the same placement method | 27/59 (46%) |
| **D - independent simulation** (Nov 5) | 136 never-trained survey-leg-3 photos, each with one photo of a **real living box turtle the model never saw** (GMU live turtles, Naz's silt-fence turtle, Tanya's field turtles); only on ground a turtle could stand on, every placement checked by eye and approved by Naz before scoring (`TEST_D_PROTOCOL.md`) | **56/136 = 41%** (95% CI 33-50%) at >= 0.25; 22% at >= 0.5; 2.1 false alarms / photo @0.25 | - |
| False alarms | 139 survey-leg-3 photos, never trained on, no turtles | 1.86 / photo @0.25, **0.68 @0.5**, 0.17 @0.7 | 1.23 @0.25 |

**Reading B and D together:** their ranges overlap; on turtles it has never seen, the model finds roughly 40-55%.
D is the larger and more independent test; B is real shells in place. Test D diagnostics (worked out AFTER scoring,
not a headline): each turtle is found nearly always or nearly never (all 80 misses scored zero), so the turtle's look
matters more than the ground. Top-down views were found ~60% (Naz's turtle 3/3); side/front phone views with head and
legs ~33% (a drone always looks straight down, so this part is harder than real flights); Tanya's bright black-and-
yellow turtles 1/8 - a real gap, since the training skins were mostly brown-orange.

App setting: alerts shown at score >= 0.5 (`AERO_MIN_SCORE=0.5`) - one turtle fewer than 0.25 on Test B, ~63% fewer
false alarms. Fusion marks a turtle HIGH when two photos agree at >= 0.7.

**End-to-end check (Naz's Mac, Nov 4):** demo flight = spot 4's 11 real photos with the shell repainted (Test B
procedure) -> `POST /flights/local` -> 4 detections on the turtle in 4 photos (0.61-0.78), fused into one
HIGH-priority alert at the shell; 2 false alarms (one photo) as lower-tier "needs review" alerts.

## Honest limits

- **Target (70% on held-out shells) not met.** Test B 57%, Test D 41%; riprap (white rocks), side views and
  black-and-yellow turtles are the hardest cases. Fix: real living-turtle drone photos for training.
- **No live turtle has been photographed from the drone yet.** B, C and D are simulations built on real ground.
  First live flight: Fri Nov 6, Grayson site, Tanya's turtle, Logan flying, 30 and 50 ft. Test only, never trained on.
- Test D cannot show turtles partly hidden in grass or under cover (a pasted image cannot do that honestly).
- 23 test shells = wide confidence intervals. 100 ft is too high (shell ~16 px).
- One shell, one site, one sunny October morning.
- The live HDMI feed is 1280x720: a turtle at 50 ft is ~8 px, too small to detect live; use the post-flight photos
  (or fly ~20 ft for live mode). `video_test.py` exists but was not run before the freeze.
- Spot 8 (pipe) shells sit in pitch-black shadow - invisible to people and the model; never scored.

## Reproduce

`index_photos` -> label (`label_shells.html`) -> `build_real` -> `reskin` (dataset RS + Test B) -> `test_c --train`
(placements) -> `mine` -> `train ... RS --model yolo11s-seg.pt` -> `evaluate` (A, B with `<work>/test_b`, C with
`--labels <work>/test_c/labels.json`, D with `<work>/test_d --labels <work>/test_d/labels.json`). Commands in each module's docstring.
