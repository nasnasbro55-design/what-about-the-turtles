# Detection: Jake

**Your job:** find turtles in aerial RGB photos, and find hot spots in handheld thermal photos.
Read [`../architecture/ARCHITECTURE.md`](../architecture/ARCHITECTURE.md) sections 0, 4, 7, and 8 first.

## Your interface (`detector.py`)

```python
detect(frame: Frame, image_path: str) -> list[Detection]          # aerial RGB
detect_thermal(frame: Frame, image_path: str) -> list[Detection]  # handheld FLIR
```

The backend calls only these two functions. As long as they return valid `Detection`s (see `turtles/contracts.py`), everything else can change.

- **bbox:** pixels in the original image.
- **lat/lon:** for RGB, use `turtles.geo.pixel_to_latlon(frame, cx, cy)` with the bbox center. For thermal, use `frame.lat` / `frame.lon`, which is the phone's GPS.
- **Nothing found:** return `[]`, never `None`.

## RGB model: suggested path

1. **Label.**
   - Pull turtle photos from the Drive archive (Waxpool Road, Hartland, Minnieville, Bull Run PO Road).
   - Draw boxes in Roboflow, Label Studio, or CVAT, and export in YOLO format.
   - Include photos with **no** turtle (site dirt, debris, rocks). The model needs those to learn what to ignore.
2. **Make aerial-style data.**
   - Archive photos are side-on and close up; drone photos are top-down with small turtles.
   - Shoot phone photos straight down over turtles and look-alikes (rocks, pinecones, clods).
   - Shrink them so turtles are 25–60 px across (ARCHITECTURE section 8). This matters more than model choice.
3. **Train.** Fine-tune a small pretrained detector, for example Ultralytics YOLO (nano/small).
   - Licensing note: Ultralytics is AGPL-3.0. That's fine for the competition. Flag it if W.A. Hazel wants to use the system commercially later.
4. **Small objects.** A 48 MP photo is 8064 × 6048. Cut it into overlapping ~1024 px tiles, detect on each tile, and map boxes back to full-image pixels. The SAHI library does this.
5. **Score calibration.** Fusion treats 0.25 as the floor and 0.7 as "strong". Check that your scores roughly mean that on your test set.

## Thermal: no machine learning needed

- FLIR radiometric JPGs store a temperature per pixel. One way to read them is the `flirimageextractor` Python package.
- Flag a blob that is **2 °C or more warmer than the surrounding ground** and at least a few pixels big.
- Score = how far above the background it is, scaled to 0–1.
- Start with the 2 °C threshold and tune it with real images.

## Evaluation (you own this)

- Hold out a test set you never train on.
- Report **recall first** (missing a turtle is the costly error), then precision, at score thresholds 0.25, 0.5, and 0.7.
- Write results to `turtles/detection/eval/RESULTS.md`. These numbers go straight into the pitch.

## Milestones

| Date | Done means |
|---|---|
| Thu Oct 16 | At least 50 boxes labeled; you've read the contracts and raised any problems |
| Mon Oct 20 | `detect()` returns real Detections on 20 photos (any quality) |
| Fri Oct 23 | First eval numbers; detector plugged into Ethan's pipeline |
| After Grayson flight | Retrained on real aerial photos, new eval numbers |

**Don't worry about:** the drone, the API, or the web app.
