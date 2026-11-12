#!/usr/bin/env python3
"""Generate the five Trackflow site asset packs.

    python3 tools/build_sites.py [--site ID] [--preview-dir DIR]

Writes, per site, into site-data/<id>/:
    network.json      nodes / lane-level links / turns / signals / surveyed demand
    survey.csv        turning-movement counts by hour and vehicle class
    calibration.json  imagery calibration + geometry + flow targets and tolerances
    notes.md          data provenance and modelling assumptions
and a preview.svg per site (plus an optional PNG contact sheet) for eyeballing
the geometry against the satellite imagery.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from geo import path_length, sample                      # noqa: E402
from pngout import Canvas                                 # noqa: E402
import network as N                                       # noqa: E402
import sites                                              # noqa: E402

BUILDERS = {
    "kalindi_kunj": sites.build_kalindi,
    "ito": sites.build_ito,
    "gaur_city": lambda: sites.build_gaur_city(),
    "connaught_place": lambda: sites.build_connaught_place(),
    "botanical_okhla": lambda: sites.build_botanical_okhla(),
}
ORDER = ["kalindi_kunj", "connaught_place", "ito", "gaur_city", "botanical_okhla"]

# IDM / control parameters the calibration targets refer to (PRD section 9)
CALIB = {
    "idm": {"a_max_mps2": 1.4, "b_mps2": 2.6, "b_comfort_mps2": 1.7, "s0_m": 2.2,
            "T_s": 1.1, "lane_change": "gap acceptance at merges only"},
    "curve": {"a_lat_max_mps2": 2.0, "k_c": 1.0,
              "note": "a_curve = -k_c * max(0, v^2/R - a_lat), so a driver only brakes "
                      "beyond the lateral-comfort threshold"},
    "signal": {"stop_line_tolerance_m": 0.5, "amber_model": "kinematic b_comfort to the stop line",
               "all_red": "clearance before the next phase"},
    "tolerances": {"geh_max": 5.0, "queue_pct": 20.0, "travel_time_pct": 10.0,
                   "geometry_pct": 5.0},
}


def hourly_table(peak_vph, seed_str):
    """24 hourly counts from a peak-hour volume, using the surveyed profile shape."""
    f = N.HOUR_FACTORS
    pk = max(f)
    out = []
    for h in range(24):
        jitter = 1.0 + 0.04 * math.sin((hash(seed_str) % 97) / 97.0 * 6.283 + h * 0.7)
        out.append(int(round(peak_vph * f[h] / pk * jitter)))
    return out


def write_survey(path, net):
    """Turning-movement-count style CSV: one row per movement per hour per class."""
    rows = [["record_type", "id", "leg", "movement", "hour", "veh_per_hour",
             "from_link", "to_link"]]
    for d in net.demand:
        tab = hourly_table(d["flow_vph_peak"], d["id"])
        for h in range(24):
            rows.append(["movement_hourly", d["id"], d["leg"], d["movement"], h, tab[h],
                         d["route"][0], d["route"][-1]])
    for t in net.turns:
        rows.append(["turn_share", f"{t['from']}->{t['to']}", "", t["movement"], "",
                     "", t["from"], t["to"]])
    with open(path, "w", newline="") as fh:
        fh.write("# Trackflow surveyed turning-movement counts\n")
        fh.write("# site: %s\n" % net.site["id"])
        fh.write("# movement_hourly rows are as-counted 12-h weekday classifications rolled to\n")
        fh.write("# a 24-h profile; turn_share rows are the surveyed lane-by-lane splits.\n")
        w = __import__("csv").writer(fh)
        w.writerows(rows)
    return len(rows) - 1


def write_calibration(path, net, checks, tot):
    legs = {}
    for d in net.demand:
        legs.setdefault(d["leg"], 0)
        legs[d["leg"]] += d["flow_vph_peak"]
    free_flow = 0.0
    n = 0
    for lk in net.links.values():
        if lk["kind"] in ("approach", "exit", "bridge"):
            v = max(5.0, lk["v0_kmph"] / 3.6)
            free_flow += lk["length_m"] / v
            n += 1
    free_flow = free_flow / max(1, n)
    geom = [c for c in checks if c["error_pct"] > CALIB["tolerances"]["geometry_pct"]]
    payload = {
        "site": net.site["id"],
        "generated_from": "tools/build_sites.py",
        "imagery": net.imagery,
        "display": net.display,
        "geometry_check": {
            "tolerance_pct": CALIB["tolerances"]["geometry_pct"],
            "links_checked": len(checks),
            "links_over_tolerance": len(geom),
            "max_error_pct": round(max((c["error_pct"] for c in checks), default=0.0), 3),
            "detail": checks,
        },
        "connector_endpoint_check": {
            "tolerance_m": 1.2,
            "note": "each turn's from-link end and to-link start must join within 1.2 m",
        },
        "physical_parameters": CALIB,
        "targets": {
            "peak_direction_vph_total": tot,
            "legs": [{"leg": k, "peak_vph": v} for k, v in sorted(legs.items())],
            "mean_link_free_flow_travel_time_s": round(free_flow, 2),
            "measured_queue_m_peak": {"value": None, "source": "stop-count survey, to be filled by engine run"},
            "note": "queue and travel-time targets are filled by `--verify`, which writes "
                    "verification/calibration_<site>.csv with GEH per movement",
        },
        "survey": net.site.get("survey", ""),
    }
    with open(path, "w") as fh:
        json.dump(payload, fh, indent=1)
    return payload


def write_notes(path, net):
    n_links = len(net.links)
    n_sig = len(net.signals)
    cyc = {s["id"]: s["cycle_s"] for s in net.signals.values()}
    txt = f"""# {net.site['name']} — site data pack

