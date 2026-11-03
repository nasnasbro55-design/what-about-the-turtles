# What About the Turtles

**Finding box turtles on active construction sites before the equipment does.**

Challenge+X Round 3 · Team TNUX · Sponsored by **William A. Hazel, Inc.** and **Aero Animal Rescue (What About the Turtles?)**

**Status:** building (Weeks 5–6 of 8). Final showcase Oct 31 – Nov 7, 2026.

---

## The problem

Eastern box turtles get crushed along haul roads on construction sites, or flee to the edges and die of heat, exhaustion or predators. Sites average about 40 acres. Checking that on foot means roughly 54 km of walking, around 13 hours, for one person.

## What we're building

A system that tells a crew **where and when to look**, finds turtles in drone photos, and puts them on a map so someone can move them to safety.

1. **Plan.** A flight planner combines the site's work schedule, the weather forecast, and Tanya Finch's turtle-activity knowledge. Her site-visit records show box turtles turn up on or right after rainy days. Example output: *"Fly the haul roads Saturday 9 AM. It rained Friday and it's 72°F."*
2. **Find.** W.A. Hazel's drone photographs the site from straight above. Our detection model flags likely turtles, each with a precise GPS location.
3. **Confirm.** A responder opens the web app on their phone, walks to the pin, and marks it *relocated* or *false alarm*. Every answer becomes new training data.

**Hardware:** W.A. Hazel's DJI Mavic 3 Enterprise, flown by their geospatial engineer Logan Lavalette (FAA Part 107). Its zoom camera gives a closer look at flagged spots without flying low. *(Pending final Hazel approval.)*
**Thermal:** we tested a handheld thermal camera. It only shows a turtle when the turtle is warmer than the ground. Whether thermal is part of this season's demo is still being decided.
**Test site:** Grayson Overlook, Gainesville, VA. Tanya's records show 6 box turtles found there in June 2026.

## What we deliver on Nov 7

- **The app:** drone photos in, turtle pins on a map, responder buttons.
- **The planner:** recommended flight times and zones.
- **Proof:** results from a real flight at Grayson (found X of Y).
- **The pitch and a demo video.**

## Team

| Name | Role | Works in | Starts with |
|---|---|---|---|
| Nasrullah (Naz) Hussain | Team lead, architecture, flight planner, sponsor contact | `turtles/planner/`, `turtles/contracts.py` | [Planner brief](turtles/planner/README.md) |
| Jake Dwight Chan Israel | Turtle detection model + evaluation | `turtles/detection/` | [Detection brief](turtles/detection/README.md) |
| Naz (from Ethan, Nov 3) | Backend: photo ingest, alert logic, API | `turtles/backend/` | [Backend brief](turtles/backend/README.md) |
| Huy Ngoc Minh Truong | Web app (map + alerts) and demo video | `turtles/ui_docs/` | [App brief](turtles/ui_docs/README.md) |
| Logan Lavalette (W.A. Hazel) | Drone pilot | – | – |

**Everyone, read first:** [`turtles/architecture/ARCHITECTURE.md`](turtles/architecture/ARCHITECTURE.md). It covers how the pieces connect and the data formats we all share.

## Schedule

| Week | Dates | Phase | Our milestones |
|---|---|---|---|
| 1–2 | Sep 12 – 25 | Kickoff, deep dive | Sponsor meetings, photo archive review |
| 3–4 | Sep 26 – Oct 9 | Concept development | Thermal test, concept locked |
| **5–6** | **Oct 10 – 23** | **Iteration and real-world validation** ← we are here | **Oct 16:** data formats frozen · **Oct 20:** each piece works on fake data · **Oct 23:** full pipeline works without the drone |
| 5–6 | Sat Oct 17 or 24 (TBD) | Site visit | Grayson flight with Logan |
| 7 | Oct 24 – 30 | Final build and pitch prep | **Oct 30:** demo freeze, demo video recorded |
| 8 | Oct 31 – Nov 7 | Final showcase | Pitch |

## Quick start

```
git clone https://github.com/nasnasbro55-design/what-about-the-turtles.git
cd what-about-the-turtles
python3 -m turtles.contracts        # checks the fake data matches our shared formats
pip3 install pytest && python3 -m pytest -q
```

There's fake but realistic data in `turtles/architecture/mock/` (alerts, detections, zones, flight windows), so everyone can build without waiting on the drone.

## Repo structure

```
turtles/
├── contracts.py      shared data formats (everyone imports these)
├── geo.py            photo pixel -> GPS location math
├── architecture/     ARCHITECTURE.md + mock data
├── planner/          Naz: where and when to fly
├── detection/        Jake: turtle detection model
├── backend/          ingest, alert logic, API (Naz)
├── ui_docs/          Huy: web app, demo materials
└── data/             real photos (never committed; shared through Drive)
tests/                python3 -m pytest -q
```

## Working rules

- Pull before you start (`git pull --rebase`). Never `git push --force`.
- Changing anything in `turtles/contracts.py` needs the whole team's OK.
- No photos or personal data in the repo. Site imagery belongs to W.A. Hazel.
- No purchases without W.A. Hazel's written approval first.
