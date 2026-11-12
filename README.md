# Trackflow

A live, browser-based **microscopic traffic simulator** for five Delhi-NCR
interchanges, built in the working style of PTV Vissim and Aimsun Next.

A C++17 engine advances every vehicle through time with Runge-Kutta integration,
rebuilds missing detector readings with Newton divided differences, and pins down
threshold-crossing instants with a safeguarded Newton-Raphson solver. A Node
bridge streams engine state over WebSocket; a React dashboard draws each
interchange over its satellite capture: lane geometry, signal heads, lane-level
vehicle glyphs, a network object tree and an attribute inspector.

**CM PBL · Computational Methods Lab (ES-251) · Session 2026-27**

---

## Quick start

```bash
# 1. build the engine (C++17, no dependencies)
cd engine && make && cd ..

# 2. regenerate the verification tables (optional, already committed)
cd engine && ./trackflow_engine --verify --data ../site-data && cd ..

# 3. the web app
npm install
npm run build          # bundles client/ into dist/
npm run dev            # http://localhost:5173
```

The bridge spawns the engine itself, so nothing else needs starting. If the engine
binary is missing, `/api/health` reports `engine_binary: false` and the UI shows
"engine offline".

### Without the browser UI

```bash
cd engine
./trackflow_engine --run 600 --site connaught_place --data ../site-data
./trackflow_engine --verify --data ../site-data      # writes verification/*.csv
./trackflow_engine --site ito --data ../site-data    # numbered menu
```

---

## The five interchanges

| site | type | what it stresses | links | peak demand |
| --- | --- | --- | --- | --- |
| **Kalindi Kunj Bridge** | river crossing bottleneck | heterogeneous lane blocking — one truck sets the pace | 72 | 11,924 veh/h |
| **Connaught Place** | Inner + Outer Circles, 6 radials | continuous curvature, multiple coordinated signals | 182 | 16,848 veh/h |
| **ITO** | multi-directional urban grid | standstill detection, `v(t) = 0` gridlock alerts | 50 | 24,901 veh/h |
| **Gaur City Char Murti** | signalised roundabout | multi-approach demand control, ring discharge | 73 | 5,446 veh/h |
| **Botanical Okhla** | cloverleaf | curvature-limited speed on 19 m loop ramps | 36 | 17,401 veh/h |

All five build with **zero topology problems** from `tools/build_sites.py`.

---

## Architecture

```
section_img/            committed satellite captures (1920×1080, North-up)
        │
        ▼
tools/                  network compiler (Python)
  geo.py                metre-space geometry, exact start/end points
  network.py            schema-4 model, vehicle classes, junction wiring, validation
  rings.py              circles: entry, exit, ring-to-ring penetration
  sites.py              the five builders
  build_sites.py        CLI → site-data/<id>/{network,survey,calibration,notes}
        │
        ▼  site-data/<id>/network.json
engine/                 simulation (C++17)
  json.h                dependency-free reader
  geometry.h            arc-length polylines, curvature
  numerics.h            RK4 / RK2 / Euler, Newton DD, safeguarded NR
  network.h/.cpp        model loading
  sim.h/.cpp            IDM, signals, demand, transfer, alerts, snapshots
  verify.cpp            the PRD §12 verification suite
        │
        ▼  line-oriented JSON over stdio
server/index.js         Node bridge: spawns the engine, relays over WebSocket
        │
        ▼  WebSocket /ws + REST /api/*
client/                 React 19 + Tailwind 4 dashboard
```

### Visual language

| token | value | use |
| --- | --- | --- |
| background | `#0f172a` | canvas and page |
| panel | `#111c2e` | side columns, top bar |
| hairline | `#1f2f45` | dividers |
| text | `#e5edf7` | primary |
| muted | `#8ba0b8` | labels, secondary |
| accent | `#38bdf8` | selection, active controls |
| heat | `#10b981` → `#f59e0b` → `#ef4444` | speed / density overlay |

Inter for the interface, JetBrains Mono for every number.

### The dashboard

* **Top bar** — site switcher, transport (run / pause / single-step / reset),
  0.5×–5× playback, view mode, overlay selector, live counters.
* **Network object tree** — carriageways, individual lane-level links with live
  speed, signal controllers with a countdown pill, vehicle classes, heat groups,
  scenarios.
* **Map** — satellite imagery under a calibrated transform, lane network, signal
  heads, vehicle glyphs drawn with class-accurate dimensions, scale bar, zoom and
  pan, hover pick, click to inspect.
