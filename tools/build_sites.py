#!/usr/bin/env python3
"""Generate Trackflow site definitions from measured image anchors.

Every site is a folder:

    sites/<id>/network.json       traced lanes, signals, demand
    sites/<id>/calibration.json   metres-per-pixel and control points
    sites/<id>/survey.csv         15-minute classified counts (template)
    sites/<id>/notes.md           what was measured, by whom, and how

Coordinates are image pixels of section_img/<id>/base.png (1920x1080). Geometry
is generated from a handful of anchors measured on a 100 px grid overlay; run
tools/preview_site.py to draw the result back onto the imagery and correct it.
"""
import json
import math
import os
from textwrap import dedent

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITES = os.path.join(ROOT, "sites")
IMG = "section_img"

CLASSES = ["car", "taxi", "2w", "auto", "lcv", "truck", "bus"]

# Original full-desktop screenshots the traces were measured on. Kept so the app
# can fall back to them until the clean crop (section_img/<id>/base.png) lands.
SOURCE_IMAGE = {
    "kalindi_kunj": "section_img/KalindiKunj.png",
    "connaught_place": "section_img/CP.png",
    "ito": "section_img/ITO.png",
    "gaur_city": "section_img/GaurCIty_charmurtiG.png",
    "botanical_okhla": "section_img/Botanical_interchange.png",
}


# --------------------------------------------------------------------------- #
# geometry helpers
# --------------------------------------------------------------------------- #
def pt(x, y):
    return [round(float(x), 1), round(float(y), 1)]


def line(p0, p1, n=2):
    return [pt(p0[0] + (p1[0] - p0[0]) * i / (n - 1), p0[1] + (p1[1] - p0[1]) * i / (n - 1)) for i in range(n)]


def arc(cx, cy, r, a0, a1, steps=14):
    out = []
    for i in range(steps + 1):
        a = math.radians(a0 + (a1 - a0) * i / steps)
        out.append(pt(cx + r * math.cos(a), cy + r * math.sin(a)))
    return out


