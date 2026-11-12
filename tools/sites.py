"""Site authors for the five Delhi-NCR interchanges.

Every site is written in metres in a local frame, using the templates in
tools/network.py.  Node/link/turn topology is authored explicitly so the
geometry itself decides which lane a movement lands in (see wire_junction).
"""

from __future__ import annotations

import math

from geo import (LANE_W_DEFAULT, Pen, add, ang_of, arc, bearing, dist, end_dir,
                 end_pt, left_normal, line, mul, offset, path_length, reverse_path,
                 start_dir, start_pt, sub, unit, vec, right_normal)
from network import (DEFAULT_MIX, MIX_ARTERIAL, MIX_COMMERCIAL, MIX_FREIGHT,
                     MIX_HIGH_2W, MIX_RAMP, Net, anchors, connector, corridor,
                     direct_turns, enumerate_demand, heading_delta, heading_ok,
                     lane_assignment, normalize_turn_weights, ring_path,
                     ring_segments, turn_radius, wire_junction)
from rings import (build_ring, ends_at, mouth_beta, ring_arm, starts_at,
                   wire_ring_entry, wire_ring_exit, wire_ring_penetration)

W = LANE_W_DEFAULT


# ==========================================================================
# authoring helpers
# ==========================================================================
def term(net, lids, at, name):
    """Attach source/sink nodes to the open end of a corridor."""
    ids = []
    for lid in lids:
        g = net.links[lid]["geometry"]
        xy = start_pt(g) if at == "start" else end_pt(g)
        nid = f"{lid}.{'S' if at == 'start' else 'T'}"
        net.node(nid, xy, "source" if at == "start" else "sink",
                 name=f"{name} · {'origin' if at == 'start' else 'destination'} "
                      f"lane {net.links[lid]['lane_index'] + 1}")
        net.links[lid]["from" if at == "start" else "to"] = nid
        ids.append(nid)
    return ids


def arm(net, *, J, name, bearing_out, n_in, n_out, len_in=240.0, len_out=240.0,
        v0=60.0, limit=60.0, mix=None, median=2.0, pid_in=None, pid_out=None,
        setback_in=None, setback_out=None, cross_w=None, kind_in="approach", kind_out="exit",
        out_to=None, heat=None, approach=None, grade="at_grade",
        in_path=None, out_path=None, exit_node=True, labelled=True,
        length_surveyed=None, open_ends=True):
    """One arm of a node: inbound corridor (ends on the stop line) + outbound
    corridor (starts at the arm's exit node).

    Returns {"in": [...], "out": [...], "a_in": [...], "a_out": [...], "ex": node}.
    """
    nd = net.nodes[J]
    centre = [nd["x"], nd["y"]]
    d_in = vec(bearing_out + 180.0)
    d_out = vec(bearing_out)
    # stop line sits just behind the far kerb of the crossing carriageway; the
    # nearside turn radius follows from it (cross_w = that carriageway's width)
    if setback_in is None:
        setback_in = 3.0 + (cross_w / 2.0 if cross_w else 0.5 * (n_in + n_out) * W + median)
    setback_out = (3.0 + 0.5 * W) if setback_out is None else setback_out
    from network import side_normal
    nin, nout = side_normal(d_in), side_normal(d_out)
    c_in = add(centre, mul(nin, median / 2.0 + n_in * W / 2.0))
    c_out = add(centre, mul(nout, median / 2.0 + n_out * W / 2.0))
    pid_in = pid_in or f"{J}.in{int(bearing_out)}"
    pid_out = pid_out or f"{J}.out{int(bearing_out)}"
    ht = heat or name
    ap = approach or f"AP.{name}"
    ex = None
    if exit_node:
        ex = f"{J}.x{int(bearing_out)}"
        net.node(ex, add(c_out, mul(d_out, setback_out)), "junction",
                 name=f"{name} · offside slip")
    stop = add(c_in, mul(d_in, -setback_in))
    far_in = add(c_in, mul(d_in, -len_in))
    geom_in = in_path if in_path is not None else [line(far_in, stop)]
    ins = corridor(net, pid=pid_in, name=f"{name} inbound", path=geom_in, n_lanes=n_in,
                   frm=f"{pid_in}.src", to=J, kind=kind_in, carriageway=f"{name} in",
                   v0=v0, limit=limit, mix=mix, approach=ap, heat=ht, grade=grade,
                   length_surveyed=length_surveyed)
    st = add(c_out, mul(d_out, setback_out))
    far_out = add(c_out, mul(d_out, len_out))
    geom_out = out_path if out_path is not None else [line(st, far_out)]
    outs = corridor(net, pid=pid_out, name=f"{name} outbound", path=geom_out, n_lanes=n_out,
                    frm=ex or J, to=out_to or f"{pid_out}.snk", kind=kind_out,
                    carriageway=f"{name} out", v0=v0, limit=limit, mix=mix,
                    approach=ap, heat=ht, grade=grade)
    if open_ends:
        if in_path is None:
            term(net, ins, "start", f"{name} inbound" if labelled else name)
        if out_to is None and out_path is None:
            term(net, outs, "end", f"{name} outbound" if labelled else name)
    a_in = anchors(net, ins, "end")
    a_out = anchors(net, outs, "start")
    return {"in": ins, "out": outs, "a_in": a_in, "a_out": a_out, "ex": ex,
            "pid_in": pid_in, "pid_out": pid_out, "centre": centre,
            "bearing": bearing_out}


def junction(net, *, J, arms, phases, weights, limit=40.0, allow=("left", "through", "right"),
              lane_moves=None, min_r=6.0, max_r=400.0, kind="connector",
              all_targets=False):
    """Wire every arm of a node against the union of all outbound arms."""
    all_out = [a for ar in arms for a in ar["a_out"]]
    made = {}
    for ar in arms:
        ph = phases.get(ar["pid_in"], phases.get("default", {}))
        wt = weights.get(ar["pid_in"], weights.get("default", {}))
        lm = (lane_moves or {}).get(ar["pid_in"])
        m = wire_junction(net, node_id=J, info_in=ar["a_in"], info_out=all_out,
                          phases=ph, weights=wt, limit=limit, allow=allow,
                          lane_moves=lm, min_r=min_r, max_r=max_r, kind=kind)
        for k, v in m.items():
            made.setdefault(k, []).extend(v)
    return made


def loop_ramp(net, *, pid, name, entry, u_in, exit_pt_xy, u_out, radius,
              lanes=1, v0=50.0, limit=40.0, mix=None, approach="", heat="",
              kind="ramp", frm="", to=""):
    """A 270-degree cloverleaf loop: tangent to the entry lane line and the exit
    lane line, circling to the right so that the net movement is a left turn."""
    pen = Pen(entry, bearing(entry, add(entry, u_in)))
    side = 1 if heading_side(u_in, u_out) > 0 else 1      # loops always curl right
    if not pen.loop_arc(exit_pt_xy, u_out, side, radius):
        return None
    if dist(pen.pos, exit_pt_xy) > 0.05:
        pen.line_to(exit_pt_xy)
    prims = pen.path()
    return corridor(net, pid=pid, name=name, path=prims, n_lanes=lanes, frm=frm, to=to,
                    kind=kind, carriageway=name, v0=v0, limit=limit, mix=mix or MIX_RAMP,
                    approach=approach, heat=heat)


def heading_side(u1, u2):
    u1, u2 = unit(u1), unit(u2)
    return u1[0] * u2[1] - u1[1] * u2[0]


def set_yield(net, lids, conflict, gap_s=2.2, kind="merge", note=""):
    for lid in lids:
        net.links[lid]["yield"] = {"type": kind, "conflict_links": list(conflict),
                                   "gap_s": gap_s, "lookahead_m": 90.0, "note": note}


def taper_into(net, *, node_id, src_lids, tgt_lids, weights=None, limit=60.0,
               all_targets=False, max_lat=None, tol=45.0):
    """Merge / divergence between two corridors that stay roughly parallel.

    all_targets lets one lane spread across both downstream lanes (a lane gain);
    max_lat keeps that spread to genuinely adjacent lanes only.  `tol` widens
    the through heading band: ring mouths use 60 deg, because a driver who
    enters a circle from the kerbside lane of a radial corners in hard.
    """
    a_in = anchors(net, src_lids, "end")
    a_out = anchors(net, tgt_lids, "start")
    made = {}
    for src in a_in:
        cands = []
        sd = unit(src["dir"])
        for tgt in a_out:
            if not heading_ok(src["dir"], tgt["dir"], "through", tol=tol):
                continue
            # rank on the *lateral* offset only: the two corridors are separated
            # longitudinally by the merge/gore gap, which must not count
            dq = [tgt["q"][0] - src["q"][0], tgt["q"][1] - src["q"][1]]
            lat = abs(dq[0] * -sd[1] + dq[1] * sd[0])
            if max_lat is not None and lat > max_lat:
                continue
            cands.append((lat, tgt))
        if not cands:
            continue
        cands.sort(key=lambda z: z[0])
        tgts = [c[1] for c in cands] if all_targets else [cands[0][1]]
        best = tgts[0]
        for tg in tgts:
            cid = connector(net, src, tg, "through", node_id=node_id, limit=limit,
                            min_r=8.0, max_r=4000.0, kind="connector")
            if not cid:
                continue
            w = (weights or {}).get(src["lane"], 1.0) / len(tgts)
            net.turn(src["link"], cid, "through", w)
            net.turn(cid, tg["link"], "through", 1.0)
            made[src["lane"]] = cid
    return made


