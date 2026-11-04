# Detection

`detector.py` is the only thing the backend calls: `detect(frame, path) -> [Detection]` (and `boxes(image)`).
It slices each full 5280x3956 photo into overlapping 640 px tiles, shadow-lifts the photo first if the model's run
folder says so (`preprocess.txt`), merges boxes, and maps each box center to GPS with `turtles.geo` (tilt-aware).

- Weights: `$AERO_WEIGHTS` (default: OneDrive `models/aero_turtle.pt`). **Keep weights inside their run folder** -
  `preprocess.txt` beside it turns on the shadow lift the model was trained with.
- Alert floor for the app: `$AERO_MIN_SCORE` (default 0.25; demo 0.5).
- Results and limits: [`eval/RESULTS.md`](eval/RESULTS.md).

| Module | What |
|---|---|
| `index_photos.py` | every drone photo -> frames.csv (spot, split, height, tilt, GPS) |
| `build_real.py` | dataset R: real shell tiles, own-scene + survey negatives |
| `reskin.py` | trace each shell's outline, repaint it as a living turtle (dataset RS, polygons) + Test B |
| `test_c.py` | Test C (held-out skins, leg 3) and `--train` placements (training skins, legs 1-2) |
| `build_dataset.py`, `sprites.py` | first approach (pasted sprites) - kept for the record; it taught the model paste artifacts |
| `mine.py` | hard negatives: every false alarm on survey legs 1-2 becomes an empty tile |
| `train.py` | Apple-GPU training with a time budget |
| `evaluate.py` | fixed-protocol scoring with 95% intervals |
| `demo_flight.py` | flyable Test B folder (original drone metadata spliced back) |
| `video_test.py` | detector on the recorded HDMI live feed |
| `run_flight.py` | stand-alone flight -> alert pack (the backend's `pipeline.py` is the main path) |

Thermal: `detect_thermal` returns [] - phase 2 (ground ran warmer than air all of Oct 24).
Licensing: Ultralytics is AGPL-3.0 - fine for the competition; flag before W.A. Hazel uses it commercially.