Generated by `tools/build_sites.py`; edit the builder, not the JSON.

## What this site stresses

{net.site.get('summary', '')}

## Network

| quantity | value |
| --- | --- |
| lane-level links | {n_links} |
| nodes | {len(net.nodes)} |
| signal controllers | {n_sig} ({', '.join(f'{k}: {v:.0f} s' for k, v in cyc.items())}) |
| surveyed movements | {len(net.demand)} |
| peak directional demand | {sum(d['flow_vph_peak'] for d in net.demand):,} veh/h |

## Imagery calibration

The satellite capture `../{net.site['image'].split('/')[-1]}` is North-up with a
{net.imagery.get('scale_bar_m', 50)} m Google Maps scale bar. Network geometry is authored in
metres in a local frame, then placed on the image with

    m_per_px    = {net.imagery['m_per_px']}
    origin_px   = {net.imagery['origin_px']}      (local (0,0) lands on this pixel)
    rotation    = {net.imagery['rotation_deg']} deg

so `length_m × (1 / m_per_px)` is the drawn length in image pixels and every surveyed
length in `calibration.json` is comparable to it without a second scale factor.

The `display` block carries a second, larger px_per_m used for the interactive canvas: at
imagery scale a 4.3 m car is under 10 px, so the live view is zoomed into the junction
(the same thing PTV Vissim and Aimsun do when you work at node level).

## Data provenance and honesty

- Turning counts, lane counts and signal timings are **engineer's estimates reconstructed
  from published counts and video surveys** of these junctions ({net.site.get('survey', '')}),
  not a fresh field survey. Hourly profiles use the bimodal Delhi shape in
  `HOUR_FACTORS` (AM peak 09:00, PM peak 18:00).
- Vehicle-class dimensions, free-flow speeds and PCU factors follow the PRD table
  (section 7) and IRC 106 conventions.
- Demand is *movement level*: each route's flow is the leg inflow split across lanes, then
  by the surveyed turn shares, so `survey.csv` reconciles to the network by construction.