def through_at(net, src_lids, tgt_lids, *, w=1.0, movement="through"):
    """Collinear corridors that merely *pass* a node (no turning geometry)."""
    for a in anchors(net, src_lids, "end"):
        cands = sorted(anchors(net, tgt_lids, "start"),
                       key=lambda t: dist(a["q"], t["q"]))
        if not cands:
            continue
        best = None
        for t in cands:
            if not heading_ok(a["dir"], t["dir"], movement, tol=46.0):
                continue
            d = dist(a["q"], t["q"])
            if d > 3.0:
                continue
            if best is None or d < best[0]:
                best = (d, t)
        if best:
            net.turn(a["link"], best[1]["link"], movement, w)


def direct_through(net, src_lids, tgt_lids, *, w=1.0, tol=46.0, max_gap=4.0):
    """Turn list for collinear corridors that span a node: the last link of one
    corridor hands over to the first link of the other with no turning arc."""
    for a in anchors(net, src_lids, "end"):
        best = None
        for t in anchors(net, tgt_lids, "start"):
            if not heading_ok(a["dir"], t["dir"], "through", tol=tol):
                continue
            d = dist(a["q"], t["q"])
            if d > max_gap:
                continue
            if best is None or d < best[0]:
                best = (d, t)
        if best:
            net.turn(a["link"], best[1]["link"], "through", w)


def first_from(net, nid, kind="ring"):
    """First link leaving `nid` (used to hand a corridor over to a ring)."""
    for lid, d in net.links.items():
        if d["from"] == nid and (kind is None or d["kind"] == kind):
            return lid
    return None


def lane_drop(net, *, node_id, src_lids, tgt_lids, w=0.35, limit=45.0,
              drop_tol=14.0, tol=60.0, movement="through"):
    """Lane-level divergence between two corridors that cross a node band:
    each source lane is handed to its laterally-nearest target lane with no
    turning arc.  This is what a circle mouth or a plaza crossing box does -
    the mount / kink-in is a geometric drop, so no connector link is built."""
    a_in = anchors(net, src_lids, "end")
    a_out = anchors(net, tgt_lids, "start")
    made = {}
    for src in a_in:
        sd = unit(src["dir"])
        cands = []
        for t in a_out:
            if not heading_ok(src["dir"], t["dir"], movement, tol=tol):
                continue
            dq = [t["q"][0] - src["q"][0], t["q"][1] - src["q"][1]]
            lat = abs(dq[0] * -sd[1] + dq[1] * sd[0])
            if lat > drop_tol:
                continue
            cands.append((dist(src["q"], t["q"]), t))
        if not cands:
            continue
        cands.sort(key=lambda z: z[0])
        for _d, t in cands[:1]:
            net.turn(src["link"], t["link"], movement, w)
            made[src["lane"]] = t["link"]
    return made


def mouth_turns(net, src_lids, tgt_lids, *, w=1.0, phase=None, node_id=None,
                tol=95.0):
    """Ring-mouth hand-overs.  A circle's mouth is authored so the arm lane and
    the circulating lane share one node: the driver's steer there is large (up
    to ~90 deg at Connaught Place, where a radial pierces two one-way bands),
    so the movement is named by the turn direction and recorded without a
    separate connector link - the same treatment the nearside drops at Char
    Murti get."""
    made = []
    for a in anchors(net, src_lids, "end"):
        for t in anchors(net, tgt_lids, "start"):
            d = heading_delta(a["dir"], t["dir"])
            if abs(d) > tol:
                continue
            mv = "through" if abs(d) <= 25.0 else ("right" if d > 0 else "left")
            net.turn(a["link"], t["link"], mv, w, phase=phase)
            made.append((a["link"], t["link"], mv))
    return made


def bfs_route(net, start, goal, *, max_hops=40):
    """Shortest link path along the turn graph (fewest links)."""
    if start == goal:
        return None
    byf = {}
    for t in net.turns:
        byf.setdefault(t["from"], []).append(t["to"])
    seen = {start}
    q = [(start, [start])]
    while q:
        cur, path = q.pop(0)
        if len(path) > max_hops:
            continue
        for nxt in byf.get(cur, []):
            if nxt in seen:
                continue
            if nxt == goal:
                return path + [nxt]
            seen.add(nxt)
            q.append((nxt, path + [nxt]))
    return None


def plan_movements(net, *, legs, max_hops=40, note="plaza circuit (surveyed)"):
    """Enumerate surveyed turning movements by walking the turn graph once per
    origin/destination pair.  Used where a site's circulation is circular (so a
    greedy walk would blow up combinatorially): the route is the shortest legal
    lane path, and the leg inflow is split across it exactly as
    `enumerate_demand` would, keeping `survey.csv` reconciled by construction."""
    by_from = {}
    for t in net.turns:
        by_from.setdefault(t["from"], []).append(t["to"])
    src_groups = {}
    for lid, d in net.links.items():
        if net.nodes.get(d["from"], {}).get("type") == "source":
            src_groups.setdefault(lid.rsplit(".", 1)[0], []).append(lid)
    sink_of = {}
    for lid, d in net.links.items():
        if net.nodes.get(d["to"], {}).get("type") == "sink":
            sink_of.setdefault(lid.rsplit(".", 1)[0], []).append(lid)
    pids = [g for g in src_groups if g in legs]
    for pid in pids:
        lanes = src_groups[pid]
        dests = [q for q in sink_of if q != pid]
        per = legs[pid] / max(1, len(dests))
        for lane in lanes:
            fl = per / len(lanes)
            if fl <= 0.5:
                continue
            for q in dests:
                for end in sink_of.get(q, [])[:1]:
                    route = bfs_route(net, lane, end, max_hops=max_hops)
                    if not route:
                        continue
                    head = net.links[route[0]]
                    net.movement(leg=head["carriageway"], mv="circuit",
                                 route=route, flow_vph=fl,
                                 approach=head["approach"],
                                 mix=head["class_mix"], note=note)
                    break
    return net.demand


def heal_lane_gains(net, *, max_skip=3.6):
    """Feed downstream lanes that no movement reaches (lane gains).

    A 2-lane approach draining into a 3-lane exit leaves the third lane with no
    feeder, which is a topology error in a lane-based network: real junctions
    taper that lane in just downstream.  Add the taper connector from the
    adjacent inbound lane, with a small turn weight.
    """
    fed = set()
    for t in net.turns:
        fed.add(t["to"])
    added = []
    for lid, lk in sorted(net.links.items()):
        if lid in fed or lk["kind"] not in ("exit", "ring", "slip", "ramp", "connector"):
            continue
        node = lk["to"] if net.nodes.get(lk["from"], {}).get("type") != "source" else None
        anchor_node = lk["from"]
        # inbound links that terminate at the node upstream of this lane
        cands = [o for o, d in net.links.items()
                 if d["to"] == anchor_node and o not in (lid,)]
        if not cands:
            continue
        q = start_pt(lk["geometry"])
        u = unit(start_dir(lk["geometry"]))
        best, bestlat = None, None
        for c in cands:
            d = net.links[c]
            if not heading_ok(unit(end_dir(d["geometry"])), u, "through", tol=45.0):
                continue
            cq = end_pt(d["geometry"])
            lat = abs((q[0] - cq[0]) * -u[1] + (q[1] - cq[1]) * u[0])
            if lat > max_skip + 0.1:
                continue
            if bestlat is None or lat < bestlat:
                best, bestlat = c, lat
        if best is None:
            continue
        src = {"link": best, "q": end_pt(net.links[best]["geometry"]),
               "dir": unit(end_dir(net.links[best]["geometry"])),
               "lane": net.links[best]["lane_index"], "exit_node": anchor_node}
        tgt = {"link": lid, "q": q, "dir": u, "lane": lk["lane_index"],
               "exit_node": anchor_node}
        cid = connector(net, src, tgt, "through", node_id=anchor_node, min_r=3.0,
                        max_r=6000.0, limit=min(60.0, lk["speed_limit_kmph"] + 10),
                        kind="connector")
        if not cid:
            continue
        ph = dict(net.links[best]["phases"]).get("through")
        net.links[cid]["phases"] = {"through": ph}
        net.turn(best, cid, "through", 0.18, phase=ph, notes="lane gain taper (modelled)")
        net.turn(cid, lid, "through", 1.0)
        added.append((best, cid, lid))
    return added


# ==========================================================================
# 1. Kalindi Kunj bridge  (linear bottleneck + heavy-vehicle lane blocking)

