# Flight planner: Naz

**The question it answers:** *where should we survey today, and at what time?* Every other team detects turtles. This plans the search around the construction schedule and the conditions when turtles are easiest to see, so the crew finds them **before** equipment reaches them.

**Output, shown in the app:**
> Fly **North lot** Sun 4:30–6:00 PM: clearing starts Tue 7:00 AM; ground cooling before sunset gives a good thermal window; dry, light wind.

## Inputs

| Input | Source | Format |
|---|---|---|
| Zones with scheduled work | W.A. Hazel (ask Tanya/Logan for the Grayson clearing/grading schedule) | `Zone` in `turtles/contracts.py`; the polygon is drawn on the map |
| Weather forecast | [Open-Meteo](https://open-meteo.com/en/docs): free, no API key for non-commercial use | hourly temperature, ground-surface temperature, sun, cloud, rain, wind |
| Turtle activity patterns | **Tanya.** She's the expert; we don't guess | rules in `ACTIVITY` in `planner.py` |
| Past sightings (optional) | Tanya's archive (dates + site folders) | CSV: date, site, zone/notes |

## Output

`list[FlightWindow]` (see `turtles/contracts.py`), best first. Each one has a zone, a start and end time, `priority` (0–1), `thermal_ok`, and `reasons` in plain English. Ethan serves it at `GET /plan?site_id=`, and Huy shows it as a "Next flights" panel. The mock is in `turtles/architecture/mock/windows.json`.

## Scoring v1

For each zone and each forecast hour:

1. **Can we fly?** Daylight, wind under 8 m/s, no rain. If not, skip the hour.
2. **Urgency:** hours until equipment arrives in the zone. Under 24 h = 1.0, under 72 h = 0.7, under a week = 0.4, otherwise 0.1. Work already started = 0.
3. **Thermal OK?** A hypothesis from our Oct 13 test: turtles show up when they're warmer than the ground. Count it as yes when it's been sunny recently (enough to bask) and the ground surface is cooling below air temperature, as in late afternoon. Overcast or rain = no. Only matters on a thermal flight.
4. **Activity:** Tanya's rules (for example, whether turtles move more after rain or in certain temperatures). It stays at 1.0 until she answers.
5. **Priority** = urgency × (0.6 + 0.4 if thermal OK) × activity.

Then merge consecutive good hours into windows, keep the top few per zone, and write one reason per factor.

**Already written in `planner.py`:** `fetch_forecast()` and `urgency()`.
**Yours to write:** `flyable()`, `thermal_ok()`, `plan()`.

## Stretch 1: turtle-likelihood heat map (start after `plan()` works)

A map of the site and its surroundings, shaded by how likely turtles are to be there. It tells the crew where to fly first, and in the off-season, where to sweep before trees get cleared (trees are cut Nov 15 – Apr 1, while turtles are dormant; confirm with Tanya before pitching this).

**Inputs, all free:**

| Layer | What it adds | Where to get it |
|---|---|---|
| **NDVI (vegetation)** | Wooded and green areas around the site = turtle habitat | USDA NAIP aerial imagery has a near-infrared band (Virginia 2021, 4-band, ~0.6 m). Download a 4-band tile for the site, e.g. from Microsoft Planetary Computer (`naip` collection, free), then NDVI = (NIR − Red) / (NIR + Red) per pixel. |
| **Habitat edge distance** | Turtles leave habitat into the site and flee back to the edges | Computed from the NDVI layer: distance from each cell to the nearest vegetated area |
| **Haul roads + site edges** | Where Tanya finds injured and dead turtles | From Clarke/Logan's site layout, or drawn by hand on the map |
| **Detections + confirmed alerts** | Where turtles have actually been found | Our own alerts (`status` = confirmed or relocated count most) |

**Method v1:**
- Lay a 10 m grid over the site plus a ~300 m buffer.
- For each cell, score each layer 0–1.
- likelihood = weighted sum, rescaled 0–1.
- Weights are judgment calls. Start equal, then tune with Tanya, and say so honestly in the pitch.

**Output:** a GeoJSON `FeatureCollection` of grid-cell polygons with properties `{"likelihood": 0-1, "reasons": [...]}`. Leaflet draws it directly as a shaded layer. Example: `turtles/architecture/mock/heatmap.geojson`. Ethan serves it at `GET /heatmap?site_id=`.

**Note:** NAIP may be a year or two old, so it shows the habitat *before* construction. That's actually what you want: it shows where the turtles came from.

## Stretch 2: "the drone couldn't see here" map

- From the survey photos, flag ground hidden under brush or canopy, using a simple vegetation index on the RGB pixels (excess green = 2G − R − B). No infrared needed.
- Output a GeoJSON of `not_checked` polygons.
- The app shows "We checked 85% of the site; walk these areas on foot."
- Being upfront about blind spots is hard for a judge to argue with.

## Proving it works (this is what makes it pitch-worthy)

- On flight day, note whether turtles actually showed up on thermal. Compare that against what the planner predicted for that hour. Even one real data point beats a claim.
- Show the before and after: "Clearing was scheduled Tuesday. The planner sent us Sunday at 4:30. We found X turtles in that zone."

## Milestones

| Date | Done means |
|---|---|
| Thu Oct 16 | Asked Tanya for activity patterns + sightings, and the Grayson work schedule |
| Mon Oct 20 | `fetch_forecast` + `flyable` + `urgency` working; prints ranked hours for the mock zones |
| Fri Oct 23 | `plan()` returns `FlightWindow`s; Ethan serves them, Huy shows them |
| Before the Grayson flight | Real zones + Tanya's rules in; the planner picks the flight time |
| Mon Oct 27 (stretch) | Heat map from NAIP NDVI + roads/edges, served at `/heatmap` and shown in the app |
| Thu Oct 29 (stretch) | Coverage map from the real Grayson photos |
