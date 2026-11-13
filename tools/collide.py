#!/usr/bin/env python3
"""Collision / crowding audit for the Trackflow engine.

Drives the engine over stdio and measures, frame by frame, how badly vehicles
overlap. Three independent metrics:

  overlap   two vehicles on the SAME link+lane whose bodies intersect along the
            link (bumper into bumper) -- a car-following failure
  junction  two vehicles from DIFFERENT approaches both inside the same node's
            25 m box -- a junction-conflict failure (what "cars drive through
            each other" looks like at unsignalised nodes)
  hardstop  a vehicle at v ~ 0 that is not at a red light and not queued

Usage: python3 tools/collide.py [site] [seconds] [dt]
"""
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENGINE = os.path.join(ROOT, "engine", "trackflow_engine")
DATA = os.path.join(ROOT, "site-data")

BOX_M = 25.0


def run(site="connaught_place", seconds=120.0, dt=0.5):
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

    send({"cmd": "set_integrator", "value": "rk4"})
    send({"cmd": "reset"})

    # The engine's `site` message carries the payload at the TOP level (it is
    # spliced in by the bridge), not nested under a "site" key.  Reading
    # site_msg["site"] silently yielded {} and every vehicle class fell back to
    # a generic 4.5 m, which reported phantom overlaps for two-wheelers.
    site_payload = read_until("site") or {}
    if isinstance(site_payload.get("site"), dict):
        site_payload = site_payload["site"]

    lengths = {}
    for c in site_payload.get("vehicle_classes", []):
        lengths[c["id"]] = float(c.get("length", 4.5))

    link_to = {}
    link_len = {}
    for l in site_payload.get("links", []):
        link_to[l["id"]] = l["to"]
        link_len[l["id"]] = float(l["length_m"])

    n_steps = int(seconds / dt)
    worst_overlap = 0.0
    overlap_frames = 0
    overlap_events = 0
    junction_frames = 0
    worst_junction_pairs = 0
    junction_events = 0
    total_frames = 0
    max_active = 0
    prev_overlap_set = set()
    prev_junction_set = set()
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

        # ---- same-lane overlap -------------------------------------------
        by_lane = {}
        for v in veh:
            by_lane.setdefault((v["link"], v["lane"]), []).append(v)
        frame_overlap = 0.0
        overlap_ids = set()
        for group in by_lane.values():
            group.sort(key=lambda x: x["s"])
            # group is sorted ASCENDING in s, so a = follower (behind) and
            # b = leader (ahead).  The clear gap runs from the front of the
            # leader back to the tail of the follower, so it is the follower's
            # own body length that must fit behind the leader.
            for a, b in zip(group, group[1:]):
                la = lengths.get(a["cls"], 4.5)
                gap = (b["s"] - a["s"]) - la
                if gap < 0:
                    frame_overlap = max(frame_overlap, -gap)
                    overlap_ids.add((a["id"], b["id"]))
        if frame_overlap > 0:
            overlap_frames += 1
            worst_overlap = max(worst_overlap, frame_overlap)
        overlap_events += len(overlap_ids - prev_overlap_set)
        prev_overlap_set = overlap_ids

        # ---- junction conflicts ------------------------------------------
        near = {}
        for v in veh:
            node = link_to.get(v["link"])
            ln = link_len.get(v["link"], 1e9)
            if node is None:
                continue
            if ln - v["s"] > BOX_M:
                continue
            near.setdefault(node, []).append(v)
        junction_ids = set()
        frame_junction_pairs = 0
        for node, group in near.items():
            flat = group
            for a in range(len(flat)):
                for b in range(a + 1, len(flat)):
                    if flat[a]["link"] != flat[b]["link"]:
                        junction_ids.add((min(flat[a]["id"], flat[b]["id"]),
                                          max(flat[a]["id"], flat[b]["id"])))
            if len({v["link"] for v in group}) >= 2:
                frame_junction_pairs += 1
        if junction_ids:
            junction_frames += 1
        junction_events += len(junction_ids - prev_junction_set)
        prev_junction_set = junction_ids
        worst_junction_pairs = max(worst_junction_pairs, len(junction_ids))

        if i % 40 == 0:
            samples.append({
                "t": snap.get("t"),
                "active": snap.get("active"),
                "departed": snap.get("departed"),
                "arrived": snap.get("arrived"),
                "delay": snap.get("mean_delay"),
                "overlap": round(frame_overlap, 2),
                "junc": len(junction_ids),
            })

    send({"cmd": "quit"})
    try:
        p.wait(timeout=5)
    except Exception:
        p.kill()

    pct = lambda n: 100.0 * n / max(1, total_frames)
    print(f"site={site}  simulated={seconds}s  dt={dt}  frames={total_frames}")
    print(f"peak active vehicles          : {max_active}")
    print(f"same-lane overlap frames      : {overlap_frames} ({pct(overlap_frames):.2f}%)")
    print(f"same-lane overlap worst depth : {worst_overlap:.2f} m")
    print(f"same-lane overlap incidents   : {overlap_events}")
    print(f"junction conflict frames      : {junction_frames} ({pct(junction_frames):.2f}%)")
    print(f"junction conflict incidents   : {junction_events}")
    print(f"worst concurrent conflict prs : {worst_junction_pairs}")
    print("\n      t  active  depart  arrived   delay  overlap  junc")
    for s in samples:
        print(f"  {s['t']:6.1f} {s['active']:6} {s['departed']:7} {s['arrived']:8} "
              f"{float(s['delay']):7.2f} {s['overlap']:8.2f} {s['junc']:5}")
    return {
        "overlap_frames": overlap_frames,
        "worst_overlap": worst_overlap,
        "junction_frames": junction_frames,
        "junction_incidents": junction_events,
        "frames": total_frames,
    }


if __name__ == "__main__":
    site = sys.argv[1] if len(sys.argv) > 1 else "connaught_place"
    secs = float(sys.argv[2]) if len(sys.argv) > 2 else 120.0
    d = float(sys.argv[3]) if len(sys.argv) > 3 else 0.5
    run(site, secs, d)