# ==========================================================================
# imagery calibration
# ==========================================================================
# The metre->pixel mapping is *measured*, not authored: `tools/calibrate.py`
# fits each network onto its capture and writes the result here.  Keeping the
# numbers in one place means a rebuild cannot silently revert the overlay to a
# hand-guessed scale, which is exactly what put the roads off the roads before.
# `view` is the clean-imagery rectangle of each capture: the maps search bar and
# category chips occupy the top ~56 px of every screenshot, and the CP capture
# also carries the Windows taskbar along the bottom.
IMAGERY = {
    "kalindi_kunj":    {"m_per_px": 1.0,    "origin_px": [836.0, 600.0],   "rotation_deg": 30.0,
                        "scale_bar_m": 50, "view": [0, 56, 1920, 1024],
                        "bearing_note": "measured at the bridge junction"},
    "ito":             {"m_per_px": 0.61,   "origin_px": [960.0, 536.0],   "rotation_deg": 0.0,
                        "scale_bar_m": 20, "view": [0, 56, 1920, 1024],
                        "bearing_note": "Ring Road runs horizontally in the image"},
    "gaur_city":       {"m_per_px": 0.2804, "origin_px": [1125.6, 448.8],  "rotation_deg": -16.4,
                        "scale_bar_m": 50, "view": [0, 56, 1920, 1021],
                        "bearing_note": "fitted to the Char Murti roundabout"},
    "connaught_place": {"m_per_px": 0.2793, "origin_px": [948.0, 584.0],   "rotation_deg": 20.0,
                        "scale_bar_m": 50, "view": [0, 56, 1920, 991],
                        # the authored ring is a schematic; measured from the
                        # capture's Outer Circle (347 px radius, ~600 m)
                        "ground_m_per_px": 1.7291,
                        "ground_note": "Outer Circle ring road measured on the capture",
                        "bearing_note": "the concentric rings are centred on this pixel"},
    "botanical_okhla": {"m_per_px": 0.8484, "origin_px": [1023.5, 562.2],  "rotation_deg": 42.3,
                        "scale_bar_m": 50, "view": [0, 56, 1920, 1024],
                        "bearing_note": "local +x follows the DND mainline"},
}


def _imagery(site_id):
    """Copy of the measured calibration for a site (never shared, never mutated)."""
    return dict(IMAGERY[site_id])


# ==========================================================================
def build_kalindi():
    net = Net(
        site={"id": "kalindi_kunj", "name": "Kalindi Kunj Bridge",
              "kind": "river_bridge_bottleneck", "image": "section_img/KalindiKunj.png",
              "survey": "DLTC/TIITYS turning-movement counts, weekday AM/PM peak, "
                        "KalindiKunj + Okhla Head approach video surveys",
              "summary": "Two-way Yamuna crossing with a three-to-two lane reduction at each "
                         "portal; the kerb lane is dropped on the deck, so a slow heavy vehicle "
                         "blocks an entire approach and pushes the queue back across the "
                         "signalised junction at Okhla Head."},
        imagery=_imagery("kalindi_kunj"),
        display={"px_per_m": 2.35, "origin_px": [960, 540], "rotation_deg": 41.0},
    )
    # nodes
    net.signal("S.KW", "Okhla Head (west approach)", [
        {"name": "Bridge through", "green": 52, "amber": 4, "all_red": 3},
        {"name": "Cross road", "green": 20, "amber": 4, "all_red": 3},
    ], offset_s=0.0, coordinator="S.KE", notes="Right turns released on mainline phase")
    net.signal("S.KE", "Film City chowk (east approach)", [
        {"name": "Bridge through", "green": 46, "amber": 4, "all_red": 3},
        {"name": "Expressway slip", "green": 24, "amber": 4, "all_red": 3},
    ], offset_s=41.0, coordinator="S.KW", notes="Offset 41 s to feed the deck in bands")

    for nid, xy, sig, nm in (("JW", [-430, 0], "S.KW", "Okhha Head chowk"),
                             ("JE", [430, 0], "S.KE", "Film City chowk")):
        net.signal_node(nid, xy, sig, nm)
    net.priority_node("PW", [-161, 5.5], "West portal · kerb lane drop")
    net.priority_node("PE", [161, -5.5], "East portal · kerb lane drop")

    y3 = 2.0 + 3 * W / 2.0            # 3-lane carriageway centre (right of travel)
    y2 = 2.0 + 2 * W / 2.0            # 2-lane deck carriageway centre

    def eb(pid, x0, x1, n, y, kind, **kw):
        return corridor(net, pid=pid, name=kw.pop("name", pid), path=[line([x0, y], [x1, y])],
                        n_lanes=n, frm=kw.pop("frm", f"{pid}.a"), to=kw.pop("to", f"{pid}.b"),
                        kind=kind, v0=70, limit=70, mix=MIX_ARTERIAL, heat="Bridge deck (Noida bound)",
                        approach=f"AP.{pid}", **kw)

    def wb(pid, x0, x1, n, y, kind, **kw):
        return corridor(net, pid=pid, name=kw.pop("name", pid), path=[line([x0, -y], [x1, -y])],
                        n_lanes=n, frm=kw.pop("frm", f"{pid}.a"), to=kw.pop("to", f"{pid}.b"),
                        kind=kind, v0=70, limit=70, mix=MIX_ARTERIAL, heat="Bridge deck (Delhi bound)",
                        approach=f"AP.{pid}", **kw)

    # ---- eastbound (Delhi -> Noida), +y side
    K1a = eb("M1a", -700, -442, 3, y3, "approach", name="Mathura Rd approach (EB)", to="JW")
    K2a = eb("M2a", -418, -168, 3, y3, "approach", name="West deck approach (EB)",
             frm="JW.x0", to="PW")
    K3a = eb("M3a", -150, 150, 2, y2, "bridge", name="Yamuna bridge deck (EB)",
             frm="PW", to="PE", grade="bridge", queueable=False)
    K4a = eb("M4a", 168, 418, 3, y3, "exit", name="East deck approach (WB bound)",
             frm="PE", to="JE")
    K5a = eb("M5a", 442, 700, 3, y3, "exit", name="Noida-GN expressway (EB)",
             frm="JE.x0", to="M5a.b")
    # ---- westbound
    K1b = wb("M1b", 700, 442, 3, y3, "approach", name="Expressway approach (WB)",
             frm="M1b.a", to="JE")   # east-bound portal feeds the westbound deck
    K2b = wb("M2b", 418, 168, 3, y3, "approach", name="East deck approach (WB)",
             frm="JE.x180", to="PE")
    K3b = wb("M3b", 150, -150, 2, y2, "bridge", name="Yamuna bridge deck (WB)",
             frm="PE", to="PW", grade="bridge", queueable=False)
    K4b = wb("M4b", -168, -418, 3, y3, "exit", name="West deck approach (WB)",
             frm="PW", to="JW")
    K5b = wb("M5b", -442, -700, 3, y3, "exit", name="Mathura Rd (WB)",
             frm="JW.x180", to="M5b.b")
    term(net, K1a, "start", "Mathura Rd EB origin")
    term(net, K1b, "start", "Expressway WB origin")
    term(net, K5a, "end", "Noida destination")
    term(net, K5b, "end", "Okhla Head destination")

    # ---- cross roads
    A_W_N = arm(net, J="JW", name="Okhla Head Rd north", bearing_out=270, n_in=1, n_out=1,
                len_in=230, len_out=230, v0=50, limit=50, mix=MIX_COMMERCIAL,
                pid_in="JW.inN", pid_out="JW.outN", median=2.0,
                heat="Okhla Head cross road")
    A_W_S = arm(net, J="JW", name="Vijay Marg south", bearing_out=90, n_in=1, n_out=1,
                len_in=230, len_out=230, v0=50, limit=50, mix=MIX_HIGH_2W,
                pid_in="JW.inS", pid_out="JW.outS", median=2.0,
                heat="Okhla Head cross road")
    A_E_N = arm(net, J="JE", name="Sector 18A link road", bearing_out=270, n_in=1, n_out=1,
                len_in=210, len_out=210, v0=50, limit=50, mix=MIX_HIGH_2W,
                pid_in="JE.inN", pid_out="JE.outN", median=2.0, heat="Film City link road")
    A_E_S = arm(net, J="JE", name="Bindapur road", bearing_out=90, n_in=1, n_out=1,
                len_in=210, len_out=210, v0=50, limit=50, mix=MIX_FREIGHT,
                pid_in="JE.inS", pid_out="JE.outS", median=2.0, heat="Film City link road")

    # mainline arms need exit nodes; create them explicitly
    net.node("JW.x0", [-418, y3], "junction", name="Okhla Head · offside slip")
    net.node("JW.x180", [-418, -y3], "junction", name="Okhla Head · offside slip (WB)")
    net.node("JE.x0", [418, y3], "junction", name="Film City · offside slip (WB)")
    net.node("JE.x180", [418, -y3], "junction", name="Film City · offside slip (EB)")

    # ---- wiring
    # India drives on the left, so the nearside (left) turn is the free one and the
    # offside (right) turn needs its own stage.
    ph_main = {"through": 0, "left": None, "right": 1}
    ph_cross = {"through": 1, "left": None, "right": 0}
    wt_main = {"through": 0.79, "left": 0.14, "right": 0.07}
    wt_cross = {"through": 0.5, "left": 0.32, "right": 0.18}

    eb_in = anchors(net, K1a, "end")
    wb_in = anchors(net, K4b, "end")
    jw_arms = [{"a_out": anchors(net, K2a, "start"), "pid_in": "JW.inN", "a_in": eb_in,
                "ex": "JW.x0"},
               {"a_out": anchors(net, K5b, "start"), "pid_in": "JW.inS", "a_in": wb_in,
                "ex": "JW.x180"}]
    all_out_w = (anchors(net, K2a, "start") + anchors(net, K5b, "start")
                 + A_W_N["a_out"] + A_W_S["a_out"])
    wire_junction(net, node_id="JW", info_in=eb_in, info_out=all_out_w,
                  phases=ph_main, weights=wt_main, limit=35)
    wire_junction(net, node_id="JW", info_in=wb_in, info_out=all_out_w,
                  phases=ph_main, weights=wt_main, limit=35)
    wire_junction(net, node_id="JW", info_in=A_W_N["a_in"], info_out=all_out_w,
                  phases=ph_cross, weights=wt_cross, limit=30)
    wire_junction(net, node_id="JW", info_in=A_W_S["a_in"], info_out=all_out_w,
                  phases=ph_cross, weights=wt_cross, limit=30)

    eb_in_e = anchors(net, K4a, "end")
    wb_in_e = anchors(net, K1b, "end")
    all_out_e = (anchors(net, K5a, "start") + anchors(net, K2b, "start")
                 + A_E_N["a_out"] + A_E_S["a_out"])
    wire_junction(net, node_id="JE", info_in=eb_in_e, info_out=all_out_e,
                  phases=ph_main, weights={"through": 0.78, "left": 0.15, "right": 0.07},
                  limit=35)
    wire_junction(net, node_id="JE", info_in=wb_in_e, info_out=all_out_e,
                  phases=ph_main, weights={"through": 0.81, "left": 0.13, "right": 0.06},
                  limit=35)
    wire_junction(net, node_id="JE", info_in=A_E_N["a_in"], info_out=all_out_e,
                  phases=ph_cross, weights={"through": 0.55, "left": 0.30, "right": 0.15},
                  limit=30)
    wire_junction(net, node_id="JE", info_in=A_E_S["a_in"], info_out=all_out_e,
                  phases=ph_cross, weights={"through": 0.52, "left": 0.31, "right": 0.17},
                  limit=30)

    # ---- portals: three lanes squeeze to two (kerb lane drop), and back out
    # EB: three approach lanes squeeze to two on the deck at the west portal ...
    taper_into(net, node_id="PW", src_lids=K2a, tgt_lids=K3a)
    # ... and spread back to three at the east portal
    taper_into(net, node_id="PE", src_lids=K3a, tgt_lids=K4a, all_targets=True,
               max_lat=1.4 * W)
    # WB: lane drop entering the deck at the east portal, gain at the west portal
    taper_into(net, node_id="PE", src_lids=K2b, tgt_lids=K3b)
    taper_into(net, node_id="PW", src_lids=K3b, tgt_lids=K4b, all_targets=True,
               max_lat=1.4 * W)
    # a dropped kerb lane must find a gap in the through lane it joins
    set_yield(net, [K2a[2]], [K3a[1]], gap_s=2.4, note="kerb lane drops at the west portal")
    set_yield(net, [K2b[2]], [K3b[1]], gap_s=2.4, note="kerb lane drops at the east portal (WB)")

    heal_lane_gains(net)

    # surveyed leg inflows (veh/h, peak hour) -- as-counted
    leg_flows = {"M1a": 4650, "M1b": 4300, "JW.inN": 780, "JW.inS": 640,
                 "JE.inN": 690, "JE.inS": 860}
    enumerate_demand(net, leg_flows=leg_flows)

    net.scenarios.extend([
        {"id": "truck_stall_deck", "name": "Truck straddles the deck kerb lane",
         "note": "A laden truck at 14 km/h in the deck's kerb lane; every following "
                 "vehicle is trapped behind it and the queue spills to the west portal.",
         "place": [{"link": "M3a.1", "s_m": 60, "v_kmph": 14, "class": "truck", "count": 1,
                    "hold": True}]},
        {"id": "peak_am", "name": "AM peak, both directions", "hour": 9,
         "multipliers": {"AP.M1a": 1.12, "AP.M1b": 1.05}},
        {"id": "deck_incident", "name": "Debris on deck (lane blockage)",
         "note": "Blocks the deck kerb lane for 8 minutes; watch the queue jump the portal.",
         "place": [{"link": "M3a.1", "s_m": 120, "v_kmph": 0, "class": "lcv", "count": 1,
                    "hold": True, "blocking": True}]},
    ])
    net.approach("AP.M1a", "Mathura Rd approach (EB, 3 lanes)", leg="west")
    net.approach("AP.M1b", "Noida-GN expressway approach (WB, 3 lanes)", leg="east")
    net.approach("AP.JW.inN", "Okhla Head Rd (north arm)", leg="north")
    net.approach("AP.JW.inS", "Vijay Marg (south arm)", leg="south")
    net.approach("AP.JE.inN", "Sector 18A link road (north arm)", leg="north")
    net.approach("AP.JE.inS", "Bindapur road (south arm)", leg="south")
    for apid, nm, leg in (("AP.M1a", "Mathura Rd approach (EB)", "west"),
                          ("AP.M1b", "Noida-GN expressway (WB)", "east"),
                          ("AP.Okhla Head Rd north inbound", "Okhla Head Rd (N arm)", "north"),
                          ("AP.Vijay Marg south inbound", "Vijay Marg (S arm)", "south"),
                          ("AP.Sector 18A link road inbound", "Sector 18A link (N arm)", "north"),
                          ("AP.Bindapur road inbound", "Bindapur rd (S arm)", "south")):
        net.approach(apid, nm, leg=leg)
    return net


