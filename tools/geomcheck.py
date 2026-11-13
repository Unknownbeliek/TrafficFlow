#!/usr/bin/env python3
"""Geometric collision audit for the Trackflow engine.

Drives the engine over stdio and tests vehicle bodies for actual 2D overlap
using oriented bounding boxes (SAT). Unlike a proximity heuristic, this only
counts a collision when two rendered vehicle footprints genuinely intersect,
which is exactly what a viewer would see on screen.

Also reports lane discipline (same-lane spacing) so a "tight but touching"
queue is distinguishable from interpenetration.

Usage: python3 tools/geomcheck.py [site] [seconds] [dt]
"""
import json
import math
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENGINE = os.path.join(ROOT, "engine", "trackflow_engine")
DATA = os.path.join(ROOT, "site-data")

# body half-width by class (metres); lengths come from the site payload
HALF_WIDTH = {
    "car": 0.88, "taxi": 0.88, "auto_rickshaw": 0.70, "two_wheeler": 0.38,
    "lcv": 1.00, "truck": 1.20, "bus": 1.25,
}


def corners(x, y, hdg_deg, length, width):
    a = math.radians(hdg_deg)
    ca, sa = math.cos(a), math.sin(a)
    hl, hw = length / 2.0, width / 2.0
    out = []
    for dx, dy in ((hl, hw), (hl, -hw), (-hl, -hw), (-hl, hw)):
        out.append((x + dx * ca - dy * sa, y + dx * sa + dy * ca))
    return out


def sat_overlap(p, q):
    for poly in (p, q):
        for i in range(4):
            x1, y1 = poly[i]
            x2, y2 = poly[(i + 1) % 4]
            ax, ay = -(y2 - y1), (x2 - x1)
            n = math.hypot(ax, ay)
            if n < 1e-9:
                continue
            ax, ay = ax / n, ay / n
            p1 = [ax * x + ay * y for x, y in p]
            p2 = [ax * x + ay * y for x, y in q]
            if max(p1) < min(p2) or max(p2) < min(p1):
                return 0.0  # separating axis -> no overlap
    # overlapping: approximate depth by the smaller axis penetration
    best = 1e9
    for poly in (p, q):
        for i in range(4):
            x1, y1 = poly[i]
            x2, y2 = poly[(i + 1) % 4]
            ax, ay = -(y2 - y1), (x2 - x1)
            n = math.hypot(ax, ay)
            if n < 1e-9:
                continue
            ax, ay = ax / n, ay / n
            p1 = [ax * x + ay * y for x, y in p]
            p2 = [ax * x + ay * y for x, y in q]
            pen = min(max(p1), max(p2)) - max(min(p1), min(p2))
            best = min(best, pen)
    return max(best, 0.0)


