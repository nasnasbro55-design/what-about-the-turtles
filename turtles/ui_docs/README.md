# Web app + demo: Huy

**Your job:** the app people actually see. A responder on site uses it on a phone, and the judges see it on a laptop in the pitch.
Read [`../architecture/ARCHITECTURE.md`](../architecture/ARCHITECTURE.md) sections 0, 1, 4, and 6 first.

**Build it as a mobile-friendly web app, not a native app.** It runs in any phone browser, can be added to the home screen like an app, and there's no app store, no Xcode or Android Studio, and nothing to install. Same "app" experience, a fraction of the work.

## Screens

1. **Map:** the site with a pin per alert.
   - Red = `high`, amber = `review`, gray = closed (`confirmed` / `relocated` / `false_positive`).
   - Leaflet + OpenStreetMap is free and simple.
2. **Alert list:** newest first, filterable by status, showing the count of open alerts.
3. **Alert detail:**
   - Thumbnail, confidence, a sensors badge (`RGB` or `RGB + Thermal`), time, and note.
   - A **Navigate** button that opens Google Maps at the pin's lat/lon.
   - Buttons: **Confirmed**, **Relocated**, **False positive**. Each sends `PATCH /alerts/{id}` with `{"status": ..., "note": ...}`.

4. **Next flights panel:** the planner's recommendations from `GET /plan` (`mock/windows.json` for now).
   - Best first: zone name, day and time, a thermal badge if `thermal_ok`, and the `reasons` as bullets.
   - On the map, draw each work zone from `GET /zones` (`mock/zones.json`) as a shaded area labeled with its work and start date, like "Clearing, Tue 7 AM".
   - This is what makes the pitch "we find turtles **before** the bulldozer gets there," so give it a prominent spot.

5. **Heat map layer (stretch, after screens 1–4 work):** a toggle on the map that shades cells from `GET /heatmap` (`mock/heatmap.geojson` for now) by `likelihood`. Leaflet's `L.geoJSON` with a style function does this in a few lines. Show `reasons` on tap.

## Data

- **Start today** with `turtles/architecture/mock/alerts.json`. It has 4 alerts covering every case (high with thermal, high from two photos, review, false positive).
- When Ethan's API is up, swap the JSON file for `GET {API_BASE}/alerts`. Keep `API_BASE` in one place so it's a one-line change.
- The alert fields are defined in `turtles/contracts.py`. Don't rename them on the frontend.

**Tech:** whatever you're fastest in (React, or plain HTML/JS). Speed matters more than framework.

## Also yours: demo materials

- A 2–3 minute demo video: drone flight footage, then alerts popping up on the map, then a responder confirming one.
- Screenshots for the slides.
- Recorded on real Grayson flight data once we have it, by Fri Oct 30.

## Milestones

| Date | Done means |
|---|---|
| Fri Oct 16 | Wireframe sketch posted in Discord (paper photo is fine) |
| Tue Oct 20 | Map + list + detail render from `mock/alerts.json`, and it works on your phone |
| Fri Oct 23 | Wired to Ethan's API; status buttons actually save |
| Fri Oct 30 | Demo video recorded |

**Don't worry about:** models, the drone, or the backend internals.