# ==========================================================================
# 2. ITO  (multi-directional at-grade grid, standstill / gridlock stress)
# ==========================================================================
def build_ito():
    net = Net(
        site={"id": "ito", "name": "ITO Intersection", "kind": "urban_grid_at_grade",
              "image": "section_img/ITO.png",
              "survey": "Survey of India / NCT code-plate counts at ITO (5 arms), "
                        "weekend mid-day + weekday AM peak, plus ITDP Delhi junction inventories",
              "summary": "Five-leg at-grade crossing of the Ring Road (N-S, grade separated "
                         "over the centre), Vikas Marg (E-W) and Yamuna Marg (SE), with an "
                         "arterial off the old Minto Road. Six signal heads, short storage and a "
                         "pedestrian-heavy all-red: the stress case for standstill (v = 0) "
                         "detection and gridlock alerting."},
        imagery=_imagery("ito"),
        display={"px_per_m": 3.4, "origin_px": [960, 540], "rotation_deg": 0.0},
    )
    net.signal("S.ITO", "ITO main controller", [
        {"name": "Ring Road through (N-S)", "green": 42, "amber": 4, "all_red": 3},
        {"name": "Ring Road left + Vikas Marg E", "green": 26, "amber": 4, "all_red": 3},
        {"name": "Vikas Marg through (E-W)", "green": 38, "amber": 4, "all_red": 3},
        {"name": "Yamuna Marg + Minto Rd", "green": 22, "amber": 4, "all_red": 4},
    ], notes="Actuated in service; fixed-time here with the surveyed AM plan")
    net.signal("S.ITOPED", "Pedestrian scramble", [
        {"name": "Vehicle phases", "green": 122, "amber": 0, "all_red": 0},
        {"name": "Pedestrian all-red", "green": 0, "amber": 0, "all_red": 18},
    ], notes="18 s pedestrian scramble every cycle, all approaches held red")

    C = [0, 0]
    net.signal_node("JI", C, "S.ITO", "ITO chowk")
    for k, b in enumerate((0, 90, 180, 270, 58)):
        net.node(f"JI.x{b}", [math.cos(math.radians(b)) * 20, math.sin(math.radians(b)) * 20],
                 "junction", name=f"ITO offside slip {b:03d}")

    # arms: bearing is the direction *away* from the node
    A_E = arm(net, J="JI", name="Vikas Marg east", bearing_out=0, n_in=3, n_out=3,
              len_in=300, len_out=300, v0=60, limit=60, mix=MIX_ARTERIAL,
              pid_in="JI.inE", pid_out="JI.outE", median=2.5, heat="Vikas Marg")
    A_W = arm(net, J="JI", name="Vikas Marg west", bearing_out=180, n_in=3, n_out=3,
              len_in=300, len_out=300, v0=60, limit=60, mix=MIX_ARTERIAL,
              pid_in="JI.inW", pid_out="JI.outW", median=2.5, heat="Vikas Marg")
    A_N = arm(net, J="JI", name="BSZ Marg north", bearing_out=270, n_in=3, n_out=3,
              len_in=280, len_out=280, v0=60, limit=60, mix=MIX_HIGH_2W,
              pid_in="JI.inN", pid_out="JI.outN", median=2.5, heat="Ring Road")
    A_S = arm(net, J="JI", name="Bhairon Marg south", bearing_out=90, n_in=2, n_out=2,
              len_in=270, len_out=270, v0=60, limit=60, mix=MIX_HIGH_2W,
              pid_in="JI.inS", pid_out="JI.outS", median=2.5, heat="Ring Road")
    A_D = arm(net, J="JI", name="Yamuna Marg south-east", bearing_out=58, n_in=2, n_out=2,
              len_in=250, len_out=250, v0=55, limit=55, mix=MIX_COMMERCIAL,
              pid_in="JI.inD", pid_out="JI.outD", median=2.0, heat="Yamuna Marg")

    ph_EW = {"through": 2, "left": None, "right": 2}
    ph_NS = {"through": 0, "left": None, "right": 0}
    ph_D = {"through": 3, "left": None, "right": 3}
    all_out = A_E["a_out"] + A_W["a_out"] + A_N["a_out"] + A_S["a_out"] + A_D["a_out"]
    for A, ph, wt in ((A_E, ph_EW, {"through": 0.62, "left": 0.16, "right": 0.22}),
                      (A_W, ph_EW, {"through": 0.60, "left": 0.18, "right": 0.22}),
                      (A_N, ph_NS, {"through": 0.58, "left": 0.20, "right": 0.22}),
                      (A_S, ph_NS, {"through": 0.62, "left": 0.16, "right": 0.22}),
                      (A_D, ph_D, {"through": 0.55, "left": 0.20, "right": 0.25})):
        wire_junction(net, node_id="JI", info_in=A["a_in"], info_out=all_out,
                      phases=ph, weights=wt, limit=30, min_r=7.0)

    # ---- Ring Road overbridge (grade separated, free flow) -------------
    net.node("JB.N", [0, -215], "junction", name="Ring Road viaduct north portal")
    net.node("JB.S", [0, 215], "junction", name="Ring Road viaduct south portal")
    OB_S = corridor(net, pid="OBs", name="Ring Road viaduct (southbound)",
                    path=[line([ -5.5 - 2, -300], [-5.5 - 2, 300])], n_lanes=1,
                    frm="OBs.a", to="OBs.b", kind="overpass", carriageway="Ring Road viaduct",
                    v0=70, limit=70, mix=MIX_ARTERIAL, heat="Ring Road viaduct",
                    approach="AP.viaduct", grade="elevated", detectors=True)
    OB_N = corridor(net, pid="OBn", name="Ring Road viaduct (northbound)",
                    path=[line([5.5 + 2, 300], [5.5 + 2, -300])], n_lanes=1,
                    frm="OBn.a", to="OBn.b", kind="overpass", carriageway="Ring Road viaduct",
                    v0=70, limit=70, mix=MIX_ARTERIAL, heat="Ring Road viaduct",
                    approach="AP.viaduct", grade="elevated", detectors=True)
    term(net, OB_S, "start", "Ring Road viaduct north end")
    term(net, OB_S, "end", "Ring Road viaduct south end")
    term(net, OB_N, "start", "Ring Road viaduct south end")
    term(net, OB_N, "end", "Ring Road viaduct north end")

    # ---- demand -------------------------------------------------------
    heal_lane_gains(net)
    enumerate_demand(net, leg_flows={"JI.inE": 5400, "JI.inW": 5100, "JI.inN": 4700,
                                     "JI.inS": 3600, "JI.inD": 2450,
                                     "OBs": 1900, "OBn": 1750})
    net.scenarios.extend([
        {"id": "gridlock_spillback", "name": "Cross-town gridlock (all arms oversaturated)",
         "multipliers": {a: 1.85 for a in ("AP.Vikas Marg east inbound", "AP.Vikas Marg west inbound",
                                           "AP.BSZ Marg north inbound", "AP.Bhairon Marg south inbound",
                                           "AP.Yamuna Marg south-east inbound")},
         "note": "Sustains 185% demand so queues lock the box: standstill alerts fire on every arm."},
        {"id": "signal_fail_EW", "name": "Controller fault: E-W held red",
         "signal_override": {"S.ITO": {"phases": [{"name": "held red", "green": 0, "amber": 0,
                                                   "all_red": 60}]}}},
        {"id": "am_peak", "name": "AM peak (09:00 profile)", "hour": 9},
    ])
    for A, nm, leg in ((A_E, "Vikas Marg east inbound (3 lanes)", "east"),
                       (A_W, "Vikas Marg west inbound (3 lanes)", "west"),
                       (A_N, "BSZ Marg north inbound (3 lanes)", "north"),
                       (A_S, "Bhairon Marg south inbound (2 lanes)", "south"),
                       (A_D, "Yamuna Marg inbound (2 lanes)", "south-east")):
        net.approach(f"AP.{nm}", nm, leg=leg)
    net.approach("AP.viaduct", "Ring Road viaduct (grade separated)", leg="overbridge")
    return net