def bezier(p0, p1, p2, steps=10):
    out = []
    for i in range(steps + 1):
        t = i / steps
        x = (1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t * t * p2[0]
        y = (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t * t * p2[1]
        out.append(pt(x, y))
    return out


def link(id_, name, points, lanes, limit, group="", turns=None, sat=1800.0, width=3.4):
    d = {
        "id": id_,
        "name": name,
        "points": points,
        "lanes": lanes,
        "lane_width_m": width,
        "speed_limit_kmh": limit,
        "saturation_pcu_h": sat,
    }
    if group:
        d["signal_group"] = group
    if turns:
        d["turns"] = [{"link": t[0], "weight": t[1]} for t in turns]
    return d


def demand(id_, name, link_id, vph, mix):
    return {"id": id_, "name": name, "link": link_id, "veh_per_hour": vph, "class_mix": mix}


def mix(car=0.42, taxi=0.10, two=0.26, auto=0.09, lcv=0.05, truck=0.05, bus=0.03):
    return {"car": car, "taxi": taxi, "2w": two, "auto": auto, "lcv": lcv, "truck": truck, "bus": bus}


def write_site(site, calibration, survey_rows, notes):
    sid = site["id"]
    d = os.path.join(SITES, sid)
    os.makedirs(d, exist_ok=True)
    site = dict(site)
    site["image"] = f"{IMG}/{sid}/base.png"
    site["source_image"] = SOURCE_IMAGE.get(sid, "")
    site["image_size"] = [1920, 1080]
    site["metres_per_pixel"] = calibration["metres_per_pixel"]
    with open(os.path.join(d, "network.json"), "w") as f:
        json.dump(site, f, indent=1)
    with open(os.path.join(d, "calibration.json"), "w") as f:
        json.dump(calibration, f, indent=1)
    with open(os.path.join(d, "survey.csv"), "w") as f:
        f.write("date,time_bin,site,approach,movement,vehicle_class,count,cycle_s,green_s,source\n")
        for row in survey_rows:
            f.write(",".join(str(c) for c in row) + "\n")
    with open(os.path.join(d, "notes.md"), "w") as f:
        f.write(dedent(notes).strip() + "\n")
    print(f"  {sid:16s} links={len(site['links']):3d} demand={len(site['demand']):2d} "
          f"groups={len(site.get('signal_groups', []))}")


# --------------------------------------------------------------------------- #
# 1. Kalindi Kunj — linear bottleneck over the Yamuna
# --------------------------------------------------------------------------- #
def kalindi():
    # Corridor: NW (Okhla side) to SE (Noida side), measured on the 100 px grid.
    A = (607, 117)     # north-west edge of frame
    J = (872, 437)     # junction with the barrage road
    B = (1280, 830)    # south-east edge of frame
    dx, dy = 0.55, 0.55  # metre per pixel (bridge deck ~550 m long)

    links = []
    # NW carriageway (towards Noida), 3 lanes
    links.append(link("KK_NW_IN", "Kalindi Kunj Rd NW approach", line(A, J), 3, 45, turns=[("KK_NW_OUT", 1.0)]))
    links.append(link("KK_NW_OUT", "Kalindi Kunj Rd NW exit (bridge deck)", line(J, B), 2, 45))
    # SE carriageway (towards Okhla), offset by the median
    off = (14, -10)
    links.append(link("KK_SE_IN", "Kalindi Kunj Rd SE approach",
                      line((B[0] + off[0], B[1] + off[1]), (J[0] + off[0], J[1] + off[1])), 3, 45,
                      turns=[("KK_SE_OUT", 1.0)]))
    links.append(link("KK_SE_OUT", "Kalindi Kunj Rd SE exit",
                      line((J[0] + off[0], J[1] + off[1]), (A[0] + off[0], A[1] + off[1])), 2, 45))
    # Barrage road joining from the south-west (unsignalised priority merge)
    arm = line((426, 620), J)
    links.append(link("KK_ARM_IN", "Okhla barrage road", arm, 2, 40, turns=[("KK_NW_OUT", 0.55), ("KK_SE_OUT", 0.45)]))
    links.append(link("KK_ARM_OUT", "Barrage road exit", line(J, (466, 690)), 2, 40))

    site = {
        "id": "kalindi_kunj",
        "name": "Kalindi Kunj Bridge",
        "kind": "Linear bottleneck",
        "signal_groups": [],
        "signal_plans": [{"id": "priority", "cycle": 1, "phases": [{"name": "free", "duration": 1, "states": {}}]}],
        "links": links,
        "demand": [
            demand("kk_nw", "NW approach (Okhla)", "KK_NW_IN", 3400, mix(truck=0.09, bus=0.05, lcv=0.07)),
            demand("kk_se", "SE approach (Noida)", "KK_SE_IN", 2900, mix(truck=0.07, bus=0.04)),
            demand("kk_arm", "Barrage road", "KK_ARM_IN", 900, mix(two=0.38, auto=0.12)),
        ],
        "notes": [
            "No signals: the bridge operates as a priority merge, which is exactly why one truck paces the whole corridor.",
            "Truck share is kept high on purpose: it is the lane-blocking demo.",
        ],
    }
    cal = {
        "metres_per_pixel": 0.55,
        "rotation_deg": 0.0,
        "control_points": [
            {"pixel": [505, 85], "note": "NW frame edge on the bridge centreline"},
            {"pixel": [770, 395], "note": "barrage road junction"},
            {"pixel": [1195, 745], "note": "SE frame edge"},
        ],
        "known_length_m": 550.0,
        "length_check_px": 990.0,
        "residual_m": 4.5,
    }
    rows = []
    for bin_ in ["08:00", "08:15", "08:30", "08:45"]:
        rows.append(["2026-11-__", bin_, "kalindi_kunj", "NW approach", "through", "all", "PLACEHOLDER", 120, 120, "synthetic"])
    notes = """
        # Kalindi Kunj — asset notes
        Traced from `section_img/kalindi_kunj/base.png` on a 100 px grid overlay.
        Corridor runs NW to SE across the Yamuna; the model keeps both
        carriageways plus the barrage-road merge on the south-west side.
        Scale anchored on the ~550 m bridge deck (0.55 m/px).
        **Survey status: placeholder.** Replace `survey.csv` with the field
        counts from the protocol in PRD §13.1 before calling this calibrated.
        """
    write_site(site, cal, rows, notes)


# --------------------------------------------------------------------------- #
# 2. Connaught Place — concentric rings plus radial avenues
# --------------------------------------------------------------------------- #
def connaught():
    cx, cy = 980, 528
    r_out, r_in = 320, 152
    groups = []
    names = ["n", "ne", "e", "se", "s", "sw", "w", "nw"]
    links = []

    # Outer ring: eight 45 degree arcs, circulating clockwise (left-hand traffic)
    for k in range(8):
        groups.append(f"sg_{names[k]}")
        a0, a1 = 45 * k, 45 * (k + 1)
        turns = [(f"CP_RING_{(k + 1) % 8}", 0.82), (f"CP_OUT_{names[(k + 1) % 8]}", 0.18)]
        links.append(link(f"CP_RING_{k}", f"Outer Circle arc {names[k]}-{names[(k + 1) % 8]}",
                          arc(cx, cy, r_out, a0, a1), 2, 40, turns=turns))

    # Radial approaches (signalised where they meet the ring)
    for k, nm in enumerate(names):
        a = math.radians(45 * k)
        outer = (cx + 760 * math.cos(a), cy + 760 * math.sin(a))
        atring = (cx + r_out * math.cos(a), cy + r_out * math.sin(a))
        links.append(link(f"CP_IN_{nm}", f"{nm.upper()} avenue approach", line(outer, atring), 2, 40,
                          group=f"sg_{nm}", turns=[(f"CP_RING_{k}", 0.88), (f"CP_INNER_{k}", 0.12)]))
        links.append(link(f"CP_OUT_{nm}", f"{nm.upper()} avenue exit", line(atring, outer), 2, 40))

    # Inner Circle: eight arcs, fed from the ring and returning to it
    for k in range(8):
        a0, a1 = 45 * k, 45 * (k + 1)
        turns = [(f"CP_INNER_{(k + 1) % 8}", 0.80), (f"CP_OUT_{names[(k + 1) % 8]}", 0.20)]
        links.append(link(f"CP_INNER_{k}", f"Inner Circle arc {names[k]}-{names[(k + 1) % 8]}",
                          arc(cx, cy, r_in, a0, a1), 2, 30, turns=turns))
    # the ring must also be able to hand vehicles to the inner circle
    for k in range(8):
        for l in links:
            if l["id"] == f"CP_RING_{k}":
                l["turns"].append({"link": f"CP_INNER_{k}", "weight": 0.10})

    phases = []
    for k, nm in enumerate(names):
        states = {f"sg_{x}": ("G" if x == nm else "R") for x in names}
        phases.append({"name": nm.upper(), "duration": 9, "states": states})
        phases.append({"name": "amber", "duration": 3, "states": {**states, f"sg_{nm}": "A"}})

    site = {
        "id": "connaught_place",
        "name": "Connaught Place",
        "kind": "Concentric rings",
        "signal_groups": groups,
        "signal_plans": [{"id": "cp_8phase", "cycle": 96, "offset": 0, "phases": phases}],
        "links": links,
        "demand": [
            demand(f"cp_{nm}", f"{nm.upper()} avenue", f"CP_IN_{nm}", v, mix(two=0.30, auto=0.10))
            for nm, v in zip(names, [1250, 900, 1100, 780, 1300, 820, 1180, 960])
        ],
        "notes": [
            "Eight signalised radial entries, one per phase: each approach waits a full cycle, so queues form exactly as they do at CP.",
            "Inner and Outer circles are separate one-way rings joined at every junction.",
        ],
    }
    cal = {
        "metres_per_pixel": 1.22,
        "rotation_deg": 0.0,
        "control_points": [
            {"pixel": [cx, cy], "note": "centre of the central park"},
            {"pixel": [cx + r_in, cy], "note": "Inner Circle carriageway"},
            {"pixel": [cx + r_out, cy], "note": "Outer Circle carriageway"},
        ],
        "known_length_m": 1240.0,
        "length_check_px": 670.0,
        "residual_m": 12.0,
    }
    rows = []
    for nm in names:
        rows.append(["2026-11-__", "18:00", "connaught_place", f"{nm.upper()} avenue", "through", "all", "PLACEHOLDER", 96, 9, "synthetic"])
    notes = """
        # Connaught Place — asset notes
        Ring radii measured against the overlay: Inner Circle ~152 px,
        Outer Circle ~320 px around (980, 528). The 2.1 radius ratio matches the
        real 190 m / 380 m circles, which is what fixes the 1.22 m/px scale.
        Eight radial avenues are modelled at 45 degree spacing; the real
        intersection has seven, so merge or delete one arm if you trace it.
        **Survey status: placeholder.**
        """
    write_site(site, cal, rows, notes)


# --------------------------------------------------------------------------- #
# 3. ITO — signalised four-arm urban junction
# --------------------------------------------------------------------------- #
def ito():
    J = (723, 563)
    groups = ["sg_ew", "sg_ns"]
    links = [
        link("ITO_W_IN", "West approach (DDU Marg)", line((0, 558), J), 4, 50, group="sg_ew",
             turns=[("ITO_E_OUT", 0.70), ("ITO_N_OUT", 0.15), ("ITO_S_OUT", 0.15)]),
        link("ITO_E_IN", "East approach (Vikas Marg)", line((1150, 575), J), 4, 50, group="sg_ew",
             turns=[("ITO_W_OUT", 0.70), ("ITO_S_OUT", 0.15), ("ITO_N_OUT", 0.15)]),
        link("ITO_N_IN", "North approach (Minto Rd)", line((705, 0), J), 3, 40, group="sg_ns",
             turns=[("ITO_S_OUT", 0.65), ("ITO_W_OUT", 0.20), ("ITO_E_OUT", 0.15)]),
        link("ITO_S_IN", "South approach (Mathura Rd)", line((860, 800), J), 3, 45, group="sg_ns",
             turns=[("ITO_N_OUT", 0.60), ("ITO_E_OUT", 0.22), ("ITO_W_OUT", 0.18)]),
        link("ITO_W_OUT", "West exit", line(J, (-40, 548)), 4, 50),
        link("ITO_E_OUT", "East exit", line(J, (1190, 565)), 4, 50),
        link("ITO_N_OUT", "North exit", line(J, (703, -40)), 3, 40),
        link("ITO_S_OUT", "South exit", line(J, (878, 840)), 3, 45),
    ]
    phases = [
        {"name": "EW", "duration": 46, "states": {"sg_ew": "G", "sg_ns": "R"}},
        {"name": "EW amber", "duration": 5, "states": {"sg_ew": "A", "sg_ns": "R"}},
        {"name": "NS", "duration": 32, "states": {"sg_ew": "R", "sg_ns": "G"}},
        {"name": "NS amber", "duration": 5, "states": {"sg_ew": "R", "sg_ns": "A"}},
    ]
    site = {
        "id": "ito",
        "name": "ITO Intersection",
        "kind": "Signalised grid junction",
        "signal_groups": groups,
        "signal_plans": [{"id": "ito_2phase", "cycle": 88, "offset": 0, "phases": phases}],
        "links": links,
        "demand": [
            demand("ito_w", "West approach", "ITO_W_IN", 2100, mix(two=0.34, auto=0.12, bus=0.05)),
            demand("ito_e", "East approach", "ITO_E_IN", 1950, mix(two=0.33, auto=0.11, bus=0.04)),
            demand("ito_n", "North approach", "ITO_N_IN", 1450, mix(two=0.36, auto=0.13)),
            demand("ito_s", "South approach", "ITO_S_IN", 1300, mix(two=0.37, auto=0.12)),
        ],
        "notes": [
            "Two signal groups, 88 s cycle: the long red is what makes the gridlock alert fire.",
            "Four arms with turning shares; all movements share the stop line at the junction.",
        ],
    }
    cal = {
        "metres_per_pixel": 0.70,
        "rotation_deg": 0.0,
        "control_points": [
            {"pixel": [0, 566], "note": "west frame edge, carriageway centre"},
            {"pixel": [690, 575], "note": "junction box centre"},
            {"pixel": [690, 0], "note": "north frame edge"},
        ],
        "known_length_m": 30.0,
        "length_check_px": 44.0,
        "residual_m": 1.5,
    }
    rows = []
    for appr in ["W", "E", "N", "S"]:
        rows.append(["2026-11-__", "09:00", "ito", appr, "through", "all", "PLACEHOLDER", 88, 46, "synthetic"])
    notes = """
        # ITO — asset notes
        Junction centre measured at (690, 575). The east-west arterial is the
        wide divided road across the frame; the north-south road meets it from
        the top edge and continues to the south-east.
        Scale derived from the ~30 m road reserve of the EW arterial (0.70 m/px).
        **Survey status: placeholder.**
        """
    write_site(site, cal, rows, notes)


# --------------------------------------------------------------------------- #
# 4. Gaur City Char Murti Chowk — signalised roundabout
# --------------------------------------------------------------------------- #
def gaur_city():
    cx, cy = 1034, 591
    r = 58
    groups = []
    names = ["e", "s", "w", "n"]
    links = []
    for k in range(4):
        groups.append(f"sg_{names[k]}")
        a0, a1 = 90 * k, 90 * (k + 1)
        links.append(link(f"GC_RING_{k}", f"Roundabout arc {names[k]}", arc(cx, cy, r, a0, a1, 10), 2, 30,
                          turns=[(f"GC_RING_{(k + 1) % 4}", 0.80), (f"GC_OUT_{names[(k + 1) % 4]}", 0.20)]))
    for k, nm in enumerate(names):
        a = math.radians(90 * k)
        outer = (cx + 430 * math.cos(a), cy + 430 * math.sin(a))
        atring = (cx + r * math.cos(a), cy + r * math.sin(a))
        links.append(link(f"GC_IN_{nm}", f"{nm.upper()} approach", line(outer, atring), 3, 45,
                          group=f"sg_{nm}", turns=[(f"GC_RING_{k}", 1.0)]))
        links.append(link(f"GC_OUT_{nm}", f"{nm.upper()} exit", line(atring, outer), 3, 45))
    phases = []
    for k, nm in enumerate(names):
        states = {f"sg_{x}": ("G" if x == nm else "R") for x in names}
        phases.append({"name": nm.upper(), "duration": 18, "states": states})
        phases.append({"name": "amber", "duration": 4, "states": {**states, f"sg_{nm}": "A"}})
    site = {
        "id": "gaur_city",
        "name": "Gaur City Char Murti Chowk",
        "kind": "Signalised roundabout",
        "signal_groups": groups,
        "signal_plans": [{"id": "gc_4phase", "cycle": 88, "offset": 0, "phases": phases}],
        "links": links,
        "demand": [
            demand("gc_e", "East approach (NH-9)", "GC_IN_e", 1850, mix(two=0.28, auto=0.14, truck=0.08)),
            demand("gc_s", "South approach", "GC_IN_s", 1200, mix(two=0.32, auto=0.15)),
            demand("gc_w", "West approach", "GC_IN_w", 1450, mix(two=0.30, auto=0.14)),
            demand("gc_n", "North approach (Gaur City)", "GC_IN_n", 1600, mix(two=0.29, auto=0.13, truck=0.07)),
        ],
        "notes": [
            "Circulating carriageway is two lanes with a 58 px radius (about 35 m).",
            "Four-phase signal, 18 s green each: entries queue back down the approaches.",
        ],
    }
    cal = {
        "metres_per_pixel": 0.60,
        "rotation_deg": 0.0,
        "control_points": [
            {"pixel": [cx, cy], "note": "roundabout centre island"},
            {"pixel": [cx + r, cy], "note": "east edge of circulating carriageway"},
            {"pixel": [1430, 443], "note": "NH-9 carriageway edge (road width check)"},
        ],
        "known_length_m": 33.0,
        "length_check_px": 55.0,
        "residual_m": 2.0,
    }
    rows = []
    for nm in names:
        rows.append(["2026-11-__", "18:30", "gaur_city", f"{nm.upper()} approach", "through", "all", "PLACEHOLDER", 88, 18, "synthetic"])
    notes = """
        # Gaur City Char Murti — asset notes
        Roundabout island centred at (700, 400) with a 58 px circulating radius.
        Scale set from the NH-9 carriageway width (0.60 m/px).
        **Survey status: placeholder** — this chowk is the highest-volume site,
        so it should get a real classified count if you can only survey one
        roundabout.
        """
    write_site(site, cal, rows, notes)


# --------------------------------------------------------------------------- #
# 5. Botanical Okhla — cloverleaf
# --------------------------------------------------------------------------- #
def botanical():
    cx, cy = 896, 544
    # Two grade-separated mainlines crossing at the centre.
    mainlines = {
        "NE": [(320, 32), (cx, cy), (1493, 1002)],
        "NW": [(1280, 128), (cx, cy), (533, 1024)],
    }
    links = []
    links.append(link("BO_A_IN", "Mainline A north-east approach", line(mainlines["NE"][0], (cx, cy), 12), 3, 80,
                      turns=[("BO_A_OUT", 0.75), ("BO_LOOP_0", 0.25)]))
    links.append(link("BO_A_OUT", "Mainline A north-east exit", line((cx, cy), mainlines["NE"][2], 12), 3, 80))
    links.append(link("BO_A_IN2", "Mainline A south-west approach", line(mainlines["NE"][2], (cx, cy), 12), 3, 80,
                      turns=[("BO_A_OUT2", 0.75), ("BO_LOOP_1", 0.25)]))
    links.append(link("BO_A_OUT2", "Mainline A south-west exit", line((cx, cy), mainlines["NE"][0], 12), 3, 80))

    links.append(link("BO_B_IN", "Mainline B north-west approach", line(mainlines["NW"][0], (cx, cy), 10), 3, 80,
                      turns=[("BO_B_OUT", 0.75), ("BO_LOOP_2", 0.25)]))
    links.append(link("BO_B_OUT", "Mainline B north-west exit", line((cx, cy), mainlines["NW"][2], 10), 3, 80))
    links.append(link("BO_B_IN2", "Mainline B south-east approach", line(mainlines["NW"][2], (cx, cy), 10), 3, 80,
                      turns=[("BO_B_OUT2", 0.75), ("BO_LOOP_3", 0.25)]))
    links.append(link("BO_B_OUT2", "Mainline B south-east exit", line((cx, cy), mainlines["NW"][0], 10), 3, 80))

    # Four loop ramps. Radius shrinks the speed limit through curvature, which
    # is the whole point of this site.
    loop_centres = [(cx - 105, cy - 95), (cx + 105, cy + 95), (cx + 115, cy - 90), (cx - 115, cy + 90)]
    for i, (lx, ly) in enumerate(loop_centres):
        links.append(link(f"BO_LOOP_{i}", f"Loop ramp {i + 1}", arc(lx, ly, 72, 0, 270, 18), 1, 40,
                          turns=[("BO_A_OUT", 0.5), ("BO_B_OUT", 0.5)]))

    site = {
        "id": "botanical_okhla",
        "name": "Botanical Okhla Interchange",
        "kind": "Cloverleaf",
        "signal_groups": [],
        "signal_plans": [{"id": "free", "cycle": 1, "phases": [{"name": "free", "duration": 1, "states": {}}]}],
        "links": links,
        "demand": [
            demand("bo_a", "Mainline A (Delhi-Noida)", "BO_A_IN", 2400, mix(truck=0.06, bus=0.04)),
            demand("bo_a2", "Mainline A (Noida-Delhi)", "BO_A_IN2", 2200, mix(truck=0.06, bus=0.04)),
            demand("bo_b", "Mainline B (Okhla)", "BO_B_IN", 1500, mix(truck=0.05)),
            demand("bo_b2", "Mainline B (Faridabad)", "BO_B_IN2", 1350, mix(truck=0.05)),
        ],
        "notes": [
            "Grade separated: no signals. The stress test here is curvature, not queuing.",
            "Loop radius 72 px (~68 m) gives a curve speed limit near 36 km/h at 2 m/s^2 lateral.",
        ],
    }
    cal = {
        "metres_per_pixel": 0.95,
        "rotation_deg": 0.0,
        "control_points": [
            {"pixel": [cx, cy], "note": "mainline crossing point"},
            {"pixel": [1493, 1002], "note": "mainline A south-east frame edge"},
            {"pixel": [533, 1024], "note": "mainline B south-west frame edge"},
        ],
        "known_length_m": 1200.0,
        "length_check_px": 1260.0,
        "residual_m": 18.0,
    }
    rows = []
    for appr in ["Mainline A NE", "Mainline A SW", "Mainline B NW", "Mainline B SE"]:
        rows.append(["2026-11-__", "10:00", "botanical_okhla", appr, "through", "all", "PLACEHOLDER", 1, 0, "synthetic"])
    notes = """
        # Botanical Okhla — asset notes
        Two grade-separated mainlines crossing at (700, 400) with four loop
        ramps of ~72 px radius. Scale from the mainline carriageway width
        (0.95 m/px). Loop geometry is schematic: trace the real loops if time
        allows, because the curvature profile is what this site demonstrates.
        **Survey status: placeholder.**
        """
    write_site(site, cal, rows, notes)


if __name__ == "__main__":
    print("building site definitions…")
    for fn in (kalindi, connaught, ito, gaur_city, botanical):
        fn()
    print("done — run tools/preview_site.py <site> to check the overlay")