* **Inspector** — link geometry, surveyed vs drawn length, class mix, detector
  chain, reconstructed speed profile; signal plan and live state; scenario details.
* **Demand** — surveyed / manual / scripted modes, hour-of-day slider, global and
  per-approach multipliers (0–200 %), one-click scenarios.
* **Numerics** — integrator switch, step size, state hash, interpolation report,
  and a pointer to the verification CSVs.
* **Alerts** — Newton-Raphson alerts with their iteration and bisection counts.

---

## The numerics

All three graded methods live in `engine/src/numerics.h` with the full derivation
in [`docs/algorithms.md`](docs/algorithms.md).

**RK4** integrates `ds/dt = v`, `dv/dt = a_IDM + a_curve + a_signal + a_limit`.
Steps that would drive `v` negative are shortened to the exact stopping instant
instead of clamped, so the order survives in the stop-and-go regime. Euler and RK2
are available behind a runtime switch purely for comparison.

**Newton divided differences** rebuild the speed profile between detector
checkpoints: degree capped at 4, a sliding window of the five most recent
consecutive samples, extrapolation beyond the sampled span flagged rather than
hidden, and any gap wider than 30 % of the link length marked low confidence.

**Safeguarded Newton-Raphson** finds the instant a threshold is crossed, with a
bisection fallback whenever an iterate leaves the bracket or the derivative
degenerates. When the function only *touches* zero — a vehicle that decays to a
standstill and stays there — no bracket exists at all, so the solver minimises
`|f|` instead. That is the guard the PRD asks to demonstrate.

### Verification results

`cd engine && ./trackflow_engine --verify --data ../site-data`

| test | result |
| --- | --- |
| RK convergence on `v' = a − kv²` | slopes **0.85 / 2.12 / 4.10** for Euler / RK2 / RK4 |
| Newton DD, 4 → 9 samples | max error **2.14 → 0.012** |
| root finding, crossing case | Newton 9.4e-13, bisection 9.8e-5, safeguarded 9.4e-13 |
| root finding, grazing case | bisection fails (0.90 error), safeguarded **5.3e-13** |
| Euler vs RK4 on a live scenario | total delay **812 vs 566** vehicle-seconds |

Output lands in `engine/verification/`:

| file | contents |
| --- | --- |
| `convergence.csv` | dt sweep, final speed, error, fitted slope per method |
| `interpolation.csv` | points, window, degree, max/rms error, span covered |
| `rootfinding.csv` | every method × every case, iterations, bisections, residual |
| `scenario_comparison.csv` | integrator × step size on one site, delay metrics |

---

## Data honesty

* Turning counts, lane counts and signal timings are **engineer's estimates
  reconstructed from published counts and video surveys** of these junctions, not
  a fresh field survey. Each site's `notes.md` states this.
* Geometry is checked automatically: every link's drawn length must be within 5 %
  of its surveyed length (worst observed: 3.09 %), and every turned pair must join
  within 1.2 m.
* Demand is movement-level, split from the leg inflow by the surveyed turn shares,
  so `survey.csv` reconciles to the network by construction.
* Vehicle dimensions, free-flow speeds and PCU factors follow PRD §7 and IRC 106.

---

## Repository layout

```
README.md              this file
docs/algorithms.md     the four algorithms, flowcharts, verification tables
section_img/           11 committed satellite captures
tools/                 network compiler
site-data/<id>/        network.json, survey.csv, calibration.json, notes.md
engine/                C++17 engine and verification suite
server/index.js        Node bridge
client/                React dashboard (app.jsx, canvas.jsx, panels.jsx)
verification/          generated CSVs (engine/verification/)
```

## Controls reference

| control | effect |
| --- | --- |
| `▶ / ❚❚` | start / stop the animation clock (client-side) |
| `⏸` | engine pause (`pause` / `resume`) |
| `step` | advance two integration steps (0.1 s) |
| `0.5× 1× 2× 5×` | simulated seconds per wall second |
| `satellite / schematic` | imagery underlay or grid |
| `speed / density / off` | link colouring |
| wheel | zoom · drag | pan · `fit` | recentre |
| click a lane | inspect it and run the divided-difference reconstruction |

## Licence and attribution

Satellite imagery is included for coursework and must be replaced with a single
consistent, openly licensed source (Bhuvan or OSM-derived tiles) before any public
deployment — see PRD §20, decision D1.