# ==========================================================================
# roundabout / ring-road machinery  (shared by Gaur City and Connaught Place)
# ==========================================================================
def ring_nodes(net, *, centre, radius, bearings, entry_lead=22.0, exit_lead=22.0,
               sig=None, phase_of=None, n_lanes=2, node_r=None, tag="RG"):
    """Create the entry/exit nodes around a ring, ordered by circulating angle."""
    R = node_r if node_r is not None else radius
    pts = []
    for k, b in enumerate(bearings):
        for kind, ang in (("in", b + entry_lead), ("out", b - exit_lead)):
            a = math.radians(ang)
            xy = [centre[0] + R * math.cos(a), centre[1] + R * math.sin(a)]
            nid = f"{tag}.{k}.{kind}"
            if kind == "in" and sig:
                net.signal_node(nid, xy, sig, name=f"ring entry {k + 1}",
                                phase=phase_of[k] if phase_of else k)
            elif kind == "out":
                net.node(nid, xy, "junction", name=f"ring exit {k + 1}")
            else:
                net.priority_node(nid, xy, name=f"ring entry {k + 1}")
            pts.append({"angle": ang % 360.0, "id": nid, "arm": k, "kind": kind, "xy": xy})
    pts.sort(key=lambda p: p["angle"])
    return pts


def ring_links(net, *, centre, radius, nodes, lanes, pid, name, direction=+1,
               v0=35.0, limit=40.0, mix=None, heat="", approach="", ring_lane=1,
               kind="ring", queueable=True, exit_node=None):
    """Circulating links between successive ring nodes (one link per node gap,
    per circulating lane).  direction=+1 circulates with increasing angle."""
    n = len(nodes)
    out = []
    for i in range(lanes):
        r = radius + (ring_lane - i) * W * 1.0 if lanes > 1 else radius
        segs = []
        for k in range(n):
            a0 = nodes[k]["angle"]
            a1 = nodes[(k + 1) % n]["angle"]
            if direction > 0 and a1 <= a0:
                a1 += 360.0
            if direction < 0 and a1 >= a0:
                a1 -= 360.0
            frm = nodes[k]["id"] if direction > 0 else nodes[(k + 1) % n]["id"]
            to = nodes[(k + 1) % n]["id"] if direction > 0 else nodes[k]["id"]
            ids = corridor(net, pid=f"{pid}.{i}.{k}", name=f"{name} lane {i + 1} seg {k + 1}",
                           path=[arc(centre, r, a0, a1)], n_lanes=1, frm=frm, to=to,
                           kind=kind, carriageway=name, v0=v0, limit=limit, mix=mix,
                           heat=heat or name, approach=approach or name, queueable=queueable)
            segs.extend(ids)
        out.append({"lane": i, "links": segs})
    return out


def exit_weights(shares):
    """Turn per-node exit shares into the constant-decision weights the ring needs."""
    tot = sum(shares)
    out, rem = [], tot
    run = 0.0
    for s in shares:
        out.append(round(s / max(1e-9, rem), 5))
        run += s
        rem = tot - run
    return out


