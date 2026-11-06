# A.E.R.O. detector - results (Nov 4-5, 2026)

Final model: **`rl_seg_v3`** (Nov 5 evening; was `rs_seg_v2`) - YOLO11s segmentation, 640 px tiles at native drone resolution, every photo shadow-lifted
(CLAHE) before detection. Weights stay in OneDrive (trained on W.A. Hazel imagery). Scoring rules were fixed before
any test ran (`evaluate.py`): a detection counts only if its center lies within max(20 px, half the shell's box
diagonal) of the hand-labeled center; each shell matched once; 95% ranges are Wilson intervals.

## Update, Nov 5 evening: model v3 (`rl_seg_v3`)

Test D showed v2 missed side views (head and legs out) and Tanya's black-and-yellow turtles. v3 = v2 retrained 2.5 h
on dataset RL: RS plus 815 tiles of real LIVING turtle photos placed on survey legs 1-2 (`build_living.py`). Six
turtles (27 Test D photos) were held out of v3 and the decision rule was fixed BEFORE training: v3 replaces v2 only
if it beats v2 on Test B and on the held-out turtles.

| Check | v2 (`rs_seg_v2`) | v3 (`rl_seg_v3`) |
|---|---|---|
| **Test B** (unchanged: real shells in place, skins never trained on) @0.25 | 13/23 = 57% (37-74%) | **17/23 = 74% (54-87%)** |
| Test B: rut / half buried / riprap | 7/8 / 5/11 / 1/4 | **8/8 / 8/11** / 1/4 |
| Test B @0.5 (app setting) / @0.7 | 52% / 30% | **65% / 43%** |
| Held-out Test D turtles @0.25 | 11/27 = 41% | 27/27 = 100% (see caveat) |
| False alarms, 139 turtle-free leg-3 photos, @0.25 / @0.5 / @0.7 | 1.86 / 0.68 / 0.17 | 3.88 / 1.39 / 0.29 |

Read honestly:
- **Test B is the number to trust**: 74%, above the 70% target by the agreed definition, but the 95% range runs
  down to 54%, and v3 is the 5th model measured on the same 23 shells (a small optimistic bias).
- The held-out 100% is NOT a headline: those turtles were pasted the same way as v3's training turtles (v3 may partly
  recognize the paste), and GMU photos may show the same few physical turtles as the training ones. Full Test D is no
  longer independent for v3.
- False alarms about doubled. At the app's 0.5 floor that is ~1.4 per photo ("needs review" tier); HIGH still needs
  two photos >= 0.7.

## The finding that shaped everything

Our only test object was a **sun-bleached shell: bone, chalky white**. From 50 ft it looks like the site's white rocks,
and no living box turtle looks like it (living carapaces are dark brown/black with yellow-orange markings). Models
trained on it learned "small white blob" and fired on rocks. So the final model is trained for **living turtles**: the
real drone shells, traced along their exact outline and repainted in place with real carapace patterns (Tanya's
rescues, the GMU shell), plus outline polygons (shape), plus placed turtles on survey legs 1-2, plus mined false alarms.

## Results (v2 and earlier; v3 above)

| Test | What it measures | rs_seg_v2 (Nov 4 final) | rs_seg_v1 (this morning) |
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

- **Target (70%):** v3 reaches 74% on Test B (54-87%); v2 was 57%, and v2 scored 41% on Test D. Hardest cases: riprap (white rocks, still 1/4), side views,
  black-and-yellow turtles. More false alarms with v3. Fix: real living-turtle drone photos for training.
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
v3: `build_living` -> `train <work> RL --hours 2.5 --model <work>/runs/rs_seg_v2/weights/last.pt --name rl_seg_v3`;
Test B with `--no-survey`; false alarms from a run on the original data folder.