def run(site="connaught_place", seconds=120.0, dt=0.5, verbose=True):
    p = subprocess.Popen(
        [ENGINE, "--stdio", "--data", DATA, "--site", site],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1,
    )

    def send(obj):
        p.stdin.write(json.dumps(obj) + "\n")
        p.stdin.flush()

    def read_until(kind):
        while True:
            line = p.stdout.readline()
            if not line:
                return None
            try:
                m = json.loads(line)
            except Exception:
                continue
            if m.get("type") == kind:
                return m

    send({"cmd": "reset"})
    site_payload = read_until("site") or {}
    if isinstance(site_payload.get("site"), dict):
        site_payload = site_payload["site"]

    lengths = {c["id"]: float(c.get("length", 4.3))
               for c in site_payload.get("vehicle_classes", [])}
    link_to = {l["id"]: l["to"] for l in site_payload.get("links", [])}
    link_len = {l["id"]: float(l["length_m"]) for l in site_payload.get("links", [])}
    lane_count = {l["id"]: int(l.get("lanes", 1)) for l in site_payload.get("links", [])}
    kind_of = {l["id"]: l.get("kind", "") for l in site_payload.get("links", [])}
    LANE_W = float(site_payload.get("lane_width_m", 3.5))

    n_steps = int(seconds / dt)
    total_frames = 0
    collision_frames = 0
    cross_frames = 0
    collision_events = 0
    worst_pen = 0.0
    prev_pairs = set()
    worst_pair = None
    same_lane_min_gap = 1e9
    same_lane_touch = 0
    same_lane_pairs = 0
    junction_frames = 0
    max_active = 0
    samples = []

    for i in range(n_steps):
        send({"cmd": "tick", "seconds": dt})
        snap = read_until("snapshot")
        if snap is None:
            print("engine died at step", i)
            break
        veh = snap.get("vehicles", [])
        total_frames += 1
        max_active = max(max_active, len(veh))

        # The engine reports the LINK centreline point.  The browser offsets each
        # vehicle sideways onto its own lane before drawing it, so the audit has
        # to do the same or it "finds" collisions between cars in adjacent
        # lanes that are visibly separate on screen.
        boxes = {}
        for v in veh:
            ln = lengths.get(v["cls"], 4.3)
            wd = 2.0 * HALF_WIDTH.get(v["cls"], 0.88)
            lanes = lane_count.get(v["link"], 1)
            off = 0.0
            if lanes > 1:
                lane = max(0, min(lanes - 1, v.get("lane", 0)))
                off = -(lane - (lanes - 1) / 2.0) * LANE_W
            elif kind_of.get(v["link"]) in ("slip", "connector", "ramp"):
                # mirrors the renderer: single-lane merge links sit on the
                # right-hand side of their own path
                off = -LANE_W * 0.55
            h = math.radians(v["hdg"])
            # rotate the lateral offset into the world frame: +x forward,
            # +y to the right of travel
            wx = v["x"] + off * -math.sin(h)
            wy = v["y"] + off * math.cos(h)
            v = dict(v, x=wx, y=wy)
            boxes[v["id"]] = (v, ln, wd)

        # --- exact body overlap ---------------------------------------
        pairs = set()
        frame_pen = 0.0
        cross_pairs = set()
        cell = 12.0
        grid = {}
        for vid, (v, ln, wd) in boxes.items():
            grid.setdefault((int(v["x"] // cell), int(v["y"] // cell)), []).append(vid)
        seen = set()
        for (gx, gy), ids in grid.items():
            cand = list(ids)
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    cand += grid.get((gx + dx, gy + dy), [])
            for a in ids:
                for b in cand:
                    if a >= b:
                        continue
                    key = (a, b)
                    if key in seen:
                        continue
                    seen.add(key)
                    va, la, wa = boxes[a]
                    vb, lb, wb = boxes[b]
                    if math.hypot(va["x"] - vb["x"], va["y"] - vb["y"]) > (la + lb) / 2 + 2.0:
                        continue
                    pa = corners(va["x"], va["y"], va["hdg"], la, wa)
                    pb = corners(vb["x"], vb["y"], vb["hdg"], lb, wb)
                    pen = sat_overlap(pa, pb)
                    if pen > 0.05:
                        pairs.add(key)
                        if va["link"] != vb["link"]:
                            cross_pairs.add(key)
                        if pen > frame_pen:
                            frame_pen = pen
                        if pen > worst_pen:
                            worst_pen = pen
                            worst_pair = (snap.get("t"), va, vb, pen)
        if pairs:
            collision_frames += 1
        if cross_pairs:
            cross_frames += 1
        collision_events += len(pairs - prev_pairs)
        prev_pairs = pairs

        # --- same-lane spacing ----------------------------------------
        by_lane = {}
        for v in veh:
            by_lane.setdefault((v["link"], v["lane"]), []).append(v)
        for group in by_lane.values():
            if len(group) < 2:
                continue
            group.sort(key=lambda x: x["s"])
            for a, b in zip(group, group[1:]):
                gap = (b["s"] - a["s"]) - lengths.get(a["cls"], 4.3)
                same_lane_pairs += 1
                same_lane_min_gap = min(same_lane_min_gap, gap)
                if gap < 0.5:
                    same_lane_touch += 1

        # --- junction crowding (vehicles entering one box) ------------
        near = {}
        for v in veh:
            node = link_to.get(v["link"])
            ln = link_len.get(v["link"], 1e9)
            if node is None or ln - v["s"] > 12.0:
                continue
            near.setdefault(node, set()).add(v["link"])
        if any(len(s) >= 2 for s in near.values()):
            junction_frames += 1

        if i % 40 == 0:
            samples.append({
                "t": snap.get("t"), "active": snap.get("active"),
                "delay": snap.get("mean_delay"), "coll": len(pairs),
                "pen": round(frame_pen, 2),
            })

    send({"cmd": "quit"})
    try:
        p.wait(timeout=5)
    except Exception:
        p.kill()

    pct = lambda n: 100.0 * n / max(1, total_frames)
    print(f"site={site}  simulated={seconds}s  dt={dt}  frames={total_frames}")
    print(f"peak active vehicles        : {max_active}")
    print(f"BODY-COLLISION frames       : {collision_frames} ({pct(collision_frames):.2f}%)")
    print(f"  of which CROSS-LINK frames  : {cross_frames} ({pct(cross_frames):.2f}%)")
    print(f"BODY-COLLISION events       : {collision_events}")
    print(f"deepest body penetration    : {worst_pen:.3f} m")
    print(f"same-lane min bumper gap    : {same_lane_min_gap:.2f} m")
    print(f"same-lane pairs under 0.5 m : {same_lane_touch} / {same_lane_pairs}")
    print(f"junction-crowding frames    : {junction_frames} ({pct(junction_frames):.2f}%)")
    if worst_pair:
        t, va, vb, pen = worst_pair
        print(f"worst pair at t={t}: #{va['id']} {va['cls']} x {vb['id']} {vb['cls']} ({pen:.2f} m)")
    if verbose:
        print("\n      t  active   delay  coll   pen")
        for s in samples:
            print(f"  {s['t']:6.1f} {str(s['active']):>6} {float(s['delay']):7.2f} "
                  f"{s['coll']:5} {s['pen']:6.2f}")
    return {
        "collision_frames": collision_frames,
        "collision_events": collision_events,
        "worst_pen": worst_pen,
        "min_gap": same_lane_min_gap,
        "frames": total_frames,
    }


if __name__ == "__main__":
    site = sys.argv[1] if len(sys.argv) > 1 else "connaught_place"
    secs = float(sys.argv[2]) if len(sys.argv) > 2 else 120.0
    d = float(sys.argv[3]) if len(sys.argv) > 3 else 0.5
    run(site, secs, d)