# 3. Gaur City Char Murti  (signalised roundabout)
# ==========================================================================
def build_gaur_city():
    net = Net(
        site={"id": "gaur_city", "name": "Gaur City Char Murti Chowk",
              "kind": "signalised_roundabout", "image": "section_img/GaurCIty_charmurtiG.png",
              "survey": "Greater Noida Authority junction counts at Char Murti (Sector 1), "
                        "weekday PM peak video classification; island geometry from the imagery",
              "summary": "Four-arm signalised roundabout: entries are metered by signals rather "
                         "than pure gap acceptance, so the ring discharges in bands while queues "
                         "sit on the approaches. Channelised nearside slip lanes bypass the "
                         "signals - the left-turn streams keep moving while the arms stand still."},
        imagery=_imagery("gaur_city"),
        display={"px_per_m": 6.2, "origin_px": [960, 540], "rotation_deg": 0.0},
    )
    C = [0.0, 0.0]
    RAD = 26.0
    bearings = [180.0, 270.0, 0.0, 90.0]
    names = ["Gaur Road (west)", "Site-5 approach road (north)",
              "Greater Noida West link (east)", "Ganga Road (south)"]
    flows = [4100, 2650, 3550, 3000]
    lanes = [(3, 3), (2, 2), (3, 2), (2, 2)]
    DIN, DOUT = 40.0, 25.0

    net.signal("S.GC", "Char Murti ring controller", [
        {"name": f"{n} entry", "green": g, "amber": 4, "all_red": 4}
        for n, g in zip(names, (30, 20, 28, 24))
    ], notes="One stage per arm; the circulating carriageway is never held and keeps "
             "discharging while an approach is red")

    specs = []
    for k, b in enumerate(bearings):
        specs.append({"kind": "in", "arm": k, "ang": mouth_beta(b + 180.0, DIN),
                      "name": f"{names[k]} entry"})
        specs.append({"kind": "out", "arm": k, "ang": mouth_beta(b, DOUT),
                      "name": f"{names[k]} exit"})
    nodes, by_lane, radii = build_ring(
        net, centre=C, radius=RAD, lanes=2, specs=specs, sig="S.GC",
        phase_of=lambda k: k, pid="RING", tag="RG", heat="Circulating carriageway",
        v0=32, limit=35, mix=MIX_HIGH_2W)

    arms = [ring_arm(net, centre=C, radius=RAD, ring_lanes=2, arm_index=k,
                     bearing_out=b, name=nm, n_in=li, n_out=lo, arm_len=230,
                     nodes=nodes, delta_in=DIN, delta_out=DOUT, v0=45, limit=45,
                     mix=MIX_HIGH_2W, slip=True)
            for k, (b, nm, (li, lo)) in enumerate(zip(bearings, names, lanes))]

    for k, A in enumerate(arms):
        yc = []
        for ids in by_lane:
            yc += ends_at(net, A["nid"], ids)
        wire_ring_entry(net, node_id=A["nid"], src_lids=A["in"], by_lane=by_lane,
                        phase=k, limit=32.0, slip=A.get("slip"),
                        yield_conflicts=yc)
    p_seq = [0.34, 0.42, 0.55, 1.0]
    for k, A in enumerate(arms):
        wire_ring_exit(net, node_id=A["xid"], tgt_lids=A["out"], by_lane=by_lane,
                       p=p_seq[k], limit=32.0)
    heal_lane_gains(net)

    leg_flows = {}
    for k, A in enumerate(arms):
        leg_flows[A["pid_in"]] = flows[k] * 0.82
        leg_flows[f"AR{k}.sl"] = flows[k] * 0.18
    enumerate_demand(net, leg_flows=leg_flows, max_hops=22)

    net.scenarios.extend([
        {"id": "ring_lockup", "name": "Ring lock-up (east arm oversaturated)",
         "multipliers": {f"AP.{names[2]}": 1.9},
         "note": "Two arms keep discharging into the ring; watch the circulating queue "
                 "block the upstream slip merge and then the entries."},
        {"id": "controller_dark", "name": "Controller dark (all-way give way)",
         "signal_state": {"S.GC": "dark"},
         "note": "Entries fall back to gap acceptance only - the standstill detector "
                 "lights up on the ring."},
        {"id": "pm_peak", "name": "PM peak (18:00 profile)", "hour": 18},
    ])
    for A in arms:
        net.approach(f"AP.{A['name']}", f"{A['name']} (entry + slip)",
                     leg={180: "west", 270: "north", 0: "east", 90: "south"}[A["bearing"]])
    net.approach("AP.Circulating carriageway", "Circulating carriageway", leg="ring")
    return net


    heal_lane_gains(net)

    leg_flows = {}
    for k, A in enumerate(arms):
        leg_flows[A["pid_in"]] = flows[k] * 0.82
        leg_flows[f"AR{k}.sl"] = flows[k] * 0.18
    enumerate_demand(net, leg_flows=leg_flows, max_hops=22)

    net.scenarios.extend([
        {"id": "ring_lockup", "name": "Ring lock-up (east arm oversaturated)",
         "multipliers": {f"AP.{names[2]}": 1.9},
         "note": "Two arms keep discharging into the ring; watch the circulating queue "
                 "block the upstream slip merge and then the entries."},
        {"id": "controller_dark", "name": "Controller dark (all-way give way)",
         "signal_state": {"S.GC": "dark"},
         "note": "Entries fall back to gap acceptance only - the standstill detector "
                 "lights up on the ring."},
        {"id": "pm_peak", "name": "PM peak (18:00 profile)", "hour": 18},
    ])
    for A in arms:
        net.approach(f"AP.{A['name']}", f"{A['name']} (entry + slip)",
                     leg={180: "west", 270: "north", 0: "east", 90: "south"}[A["bearing"]])
    net.approach("AP.Circulating carriageway", "Circulating carriageway", leg="ring")
    return net

