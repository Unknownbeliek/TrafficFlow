# Trackflow — Traffic Flow & Vehicle Dynamics Simulator

CM PBL · **Computational Methods Lab (ES-251)** · Session 2026-27 (Odd Semester)

A live, browser-based microscopic traffic simulator for five Delhi-NCR interchanges. A C++17
engine moves individual vehicles through time with Runge–Kutta integration, reconstructs
missing detector readings with Newton divided differences, and pins threshold-crossing
instants with a safeguarded Newton–Raphson solver. A Node bridge streams engine state over
WebSocket and a React dashboard draws each interchange over satellite imagery in the working
style of PTV Vissim / Aimsun Next.

```
browser  ←socket.io←  server/ (Node)  ←NDJSON over stdio←  engine/ (C++17)
   React dashboard        bridge, 10 Hz ticker              IDM + RK4, signals, solvers
```

## Run it

```bash
# 1. engine (needs only g++ and make)
cd engine && make -j

# 2. dashboard
cd ../web && npm install && npm run build

# 3. bridge (serves the built dashboard and the API)
cd ../server && npm install && npm start
#    → http://localhost:3000
```

`./run.sh` does all three steps in order.

## What the demo does

* **Five interchanges** — Kalindi Kunj, Connaught Place, ITO, Gaur City Char Murti,
  Botanical Okhla — from one site selector.
* **Signals** cycle green → amber → red with a live countdown; vehicles stop at the line,
  discharge in platoons and clear on amber only when they can no longer stop safely.
* **Live demand** — *Natural* runs the surveyed volumes, *Manual* puts a 0–200 % slider on
  every approach; changes take effect without restarting the simulation.
* **Vehicles** are seven classes (car, taxi, two-wheeler, auto, LCV, truck, bus) drawn
  top-down at true length in metres, colour-coded and individually inspectable.
* **Heatmap** colours each link by density ratio (teal → amber → crimson), with LOS badges.
* **Alerts** carry a *computed* crossing time from the root finder, not a frame time.

## Numerics (the graded part)

```bash
cd engine && ./trackflow verify reports      # or: make verify
```

| Experiment | What it proves |
|---|---|
| RK4 / RK2 / Euler on `v' = a − k v²` | measured order 1.00 / 2.02 / 4.02 against the closed form |
| Newton divided differences, 4 / 5 / 9 samples | linear vs full-degree vs sliding-window error, incl. Runge blow-up |
| Newton–Raphson vs bisection vs secant | iterations to `1e-4`, with the guarded solver in production |
| Tangential root `(t−5)²` | why a standstill is *not* solved as a root of `v = 0` |

The same numbers appear in the dashboard under **numerics · error analysis**, read from
`engine/reports/*.csv`. Nothing in the report is transcribed from a screenshot.

## Repository map

```
engine/            C++17 engine (the only place that simulates anything)
  src/solvers.hpp    Newton divided differences, safeguarded NR, bisection, secant
  src/sim.cpp        IDM + RK4, signal gating, transfers, alerts
  src/verify.cpp     the ES-251 verification suite (writes reports/*.csv)
  src/main.cpp       menu-driven CLI + NDJSON serve mode
sites/<id>/        network.json, calibration.json, survey.csv, notes.md per interchange
server/            Node bridge: engine process, 10 Hz ticker, socket.io, REST
web/               React + Tailwind dashboard (builds to webroot/)
tools/             build_sites.py (generator), preview_site.py, render_frame.py
docs/              algorithms.md (flowcharts), PRD pointer
section_img/       satellite imagery; section_img/<site>/base.png is the one the app uses
```

## Adding or correcting a site

1. Drop the clean crop at `section_img/<id>/base.png` (1920×1080, no browser/OS chrome).
2. Edit the anchors in `tools/build_sites.py` (or hand-edit `sites/<id>/network.json`).
3. `python3 tools/build_sites.py`
4. `python3 tools/preview_site.py <id>` — draws the traced lanes back onto the imagery.
5. `python3 tools/render_frame.py <id> --seconds 120` — renders a simulated frame without a browser.

Step 4 is the calibration loop: if the coloured lane lines do not sit on the road in the
photo, the trace or the metres-per-pixel value is wrong.

## Status

Working: engine, all three methods with verification, five site definitions, bridge,
dashboard, alerts, live demand control.

Known gaps, in the order they matter:

1. **Survey data is placeholder.** Every `survey.csv` is marked `synthetic`. Run the
   protocol in the PRD (§13.1) and replace the counts; the UI should then drop its
   assumption badge.
2. **Geometry is traced, not surveyed.** Kalindi Kunj and ITO sit on their roads; CP's
   rings and Botanical's ramps are close but crude. Use `preview_site.py` to refine.
3. **Imagery** is still the original full-desktop screenshots — replace with the crops.
4. Lane-changing and two-wheeler filtering are not implemented (lane discipline only).