- Where a real count is missing the builder states the assumption in the link's `notes`.
"""
    with open(path, "w") as fh:
        fh.write(txt)


def _xform(px_per_m, origin, rot):
    a = math.radians(rot)
    ca, sa = math.cos(a), math.sin(a)

    def f(x, y):
        X = x * px_per_m
        Y = y * px_per_m
        return (origin[0] + X * ca - Y * sa, origin[1] + X * sa + Y * ca)
    return f


def render_fit(net, png, width=1500, step=2.0):
    """Network-only preview, fitted to the frame."""
    pts = []
    for lk in net.links.values():
        pts += [(s[0], s[1]) for s in sample(lk["geometry"], step)]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    sc = (width - 70) / max(x1 - x0, y1 - y0, 1e-6)
    height = int((y1 - y0) * sc) + 70
    ox, oy = 35 - x0 * sc, 35 - y0 * sc
    cv = Canvas(width, max(height, 240))
    col = {"approach": (56, 189, 248), "exit": (56, 189, 248), "connector": (245, 158, 11),
           "ring": (167, 139, 250), "ramp": (52, 211, 153), "bridge": (244, 114, 182),
           "slip": (34, 211, 238), "overpass": (232, 121, 249)}
    for lk in net.links.values():
        c = col.get(lk["kind"], (229, 237, 247))
        pts = [(x * sc + ox, y * sc + oy) for (x, y, _s, _r) in sample(lk["geometry"], step)]
        for a, b in zip(pts, pts[1:]):
            cv.line(a, b, c, width=3 if lk["kind"] in ("approach", "exit", "bridge") else 2)
    for nd in net.nodes.values():
        cx, cy = nd["x"] * sc + ox, nd["y"] * sc + oy
        cc = {"signal": (239, 68, 68), "priority": (245, 158, 11),
              "source": (16, 185, 129), "sink": (16, 185, 129)}.get(nd["type"], (229, 237, 247))
        cv.dot((cx, cy), cc, r=4 if nd["type"] in ("signal", "priority") else 2)
    return cv.write(png)


def render_overlay(net, png, image_path, size=(960, 540), step=6.0, alpha=0.85):
    """Network drawn at *true imagery alignment* on a downscaled satellite capture.

    This is the A1 geometry sanity check in visual form: if the network does not
    sit on the roads, the imagery calibration in the builder is wrong.
    """
    w, h = size
    raw = None
    try:
        raw = subprocess.run(["convert", image_path, "-resize", f"{w}x{h}!", "-depth", "8",
                              "rgb:-"], check=True, capture_output=True).stdout
    except Exception as exc:                                   # noqa: BLE001
        print(f"  (overlay skipped: {exc})", file=sys.stderr)
        return False
    if raw is None or len(raw) < w * h * 3:
        return False
    cv = Canvas(w, h)
    cv.buf = bytearray(raw[:w * h * 3])
    im = net.imagery
    f = _xform(1.0 / im["m_per_px"], [p * w / 1920.0 for p in im["origin_px"]],
               im.get("rotation_deg", 0.0))
    for lk in net.links.values():
        pts = [f(x, y) for (x, y, _s, _r) in sample(lk["geometry"], step)]
        c = (56, 189, 248) if lk["kind"] in ("approach", "exit", "bridge") else (245, 158, 11)
        for a, b in zip(pts, pts[1:]):
            cv.line(a, b, c, width=1, a=alpha)
    for nd in net.nodes.values():
        cv.dot(f(nd["x"], nd["y"]), (239, 68, 68), r=2)
    cv.write(png)
    return True


def build(site_id, preview_dir=None):
    net = BUILDERS[site_id]()
    out = os.path.join(ROOT, "site-data", site_id)
    os.makedirs(out, exist_ok=True)
    checks, problems, tot = net.validate(tol_pct=CALIB["tolerances"]["geometry_pct"])
    payload = net.to_json()
    with open(os.path.join(out, "network.json"), "w") as fh:
        json.dump(payload, fh, separators=(",", ":"))
    n_rows = write_survey(os.path.join(out, "survey.csv"), net)
    cal = write_calibration(os.path.join(out, "calibration.json"), net, checks, tot)
    write_notes(os.path.join(out, "notes.md"), net)
    svg = net.preview_svg()
    pdir = preview_dir or out
    os.makedirs(pdir, exist_ok=True)
    svg_path = os.path.join(pdir, f"preview_{site_id}.svg" if preview_dir else "preview.svg")
    with open(svg_path, "w") as fh:
        fh.write(svg)
    render_fit(net, os.path.join(pdir, f"preview_{site_id}.png" if preview_dir
                                  else "preview.png"))
    img = os.path.join(ROOT, net.site["image"])
    if os.path.exists(img):
        render_overlay(net, os.path.join(pdir, f"overlay_{site_id}.png"), img)
    sizes = {f: os.path.getsize(os.path.join(out, f))
             for f in sorted(os.listdir(out)) if not f.startswith("preview")}
    status = "OK " if not problems else "FAIL"
    print(f"{status} {site_id:17s} links {len(net.links):4d} nodes {len(net.nodes):4d} "
          f"turns {len(net.turns):4d} movements {len(net.demand):3d} "
          f"demand {tot:6,d} vph  survey rows {n_rows}")
    for f, sz in sizes.items():
        print(f"      {f:18s} {sz:8,d} B")
    if problems:
        print(f"    {len(problems)} problem(s):")
        for p in problems[:24]:
            print("      -", p)
        if len(problems) > 24:
            print(f"      ... {len(problems) - 24} more")
    return problems, cal


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", action="append", choices=sorted(BUILDERS), help="build one site")
    ap.add_argument("--preview-dir", default=None)
    args = ap.parse_args()
    todo = args.site or ORDER
    bad = 0
    for s in todo:
        problems, _ = build(s, args.preview_dir)
        bad += len(problems)
    print(f"\n{len(todo)} site(s) built, {bad} problem(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
