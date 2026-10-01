# What About the Turtles

**Status:** Provisional — we're in Concept Development (Weeks 3-4 of Challenge+X), not the build phase yet. Details below will firm up as hardware/approach gets finalized.

This project is part of **Challenge+X, Round 3**, sponsored by **William A. Hazel, Inc.** and **Aero Animal Rescue** (Tanya Finch's turtle rescue program).

## The problem

Box turtles get trapped and killed on active construction sites after silt fencing goes up — they try to escape, run into the fence, and can't get back to food, water, or shelter. We're partnering with William A. Hazel and Aero Animal Rescue to catch this before it happens.

## The idea

A drone flies a scripted pattern over a site's perimeter, capturing footage that AI models scan for turtles:

- **RGB detection** — spots turtles by shape/pattern against dirt, debris, and grass
- **Thermal detection** (pending validation — see Open Questions) — flags heat differentials that could be a turtle

When a detection is confirmed, the system alerts the site lead with a location and photo so someone can respond, consistent with how Aero Animal Rescue already works (nearest worker, ~15 min response).

## Site scale

Confirmed by W.A. Hazel: average site is **40 acres**, roughly **1 mile of perimeter** to cover. This is why a drone patrol is a stronger fit than a fixed-camera grid — covering that distance with stationary cameras would take 15-50+ units.

The solution is meant to be **scalable** across multiple companies and sites, not a one-off for W.A. Hazel specifically.

## Team — TNUX

| Name | Role | Responsibilities |
|---|---|---|
| **Nasrullah "Naz" Hussain** (lead, POC) | Technical lead / pilot | Drone & thermal feasibility research, FAA Part 107 study + certification, drone pilot for demo, system architecture, fusion logic design, main contact with Tanya/John |
| **Jake Dwight Chan Israel** | Detection models | Builds and evaluates the RGB object-detection model on real turtle photos, builds the thermal detection model once validation data exists, owns the eval harness scoring both |
| **Ethan Cooper** | Backend & alerts | Ingests drone footage/frames, runs the fusion logic, turns a detection into a real-time alert, builds the API, reviews/merges PRs |
| **Huy Ngoc Minh Truong** | Flight logistics & presentation | Flight logistics and safety documentation, dashboard (visualizing flagged detections), demo video, docs, candidate for CAD/3D-printing work |

## Schedule (Challenge+X program weeks)

| Week | Dates | Phase | What we're doing |
|---|---|---|---|
| 1 | Sep 12-18 | Kickoff & Team Formation | Done |
| 2 | Sep 19-25 | Challenge Deep Dive & Early Mentorship | Done |
| 3-4 | Sep 26-Oct 9 | **Concept Development & Sponsor Check-ins** | **← We are here.** Finalizing approach, thermal validation, FAA cert prep, site visit scheduling |
| 5-6 | Oct 10-23 | Iteration & Real-World Validation | Build detection models, drone pipeline, alert system; first flight test |
| 7 | Oct 24-30 | Final Build & Pitch Prep | Polish, dashboard, rehearse pitch |
| 8 | Oct 31-Nov 7 | Final Showcase & Awards | Demo day |

## Open questions (resolving during concept development)

- Thermal feasibility on turtles (ectotherms don't generate body heat — testing before committing to hardware)
- Final hardware: buy a drone, or borrow one through GMU's Autonomous Swarms club
- FAA Part 107 certification path and timeline
- Drone flight permission over an active W.A. Hazel site
- Post-competition handoff (who flies it if W.A. Hazel wants to keep using it)

## Repo structure
turtles/
├── architecture/ — system design, research notes
├── detection/ — detection models, eval
├── backend/ — API, alerting, fusion logic
├── ui_docs/ — dashboard, docs, demo materials
└── data/ — training/test images (not committed — see .gitignore)