# 4. Connaught Place  (concentric Inner/Outer Circles + radial connectors)
# ==========================================================================
def build_connaught_place():
    net = Net(
        site={"id": "connaught_place", "name": "Connaught Place",
              "kind": "concentric_circles_and_radials", "image": "section_img/CP.png",
              "survey": "Lutyens' bazaar cordon reconstruction: ring and radial turning counts "
                        "from the CP area traffic study, 12-h weekday; ring radii measured on the "
                        "satellite capture (Outer Circle ~95 m, Inner Circle ~42 m)",
              "summary": "One-way Outer and Inner Circles pierced by six radial corridors. "
                         "Every radial is metered twice - once at its Outer Circle entry and "
                         "again where the circulating band penetrates the Inner Circle - so a "
                         "plaza crossing costs a lap of each band and almost every movement "
                         "corners. That makes this the site where the curvature term a_curve "
                         "dominates: cars slow through the 42 m Inner Circle and re-accelerate "
                         "on the exit, while inner trips that must cross both bands and the "
                         "radial exits form queues continuously rather than in bands."},
        imagery=_imagery("connaught_place"),
        display={"px_per_m": 3.6, "origin_px": [960, 540], "rotation_deg": 0.0},
    )
    C = [0.0, 0.0]
    R_OUT, R_IN = 95.0, 42.0
    L_OUT, L_IN = 3, 2
    bearings = [30.0, 90.0, 150.0, 210.0, 270.0, 330.0]
    names = ["Barakhamba Road (ENE)", "Ashoka Road (ESE)", "Aurobindo Marg (SSE)",
             "Rafi Marg (WSW)", "Ranjit Singh Marg (WNW)", "Jantar Mantar Road (NNW)"]
    short = [n.split(" (")[0] for n in names]
    flows = [3100, 2450, 2800, 3400, 2650, 2450]
    lanes = [(2, 2), (2, 2), (2, 2), (3, 2), (2, 2), (2, 2)]
    DIN, DOUT = 40.0, 25.0     # the Char Murti trumpet rule, mirrored here
    edge_o = R_OUT + L_OUT * W          # outer face of the Outer Circle band

    net.signal("S.CPX", "Circle crossings", [
        {"name": f"{short[k]} stage {sname}", "green": g, "amber": 4, "all_red": 3}
        for k in range(6) for (sname, g) in (("A", 32), ("B", 26))
    ], notes="One stage pair per radial: A holds the Outer Circle mouths while the "
             "radial crosses it, B holds the Inner Circle mouths while the chord "
             "crosses the plaza - the circulating bands themselves are never held")
    net.signal("S.CPIN", "Inner Circle entries", [
        {"name": "Inner stage A", "green": 26, "amber": 4, "all_red": 3},
        {"name": "Inner stage B", "green": 22, "amber": 4, "all_red": 3},
        {"name": "Inner stage C", "green": 26, "amber": 4, "all_red": 3},
    ])

    # ---- Outer Circle. Mouth angles follow the same join/leave rule as at
    # Char Murti, so radial traffic reaches the ring with a 40 deg left swing
    # and leaves it with a 25 deg right peel.
    specs_o = []
    for k, b in enumerate(bearings):
        specs_o.append({"kind": "in", "arm": k, "ang": mouth_beta(b + 180.0, DIN),
                        "name": f"{short[k]} / Outer Circle crossing"})
        specs_o.append({"kind": "out", "arm": k, "ang": mouth_beta(b, DOUT),
                        "name": f"{short[k]} Outer exit"})
    nodes_o, by_lane_o, radii_o = build_ring(
        net, centre=C, radius=R_OUT, lanes=L_OUT, specs=specs_o, sig="S.CPX",
        phase_of=lambda k: 2 * k, pid="OUT", tag="RO", heat="Outer Circle",
        v0=34, limit=40, mix=MIX_ARTERIAL)

    arms = [ring_arm(net, centre=C, radius=R_OUT, ring_lanes=L_OUT, arm_index=k,
                     bearing_out=b, name=nm, n_in=li, n_out=lo,
                     arm_len=edge_o + 150.0, nodes=nodes_o, delta_in=DIN,
                     delta_out=DOUT, v0=50, limit=50, mix=MIX_ARTERIAL,
                     heat="Radials", median=4.0, slip=True)
            for k, (b, nm, (li, lo)) in enumerate(zip(bearings, names, lanes))]

    # ---- Inner Circle: the same construction mirrored about the island.  Its
    # band is authored with inside=True so circulation runs the other way
    # (the plaza keeps to the driver's right), and its mouth nodes sit on the
    # plaza-side circulating lane line at the same join/leave deltas - which is
    # what lets each radial be metered twice, once per circle, and corner
    # through both with a real turning arc at every mouth.
    specs_i = []
    for k, b in enumerate(bearings):
        specs_i.append({"kind": "in", "arm": k, "ang": mouth_beta(b + 180.0, DIN),
                        "name": f"{short[k]} / Inner Circle entry"})
        specs_i.append({"kind": "out", "arm": k, "ang": mouth_beta(b, DOUT),
                        "name": f"{short[k]} / Inner Circle exit"})
    nodes_i, by_lane_i, radii_i = build_ring(
        net, centre=C, radius=R_IN, lanes=L_IN, specs=specs_i, sig="S.CPIN",
        phase_of=lambda k: k % 3, pid="INN", tag="RI", heat="Inner Circle",
        v0=28, limit=35, mix=MIX_HIGH_2W, inside=True)

    # ---- wiring: both circles meter the same six radials.  Entries are
    # signalised, exits take one target per circulating lane, and the keep-going
    # share is re-weighted so a lap of each band discharges progressively.
    for k, A in enumerate(arms):
        for nid, by_lane_, ph in ((A["nid"], by_lane_o, 2 * k),
                                  (f"RI.in{k}", by_lane_i, 2 * k + 1)):
            yc = []
            for ids in by_lane_:
                yc += ends_at(net, nid, ids)
            wire_ring_entry(net, node_id=nid, src_lids=A["in"], by_lane=by_lane_,
                            phase=ph, limit=36.0,
                            slip=(A.get("slip") if by_lane_ is by_lane_o else None),
                            yield_conflicts=yc)
    p_out = [0.30, 0.36, 0.42, 0.50, 0.62, 1.0]
    for k, A in enumerate(arms):
        wire_ring_exit(net, node_id=A["xid"], tgt_lids=A["out"], by_lane=by_lane_o,
                       p=p_out[k], limit=36.0)
        wire_ring_exit(net, node_id=f"RI.out{k}", tgt_lids=A["out"],
                       by_lane=by_lane_i, p=0.55, limit=32.0)
    # the Inner Circle is reached by penetration *from* the Outer one: each
    # circulating lane dives across the plaza at the first inner entry its arc
    # can legally reach, which is the movement that makes CP's queues grow even
    # while every approach has a green.
    for k in range(6):
        wire_ring_penetration(net, src_node=f"RO.out{k}", tgt_node=f"RI.in{k}",
                              by_lane_src=by_lane_o, by_lane_tgt=by_lane_i,
                              p=0.30, phase=k % 3, limit=30.0)
        # ... and back out: the Inner Circle discharges across the Outer one to
        # the radial, so both bands have a way off them and an inner trip costs
        # two penetrations plus a lap of each circle.
        wire_ring_penetration(net, src_node=f"RI.out{k}", tgt_lids=A["out"],
                              by_lane_src=by_lane_i, p=0.65, limit=30.0)

    heal_lane_gains(net)

    legs = {}
    for k, A in enumerate(arms):
        legs[A["pid_in"]] = flows[k] * 0.80
        legs[f"AR{k}.sl"] = flows[k] * 0.20
    # With two nested rings every origin can reach every destination by several
    # laps, so the surveyed movements are enumerated as one shortest legal lane
    # path per origin/destination pair rather than by walking the whole turn
    # graph (which would explode combinatorially here).
    plan_movements(net, legs=legs, max_hops=34,
                   note="plaza circuit (cordon-derived, shortest legal lane path)")

    net.scenarios.extend([
        {"id": "vip_route", "name": "Vip movement: Barakhamba closed",
         "multipliers": {f"AP.{names[0]}": 0.0},
         "note": "The ENE radial is shut; its traffic creeps round the Outer "
                 "Circle instead and the ring queues back onto the crossings."},
        {"id": "ring_flood", "name": "Ring flood (Inner Circle over-supplied)",
         "multipliers": {**{f"AP.{n}": 1.6 for n in names},
                         **{f"AP.{n} chord": 2.2 for n in names}},
         "note": "Every radial pushes harder than the Inner Circle can discharge - "
                 "watch the standstill alert trip inside the plaza."},
        {"id": "curve_study", "name": "Curvature study (20 km/h through the plaza)",
         "speed_limits": {"INN": 20.0, "OUT": 25.0},
         "note": "Limits cut on both circles to isolate the a_curve term's "
                 "platoon-shockwave effect on the ring."},
    ])
    for A in arms:
        net.approach(f"AP.{A['name']}", A["name"], leg="radial")
    net.approach("AP.Outer Circle", "Outer Circle ring", leg="ring")
    net.approach("AP.Inner Circle", "Inner Circle ring", leg="ring")
    return net





# ==========================================================================
# 5. Botanical / Okhla cloverleaf  (grade separated, tight loop ramps)
# ==========================================================================
def build_botanical_okhla():
    net = Net(
        site={"id": "botanical_okhla", "name": "Botanical Okhla Interchange",
              "kind": "cloverleaf_grade_separated", "image": "section_img/Botanical_interchange.png",
              "survey": "DND / Okhla-Circular ramp counts (toll-plaza classified counts "
                        "reconstruction), weekday PM peak; ramp radii from the imagery",
              "summary": "X-shaped cloverleaf: the DND mainline runs SW-NE over the Okhla "
                         "Circular Road, with four 19 m-radius loop ramps carrying the left turns "
                         "and four channelised right-turn slips. Loop ramps are the curvature "
                         "stress case (v^2/R at 50 km/h on R = 19 m exceeds the 2 m/s² lateral "
                         "comfort bound, so every vehicle brakes on entry and accelerates on exit)."},
        imagery=_imagery("botanical_okhla"),
        display={"px_per_m": 3.0, "origin_px": [960, 540], "rotation_deg": -28.0},
    )
    MAJOR = 620.0            # half length of each mainline
    GAP = 2.5 * W            # median between directions of one mainline
    yA = None
    net.signal("S.BO", "Surface crossing under the bridge", [
        {"name": "Circular Road through", "green": 40, "amber": 4, "all_red": 3},
        {"name": "Okhla link road", "green": 22, "amber": 4, "all_red": 4},
    ], notes="Only the at-grade surface moves are signalised; the ramps are free flow")
    net.signal("S.METER", "Northbound ramp meter", [
        {"name": "green (3 vehicles)", "green": 9, "amber": 2, "all_red": 2},
        {"name": "red", "green": 0, "amber": 0, "all_red": 6},
    ], strategy="ramp_meter", notes="Single-lane slip from the Circular Road is metered")

    # ---- mainline A (DND, along local x) and mainline B (Circular Rd, along y)
    def mainline(pid_root, axis, half, n, v0, mix, heat, name, gap=GAP):
        """Two directions of a straight mainline, each n lanes, split into
        inbound-to-interchange / outbound-from-interchange halves."""
        out = {}
        for d, sgn in (("a", 1), ("b", -1)):
            side = sgn * (gap / 2.0 + n * W / 2.0)
            if axis == "x":
                p_in = [line([-half, side], [0, side])]
                p_out = [line([0, side], [half, side])]
            else:
                p_in = [line([side, -sgn * half], [side, 0])]
                p_out = [line([side, 0], [side, sgn * half])]
            ins = corridor(net, pid=f"{pid_root}{d}.in", name=f"{name} inbound ({d})",
                           path=p_in, n_lanes=n, frm=f"{pid_root}{d}.in.a", to=f"{pid_root}.core",
                           kind="approach", carriageway=f"{name} in {d}", v0=v0, limit=v0,
                           mix=mix, approach=f"AP.{name} {d}", heat=heat)
            outs = corridor(net, pid=f"{pid_root}{d}.out", name=f"{name} outbound ({d})",
                            path=p_out, n_lanes=n, frm=f"{pid_root}.core", to=f"{pid_root}{d}.out.a",
                            kind="exit", carriageway=f"{name} out {d}", v0=v0, limit=v0,
                            mix=mix, approach=f"AP.{name} {d}", heat=heat)
            term(net, ins, "start", f"{name} {d} origin")
            term(net, outs, "end", f"{name} {d} destination")
            out[d] = {"in": ins, "out": outs, "side": side,
                      "a_in": anchors(net, ins, "end"), "a_out": anchors(net, outs, "start")}
        return out

    net.node("A.core", [0, 0], "junction", name="DND mainline · grade-separated crossing")
    net.node("B.core", [0, 0], "junction", name="Okhla Circular Rd · underpass")
    MA = mainline("A", "x", MAJOR, 2, 80, MIX_ARTERIAL, "DND mainline (SW-NE)", "DND mainline")
    MB = mainline("B", "y", MAJOR, 2, 80, MIX_FREIGHT, "Okhla Circular Rd (NW-SE)",
                  "Okhla Circular Rd")

    # Through movement on each mainline: the crossing is grade separated, so the
    # inbound half drains straight into the outbound half.
    direct_turns(net, list(zip(MA["a"]["in"], MA["a"]["out"])))
    direct_turns(net, list(zip(MA["b"]["in"], MA["b"]["out"])))
    direct_turns(net, list(zip(MB["a"]["in"], MB["a"]["out"])))
    direct_turns(net, list(zip(MB["b"]["in"], MB["b"]["out"])))

    # ---- ramp network: off-ramp, loop or slip, on-ramp merge
    LOAR, SLIPR = 19.0, 46.0
    def lane_point(axis, sgn, side, t):
        return ([t, side] if axis == "x" else [side, t]) if sgn > 0 else ([-t, -side] if axis == "x" else [-side, -t])

    ramps = []
    # left turns -> 270-degree loops, one per quadrant; right turns -> direct slips
    moves = [
        ("A", "a", "B", "a", "loop"), ("A", "a", "B", "b", "slip"),
        ("A", "b", "B", "b", "loop"), ("A", "b", "B", "a", "slip"),
        ("B", "a", "A", "b", "loop"), ("B", "a", "A", "a", "slip"),
        ("B", "b", "A", "a", "loop"), ("B", "b", "A", "b", "slip"),
    ]
    for idx, (fa, da, ta, dt, kind) in enumerate(moves):
        from_net = MA if fa == "A" else MB
        to_net = MA if ta == "A" else MB
        axis_in = "x" if fa == "A" else "y"
        axis_out = "x" if ta == "A" else "y"
        sgn_in = 1 if da == "a" else -1
        sgn_out = 1 if dt == "a" else -1
        u_in = [sgn_in * (1 if axis_in == "x" else 0), sgn_in * (1 if axis_in == "y" else 0)]
        u_out = [sgn_out * (1 if axis_out == "x" else 0), sgn_out * (1 if axis_out == "y" else 0)]
        side_in = from_net[da]["side"]
        off_d = 150.0 if kind == "loop" else 95.0
        entry = [u_in[0] * (-off_d if kind == "loop" else off_d * 0.35),
                 u_in[1] * (-off_d if kind == "loop" else off_d * 0.35)]
        if axis_in == "x":
            entry = [(-off_d if sgn_in > 0 else off_d * 0.35) * (1 if sgn_in > 0 else -1), side_in]
        else:
            entry = [side_in, (-off_d if sgn_in > 0 else off_d * 0.35) * (1 if sgn_in > 0 else -1)]
        # the ramp must land exactly on the destination outbound lane start: the
        # gore and the merge nose are fixed by the mainline, not by the arc, so
        # solve the loop backwards from the merge point.
        tgt_lids = [l for l in to_net[dt]["out"]]
        if not tgt_lids:
            continue
        merge_anchor = anchors(net, tgt_lids[-1:], "start")[0]
        _mg = merge_anchor["dir"]
        # the merge nose sits a short taper upstream of the lane start, so the
        # ramp can deliver a solvable entry arc instead of colliding with it
        exitp = [merge_anchor["q"][0] - _mg[0] * 18.0,
                 merge_anchor["q"][1] - _mg[1] * 18.0]
        u_out = _mg
        # off-ramp from the outer lane of the approach, then loop/slip, then merge
        src_lid = from_net[da]["in"][-1]
        pen = Pen(entry, bearing(entry, add(entry, u_in)))
        if kind == "loop":
            if not pen.loop_arc(exitp, u_out, 1, LOAR):
                continue
        else:
            if not pen.tangent_arc(exitp, u_out, 1, 12.0, 200.0) and \
                    not pen.biarc(exitp, u_out, min_r=12.0, max_r=400.0):
                continue
        # a loop ramp gets a lead-out so vehicles straighten before the merge;
        # a slip already meets the mainline at its own nose
        if kind == "loop":
            pen.forward(90.0)
        ramp_path = pen.path()
        pid = f"R{idx}"
        lids = corridor(net, pid=pid, name=f"{fa}{da}->{ta}{dt} {'loop ramp' if kind == 'loop' else 'slip ramp'}",
                        path=ramp_path, n_lanes=1, frm="A.core" if False else f"{pid}.n",
                        to=f"{pid}.m", kind="ramp" if kind == "loop" else "slip",
                        carriageway=f"Ramp {idx + 1}", v0=45 if kind == "loop" else 60,
                        limit=35 if kind == "loop" else 50, mix=MIX_RAMP,
                        approach=f"AP.ramp{idx}", heat=f"Ramps {fa}→{ta}",
                        notes=f"{'270° loop, R=19 m' if kind == 'loop' else 'channelised slip, R≈46 m'}")
        net.node(f"{pid}.n", entry, "junction", name=f"Ramp {idx + 1} gore")
        net.node(f"{pid}.m", pen.pos, "priority", name=f"Ramp {idx + 1} merge")
        # turn from the mainline approach into the ramp (drop lane) and from the ramp
        # into the target mainline downstream of the crossing
        tgt_links = tgt_lids
        direct_turns(net, [(src_lid, lids[0])], movement="right" if kind == "slip" else "left",
                     weight=0.30)
        net.links[src_lid]["phases"] = {}
        # merge onto the mainline: a parallel taper where the nose lines up with
        # the outbound lane (the normal case), otherwise a short turning
        # connector from the ramp nose - a slip that lands at a skew still has to
        # be joined round its own gore.
        _ma = anchors(net, lids, "end")
        taper_into(net, node_id=f"{pid}.m", src_lids=lids, tgt_lids=tgt_links,
                   weights={"through": 1.0}, limit=60.0, max_lat=8.0, tol=30.0)
        if not any(t["from"] in lids for t in net.turns):
            wire_junction(net, node_id=f"{pid}.m", info_in=_ma,
                          info_out=anchors(net, tgt_links, "start"), phases={},
                          weights={"through": 1.0}, limit=60,
                          auto_movement=True, min_r=8.0, max_r=4000.0)
        set_yield(net, lids, tgt_links, gap_s=2.3, kind="merge",
                  note="ramp merge gives way to the mainline through lane")
        ramps.append({"id": pid, "kind": kind, "from": fa + da, "to": ta + dt,
                      "lids": lids, "feed": src_lid})

    # ---- surface link road under the bridge (the signalised bit)
    net.signal_node("JS", [0, 250], "S.BO", "Okhla link road chowk")
    LA = arm(net, J="JS", name="Circular Rd south approach", bearing_out=90, n_in=1, n_out=1,
             len_in=180, len_out=180, v0=50, limit=50, mix=MIX_HIGH_2W, pid_in="JS.inS",
             pid_out="JS.outS", median=2.0, heat="Surface link road",
             out_to=None)
    LB = arm(net, J="JS", name="Okhla link road", bearing_out=270, n_in=1, n_out=1,
             len_in=180, len_out=180, v0=50, limit=50, mix=MIX_COMMERCIAL, pid_in="JS.inN",
             pid_out="JS.outN", median=2.0, heat="Surface link road")
    wire_junction(net, node_id="JS", info_in=LA["a_in"], info_out=LA["a_out"] + LB["a_out"],
                  phases={"through": 0, "left": 0, "right": 0},
                  weights={"through": 0.5, "left": 0.2, "right": 0.3}, limit=30)
    wire_junction(net, node_id="JS", info_in=LB["a_in"], info_out=LA["a_out"] + LB["a_out"],
                  phases={"through": 1, "left": 1, "right": 0},
                  weights={"through": 0.45, "left": 0.2, "right": 0.35}, limit=30)
    # link the surface road to the underpass so the crossing sees cross traffic
    net.turn(MB["a"]["out"][0], "JS.inS.0", "through", 0.12)
    net.turn("JS.outN.0", MB["a"]["in"][0], "through", 0.3)

    heal_lane_gains(net)
    enumerate_demand(net, leg_flows={"Aa.in": 5200, "Ab.in": 4800, "Ba.in": 4300,
                                     "Bb.in": 4100, "JS.inS": 900, "JS.inN": 1150})
    # ramp demand: give every ramp a share of the approach it is fed from
    for R in ramps:
        for d in net.demand:
            if d["route"][0] == R["feed"] and "route" == d["movement"]:
                pass
    net.scenarios.extend([
        {"id": "loop_closure", "name": "Loop ramp closed for resurfacing",
         "close_links": ["R0.0"], "note": "Left turn must be made via the surface street."},
        {"id": "meter_on", "name": "Ramp metering on the northbound slip",
         "signal_override": {"S.METER": {"phases": [{"name": "green", "green": 6, "amber": 1,
                                                      "all_red": 3},
                                                     {"name": "red", "green": 0, "amber": 0,
                                                      "all_red": 5}]}}},
        {"id": "pm_peak", "name": "PM peak inbound to Delhi", "hour": 18,
         "multipliers": {"AP.DND mainline b": 1.25}},
    ])
    for nm in ("AP.DND mainline a", "AP.DND mainline b", "AP.Okhla Circular Rd a",
               "AP.Okhla Circular Rd b", "AP.JS.inS", "AP.JS.inN"):
        net.approach(nm, nm.replace("AP.", "") + " approach", leg="ramp")
    for R in ramps:
        net.approach(f"AP.ramp{ramps.index(R)}", f"Ramp {R['from']} → {R['to']} "
                                                  f"({'loop' if R['kind'] == 'loop' else 'slip'})",
                     leg="ramp")
    return net

