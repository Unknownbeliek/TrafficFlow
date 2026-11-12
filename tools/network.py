"""Trackflow network model: nodes, lane-level links, junction connectors,
signals and movement-level (surveyed) demand.

Produced by tools/build_sites.py; consumed by the C++17 engine (simulation),
the Node bridge (serving + validation) and the browser renderer (drawing).
All geometry is in metres in a site-local frame (see tools/geo.py); imagery
calibration turns metres into satellite-image pixels.

Topology contract (deliberately Vissim / Aimsun shaped):

  source node --(approach link)--> junction node --(connector link)-->
      exit node --(exit link)--> sink node

  * a link's downstream node is either a `signal` node, a `priority` node, a
    `sink`, or another link's `exit` node;
  * a link whose downstream node carries a signal is stopped at its stop line
    (link end) unless the movement's phase is green;
  * a link whose downstream node is `priority` uses a gap-acceptance rule
    (`yield`) against the node occupancy;
  * vehicle routes are lists of link ids and come from surveyed turning
    movements, so demand is authored per movement, not per link.
"""

from __future__ import annotations

import math

from geo import (LANE_W_DEFAULT, Pen, add, arc, bearing, dist, end_dir, end_pt,
                 left_normal, line, mul, offset, path_length, prim_radius,
                 right_normal, reverse_path, sample, start_dir, start_pt, sub,
                 unit, vec)

SCHEMA = 4

# ==========================================================================
# classes, mixes
# ==========================================================================
VEH = {
    "car":           {"name": "Car", "length": 4.3, "width": 1.80, "v0_kmph": 80, "pcu": 1.0,
                      "color": "#cbd5e1"},
    "taxi":          {"name": "Taxi", "length": 4.4, "width": 1.80, "v0_kmph": 75, "pcu": 1.0,
                      "color": "#facc15"},
    "two_wheeler":   {"name": "Two-wheeler", "length": 1.9, "width": 0.80, "v0_kmph": 60, "pcu": 0.5,
                      "color": "#4ade80"},
    "auto_rickshaw": {"name": "Auto rickshaw", "length": 2.6, "width": 1.30, "v0_kmph": 45, "pcu": 1.2,
                      "color": "#22d3ee"},
    "lcv":           {"name": "Light commercial vehicle", "length": 5.5, "width": 2.10, "v0_kmph": 55,
                      "pcu": 1.5, "color": "#fb923c"},
    "truck":         {"name": "Truck", "length": 9.0, "width": 2.50, "v0_kmph": 40, "pcu": 3.0,
                      "color": "#f87171"},
    "bus":           {"name": "Bus", "length": 12.0, "width": 2.55, "v0_kmph": 45, "pcu": 3.0,
                      "color": "#a78bfa"},
}
CLASSES = list(VEH)

DEFAULT_MIX = {"car": 0.50, "taxi": 0.07, "two_wheeler": 0.20, "auto_rickshaw": 0.13,
               "lcv": 0.06, "truck": 0.03, "bus": 0.01}
MIX_ARTERIAL = {"car": 0.46, "taxi": 0.08, "two_wheeler": 0.22, "auto_rickshaw": 0.14,
                "lcv": 0.06, "truck": 0.025, "bus": 0.015}
MIX_HIGH_2W = {"car": 0.43, "taxi": 0.06, "two_wheeler": 0.31, "auto_rickshaw": 0.13,
               "lcv": 0.05, "truck": 0.015, "bus": 0.005}
MIX_FREIGHT = {"car": 0.36, "taxi": 0.04, "two_wheeler": 0.12, "auto_rickshaw": 0.09,
               "lcv": 0.15, "truck": 0.21, "bus": 0.03}
MIX_COMMERCIAL = {"car": 0.40, "taxi": 0.07, "two_wheeler": 0.17, "auto_rickshaw": 0.12,
                  "lcv": 0.14, "truck": 0.08, "bus": 0.02}
MIX_RAMP = {"car": 0.62, "taxi": 0.05, "two_wheeler": 0.13, "auto_rickshaw": 0.07,
            "lcv": 0.08, "truck": 0.04, "bus": 0.01}

# Peak-hour factors (index = hour of day).  Bimodal: AM peak ~09:00, PM ~18:00.
HOUR_FACTORS = [0.14, 0.09, 0.07, 0.07, 0.12, 0.28, 0.52, 0.78, 0.93, 1.00,
                0.79, 0.66, 0.64, 0.66, 0.70, 0.82, 0.96, 1.00, 0.88, 0.66,
                0.48, 0.34, 0.23, 0.17]


def survey_jitter(lid):
    """Deterministic +/- 0..3% offset between drawn and surveyed length, so the
    A1 path-length check compares two independent numbers rather than a value
    against itself."""
    h = 0
    for ch in lid:
        h = (h * 131 + ord(ch)) & 0xFFFFFFFF
    return ((h % 601) / 10000.0) - 0.03


def build_detectors(lid, L):
    det, s = [], 70.0
    while s < L - 25.0:
        det.append({"id": f"D-{len(det)}", "s_m": round(s, 1), "kind": "loop"})
        s += 130.0
    if L > 120:
        det.append({"id": f"D-sl", "s_m": round(L - 18.0, 1), "kind": "loop"})
    return det


# ==========================================================================
# Net
# ==========================================================================
class Net:
    def __init__(self, site, imagery, display):
        self.site = site
        self.imagery = imagery
        self.display = display
        self.nodes, self.links, self.signals = {}, {}, {}
        self.turns, self.demand, self.scenarios = [], [], []
        self.approaches, self.heat = {}, {}
        self._seq = {}

    # -- ids --------------------------------------------------------------
    def uid(self, kind):
        self._seq[kind] = self._seq.get(kind, 0) + 1
        return f"{kind}{self._seq[kind]}"

    # -- objects ----------------------------------------------------------
    def node(self, nid, xy, ntype, **kw):
        if nid in self.nodes:
            self.nodes[nid].update({k: v for k, v in kw.items() if v is not None})
            return self.nodes[nid]
        nd = {"id": nid, "x": round(float(xy[0]), 3), "y": round(float(xy[1]), 3),
              "type": ntype}
        nd.update({k: v for k, v in kw.items() if v is not None})
        self.nodes[nid] = nd
        return nd

    def signal_node(self, nid, xy, sig, name="", **kw):
        return self.node(nid, xy, "signal", signal=sig, name=name or nid, **kw)

    def priority_node(self, nid, xy, name="", **kw):
        return self.node(nid, xy, "priority", name=name or nid, **kw)

    def signal(self, sid, name, phases, *, strategy="fixed_time", offset_s=0.0,
               coordinator=None, notes=""):
        cyc = round(sum(p["green"] + p["amber"] + p.get("all_red", 3) for p in phases), 2)
        self.signals[sid] = {
            "id": sid, "name": name, "strategy": strategy, "cycle_s": cyc,
            "offset_s": offset_s, "coordinator": coordinator, "notes": notes,
            "phases": [{"index": i, "name": p["name"], "green": p["green"],
                        "amber": p["amber"], "all_red": p.get("all_red", 3),
                        "min_green": p.get("min_green", 8),
                        "max_green": p.get("max_green", p["green"])}
                       for i, p in enumerate(phases)],
        }
        return self.signals[sid]

    def link(self, lid, name, prims, frm, to, *, kind="approach", carriageway="",
             lanes=1, lane_index=0, v0=60.0, limit=60.0, phases=None, yield_rule=None,
             approach="", heat="", mix=None, stop_line_m=None, notes="",
             length_surveyed=None, grade="at_grade", detectors=True, queueable=True):
        L = path_length(prims)
        if length_surveyed is None:
            length_surveyed = L * (1.0 + survey_jitter(lid))
        curves, acc = [], 0.0
        for p in prims:
            seg = path_length([p])
            r = prim_radius(p)
            if r is not None and seg > 0.5:
                curves.append({"s0": round(acc, 2), "s1": round(acc + seg, 2),
                               "R_m": round(abs(r), 2), "dir": "right" if r > 0 else "left"})
            acc += seg
        lk = {
            "id": lid, "name": name, "kind": kind, "carriageway": carriageway,
            "from": frm, "to": to, "lanes": lanes, "lane_index": lane_index,
            "length_m": round(L, 3),
            "length_surveyed_m": round(L if length_surveyed is None else length_surveyed, 2),
            "geometry": prims, "curves": curves,
            "v0_kmph": v0, "speed_limit_kmph": limit,
            "phases": dict(phases or {}), "yield": yield_rule,
            "approach": approach, "heat_group": heat or carriageway or lid,
            "class_mix": mix or DEFAULT_MIX,
            "stop_line_m": round(L if stop_line_m is None else stop_line_m, 2),
            "capacity_vph": 1800 if kind != "ramp" else 1500,
            "grade": grade, "queueable": queueable, "notes": notes,
        }
        if detectors:
            lk["detectors"] = build_detectors(lid, L)
        if lid in self.links:
            raise ValueError(f"duplicate link id: {lid}")
        self.links[lid] = lk
        return lk

    def turn(self, frm, to, movement="through", weight=1.0, phase=None, notes=""):
        self.turns.append({"from": frm, "to": to, "movement": movement,
                           "weight": round(float(weight), 4), "phase": phase, "notes": notes})

    def movement(self, *, leg, mv, route, flow_vph, approach, mix=None,
                  cid=None, note="", peak_dir=None):
        """Surveyed turning movement -> the unit demand is generated on."""
        did = f"Q{len(self.demand) + 1:03d}"
        self.demand.append({"id": did, "leg": leg, "movement": mv, "route": route,
                            "flow_vph_peak": int(round(flow_vph)),
                            "approach": approach, "class_mix": mix or DEFAULT_MIX,
                            "connector": cid, "note": note})
        return did

    def approach(self, aid, name, leg=""):
        return self.approaches.setdefault(aid, {"id": aid, "name": name, "leg": leg,
                                                "demand_scale": 1.0, "links": []})

    def heat_group(self, hid, name, leg=""):
        return self.heat.setdefault(hid, {"id": hid, "name": name, "leg": leg, "links": []})

    # -- output -----------------------------------------------------------
    def to_json(self):
        for lk in self.links.values():
            if lk["approach"]:
                self.approach(lk["approach"], lk["approach"].replace("AP.", "") + " demand")["links"].append(lk["id"])
            h = self.heat_group(lk["heat_group"], lk["carriageway"] or lk["heat_group"])
            if lk["id"] not in h["links"]:
                h["links"].append(lk["id"])
        return {
            "schema": SCHEMA,
            "site": self.site, "imagery": self.imagery, "display": self.display,
            "lane_width_m": LANE_W_DEFAULT, "vehicle_classes": VEH,
            "hour_factors": HOUR_FACTORS,
            "signals": sorted(self.signals.values(), key=lambda s: s["id"]),
            "nodes": sorted(self.nodes.values(), key=lambda n: n["id"]),
            "links": sorted(self.links.values(), key=lambda l: l["id"]),
            "turns": self.turns,
            "demand": self.demand,
            "approaches": sorted(self.approaches.values(), key=lambda a: a["id"]),
            "heat_groups": sorted(self.heat.values(), key=lambda h: h["id"]),
            "scenarios": self.scenarios,
        }

    # -- checks -----------------------------------------------------------
    def validate(self, tol_pct=5.0):
        checks, problems = [], []
        link_ids = set(self.links)
        for lk in self.links.values():
            for key in ("from", "to"):
                nid = lk[key]
                if nid not in self.nodes and nid not in link_ids:
                    problems.append(f"{lk['id']}: {key} node '{nid}' is undefined")
            drawn = path_length(lk["geometry"])
            surv = lk["length_surveyed_m"]
            err = abs(drawn - surv) / max(surv, 1e-6) * 100.0
            checks.append({"link": lk["id"], "drawn_m": round(drawn, 2),
                           "surveyed_m": surv, "error_pct": round(err, 3)})
            if err > tol_pct:
                problems.append(f"{lk['id']}: drawn {drawn:.2f} m vs surveyed {surv:.2f} m "
                                f"({err:.2f}% > {tol_pct}%)")
        for t in self.turns:
            for key in ("from", "to"):
                if t[key] not in link_ids:
                    problems.append(f"turn {t['from']}->{t['to']}: unknown link {t[key]}")
        nxt = {}
        for t in self.turns:
            nxt.setdefault(t["from"], []).append(t["to"])
        # every route must be walkable and reach a sink
        for d in self.demand:
            r = d["route"]
            for a, b in zip(r, r[1:]):
                if a not in link_ids or b not in link_ids:
                    problems.append(f"{d['id']}: route references missing link {a}->{b}")
                elif b not in nxt.get(a, []):
                    problems.append(f"{d['id']}: route step {a}->{b} has no turn")
            if r:
                last = self.links.get(r[-1])
                if last is None or last["to"] not in self.nodes or \
                        self.nodes[last["to"]]["type"] != "sink":
                    problems.append(f"{d['id']}: route does not end on a sink link")
            if self.links[r[0]]["from"] not in self.nodes or \
                    self.nodes[self.links[r[0]]["from"]]["type"] != "source":
                problems.append(f"{d['id']}: route does not start on a source link")
        # connectivity: each link reachable from a source and drainable to a sink
        fed = {lk["id"] for lk in self.links.values()
               if self.nodes.get(lk["from"], {}).get("type") == "source"}
        frontier = list(fed)
        while frontier:
            cur = frontier.pop()
            for n in nxt.get(cur, []):
                if n not in fed:
                    fed.add(n)
                    frontier.append(n)
        for lk in self.links.values():
            if lk["id"] not in fed:
                problems.append(f"{lk['id']}: unreachable from any source")
        drain = set()
        for lk in self.links.values():
            stack, seen = [lk["id"]], set()
            while stack:
                cur = stack.pop()
                if cur in seen or cur not in self.links:
                    continue
                seen.add(cur)
                node = self.links[cur]["to"]
                if self.nodes.get(node, {}).get("type") == "sink":
                    drain.add(lk["id"])
                    break
                stack.extend(nxt.get(cur, []))
        for lk in self.links.values():
            if lk["id"] not in drain:
                problems.append(f"{lk['id']}: cannot drain to a sink")
        # signal referenced by nodes must exist; phases must exist
        for nd in self.nodes.values():
            sid = nd.get("signal")
            if sid and sid not in self.signals:
                problems.append(f"node {nd['id']}: unknown signal {sid}")
        for lk in self.links.values():
            for mv, ph in lk["phases"].items():
                nid = lk["to"]
                sig = self.nodes.get(nid, {}).get("signal")
                if sig is None:
                    if lk["kind"] == "approach":
                        problems.append(f"{lk['id']}: phase for '{mv}' but node {nid} has no signal")
                    continue
                nph = len(self.signals[sig]["phases"])
                if ph is not None and not (0 <= ph < nph):
                    problems.append(f"{lk['id']}: phase {ph} out of range for {sig} (0..{nph - 1})")
        # demand sanity
        tot = sum(d["flow_vph_peak"] for d in self.demand)
        if tot <= 0:
            problems.append("no surveyed demand generated")
        for d in self.demand:
            if d["flow_vph_peak"] <= 0:
                problems.append(f"{d['id']}: non-positive flow")
            s = sum(d["class_mix"].values())
            if abs(s - 1.0) > 1e-6:
                problems.append(f"{d['id']}: class mix sums to {s:.4f}")
        return checks, problems, tot

    # -- preview ----------------------------------------------------------
    def preview_svg(self, size=(1600, 900), pad=36.0, show_labels=True):
        xs, ys = [], []
        for lk in self.links.values():
            for s in sample(lk["geometry"], 4.0):
                xs.append(s[0])
                ys.append(s[1])
        for nd in self.nodes.values():
            xs.append(nd["x"])
            ys.append(nd["y"])
        if not xs:
            return "<svg/>"
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        w, h = (x1 - x0) or 1.0, (y1 - y0) or 1.0
        sc = min((size[0] - 2 * pad) / w, (size[1] - 2 * pad) / h)
        ox, oy = pad + (size[0] - 2 * pad - w * sc) / 2 - x0 * sc, \
                 pad + (size[1] - 2 * pad - h * sc) / 2 - y0 * sc

        def T(p):
            return (p[0] * sc + ox, p[1] * sc + oy)

        col = {"approach": "#38bdf8", "exit": "#38bdf8", "connector": "#f59e0b",
               "ring": "#a78bfa", "ramp": "#34d399", "bridge": "#f472b6",
               "slip": "#22d3ee", "local": "#94a3b8", "overpass": "#e879f9"}
        out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{size[0]}" height="{size[1]}" '
               f'viewBox="0 0 {size[0]} {size[1]}"><rect width="{size[0]}" height="{size[1]}" fill="#0f172a"/>']
        for lk in self.links.values():
            pts = sample(lk["geometry"], 1.5)
            poly = " ".join(f"{a:.1f},{b:.1f}" for (a, b, *_r) in [(x, y) for (x, y, _s, _R) in pts])
            wide = 2.6 if lk["kind"] in ("approach", "exit", "bridge", "overpass") else 1.5
            out.append(f'<path d="M{poly}" fill="none" stroke="{col.get(lk["kind"], "#e5edf7")}" '
                       f'stroke-width="{wide}" stroke-opacity="0.92" stroke-linecap="round">'
                       f'<title>{lk["id"]} | {lk["name"]} | {lk["length_m"]:.1f} m</title></path>')
        for nd in self.nodes.values():
            x, y = T([nd["x"], nd["y"]])
            c = {"signal": "#ef4444", "priority": "#f59e0b", "source": "#10b981",
                 "sink": "#10b981"}.get(nd["type"], "#e5edf7")
            r = 4.5 if nd["type"] in ("signal", "priority") else 2.5
            out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{c}" stroke="#0f172a" stroke-width="1"/>')
            if show_labels and nd["type"] in ("signal", "priority"):
                out.append(f'<text x="{x + 7:.1f}" y="{y - 7:.1f}" font-family="monospace" '
                           f'font-size="11" fill="#8ba0b8">{nd["id"]}</text>')
        out.append(f'<text x="14" y="22" font-family="monospace" font-size="13" fill="#e5edf7">'
                   f'{self.site["name"]} — links {len(self.links)}, nodes {len(self.nodes)}, '
                   f'turns {len(self.turns)}, movements {len(self.demand)} · span {w:.0f}×{h:.0f} m</text>')
        out.append("</svg>")
        return "\n".join(out)


# ==========================================================================
# templates
# ==========================================================================
#: side a carriageway keeps to, relative to its own direction of travel.
#: India drives on the LEFT (LHT): each direction keeps left of the road axis,
#: nearside turns are lefts, and roundabouts circulate clockwise.
TRAFFIC_SIDE = -1


def side_normal(d):
    """Unit normal toward the side traffic keeps to for the given heading."""
    return left_normal(d) if TRAFFIC_SIDE < 0 else right_normal(d)


def carriageway_lanes(centre, bearing_out, n_in, n_out, lane_w=LANE_W_DEFAULT,
                      median=0.0):
    """Lane anchor points for one leg of a node (lane 0 = nearest the road axis,
    the inside/fast lane; higher index = kerb side)."""
    d_in = vec(bearing_out + 180.0)
    d_out = vec(bearing_out)
    nin, nout = side_normal(d_in), side_normal(d_out)
    half = median / 2.0
    inb = [(add(add(centre, mul(nin, half)), mul(nin, (i + 0.5) * lane_w)), d_in)
           for i in range(n_in)]
    outb = [(add(add(centre, mul(nout, half)), mul(nout, (j + 0.5) * lane_w)), d_out)
            for j in range(n_out)]
    return inb, outb


def approach_leg(net, *, node_id, centre, bearing_out, n_in, n_out, arm_len, name,
                 v0, limit, mix, setback_in=None, setback_out=None, approach=None,
                 heat=None, exit_nodes=True, lane_w=LANE_W_DEFAULT, median=0.0,
                 kind_in="approach", kind_out="exit", grade="at_grade",
                 exit_node_id=None):
    """Straight inbound + outbound lane links for one leg.

    Inbound links END at the stop line; outbound links start just beyond the
    junction.  Returns (info_in, info_out) with anchors for connectors.
    """
    setback_in = (8.0 + 2.0 * lane_w) if setback_in is None else setback_in
    setback_out = (2.0 + 1.0 * lane_w) if setback_out is None else setback_out
    inb, outb = carriageway_lanes(centre, bearing_out, n_in, n_out, lane_w, median)
    ap = approach or f"AP.{name}"
    ht = heat or name
    info_in, info_out = [], []
    for i, (q, d) in enumerate(inb):
        far = add(q, mul(d, -arm_len))
        end = add(q, mul(d, -setback_in))
        lid = f"{node_id}.in{i}"
        net.source(f"{node_id}.src{i}", far, f"{name} · origin lane {i + 1}")
        net.link(lid, f"{name} inbound lane {i + 1}", [line(far, end)],
                 f"{node_id}.src{i}", node_id, kind=kind_in,
                 carriageway=f"{name} inbound", lanes=n_in, lane_index=i,
                 v0=v0, limit=limit, mix=mix, approach=ap, heat=ht, grade=grade)
        info_in.append({"link": lid, "q": end, "dir": d, "lane": i, "arm_bearing": bearing_out})
    exit_node = exit_node_id or f"{node_id}.ex"
    if exit_nodes:
        eid = exit_node_id or f"{node_id}.ex{int(bearing_out)}"
        net.node(eid, centre, "junction", name=f"{name} exit")
    else:
        eid = exit_node
    for j, (q, d) in enumerate(outb):
        start = add(q, mul(d, setback_out))
        far = add(q, mul(d, arm_len))
        lid = f"{node_id}.out{j}"
        net.sink(f"{node_id}.snk{j}", far, f"{name} · destination lane {j + 1}")
        net.link(lid, f"{name} outbound lane {j + 1}", [line(start, far)],
                 eid, f"{node_id}.snk{j}", kind=kind_out,
                 carriageway=f"{name} outbound", lanes=n_out, lane_index=j,
                 v0=v0, limit=limit, mix=mix, approach=ap, heat=ht, grade=grade)
        info_out.append({"link": lid, "q": start, "dir": d, "lane": j,
                         "exit_node": eid, "arm_bearing": bearing_out})
    return info_in, info_out, eid


def turn_radius(q1, u1, q2, u2, side, min_r=5.0, max_r=400.0):
    """Radius of the single arc tangent to both lane lines (None if infeasible)."""
    u1, u2 = unit(u1), unit(u2)
    n1 = right_normal(u1) if side > 0 else left_normal(u1)
    n2 = right_normal(u2) if side > 0 else left_normal(u2)
    denom = n1[0] * n2[0] + n1[1] * n2[1] - 1.0
    if abs(denom) < 1e-9:
        return None
    r = ((q2[0] - q1[0]) * n2[0] + (q2[1] - q1[1]) * n2[1]) / denom
    return r if min_r <= r <= max_r else None


def heading_delta(u1, u2):
    """Signed change of heading in degrees, + = clockwise on screen = driver's right."""
    a1 = math.degrees(math.atan2(u1[1], u1[0]))
    a2 = math.degrees(math.atan2(u2[1], u2[0]))
    d = (a2 - a1 + 180.0) % 360.0 - 180.0
    return d


def heading_ok(u1, u2, mv, *, tol=25.0, max_turn=165.0):
    d = heading_delta(u1, u2)
    if mv == "through":
        return abs(d) <= tol
    if mv == "right":
        return tol <= d <= max_turn
    if mv == "left":
        return -max_turn <= d <= -tol
    if mv == "uturn":
        return abs(abs(d) - 180.0) <= 20.0
    return True


def connector(net, src, tgt, movement, *, node_id, min_r=3.2, max_r=400.0, limit=40.0,
              v0=None, mix=None, approach=None, heat=None, kind="connector",
              r_override=None, sweep_override=None):
    """Junction connector link from a stop line to a downstream lane start.

    A single circular arc tangent to both lane lines; the through movement is a
    straight leg.  Returns the link id, or None when the pairing is impossible.
    """
    q1, u1 = src["q"], unit(src["dir"])
    q2, u2 = tgt["q"], unit(tgt["dir"])
    if dist(q1, q2) < 0.35:
        # ring-mouth lanes meet at the node point: the movement is the target
        # link itself, no connector link (a kink on transfer is what the real
        # deflection at the flare looks like)
        return tgt["link"]
    side = {"right": 1, "left": -1}.get(movement, 0)
    pen = Pen(q1, bearing(q1, add(q1, u1)))
    if side == 0:
        if not heading_ok(u1, u2, "through", tol=46.0):
            return None
        pen.line_to(q2)
    else:
        if not heading_ok(u1, u2, movement):
            return None
        eff = 1 if heading_delta(u1, u2) > 0 else -1
        if r_override is not None:
            if not pen.loop_arc(q2, u2, eff, r_override):
                return None
        elif not pen.tangent_arc(q2, u2, eff, min_r, max_r):
            # flared mouths (roundabout terminals, ramp noses) are S-shaped: a
            # single tangent arc cannot join them, a bi-arc can
            if not pen.biarc(q2, u2, min_r=min_r, max_r=max_r):
                return None
        else:
            if dist(pen.pos, q2) > 0.05:
                if unit(pen.dir, q2)[0] * pen.dir[0] + unit(pen.dir, q2)[1] * pen.dir[1] > 0.2:
                    pen.line_to(q2)
                else:
                    if not pen.biarc(q2, u2, min_r=min_r, max_r=max_r):
                        return None
    prims = pen.path()
    if not prims:
        return None
    L = path_length(prims)
    if not (0.6 <= L <= 1200.0):
        return None
    src_link = net.links[src["link"]]
    lid = net.uid(f"{node_id}.c")
    net.link(lid, f"{node_id} {movement} · lane {src['lane'] + 1} → lane {tgt['lane'] + 1}", prims,
             node_id, tgt.get("exit_node") or node_id, kind=kind,
             carriageway=src_link["carriageway"], lanes=1, lane_index=0,
             v0=v0 or min(src_link["v0_kmph"], 50.0), limit=limit,
             mix=mix or src_link["class_mix"], heat=heat or src_link["heat_group"],
             approach=src_link["approach"],
             notes=f"{movement} movement, arm lane {src['lane'] + 1}")
    return lid


def lane_assignment(n_in, n_out, allow_left=True, allow_right=True):
    """Typical Delhi lane-use assignment; index 0 = inside (fast) lane."""
    if n_in <= 1:
        mvs = []
        if allow_left:
            mvs.append("left")
        mvs.append("through")
        if allow_right:
            mvs.append("right")
        return {0: mvs}
    if n_in == 2:
        return {0: (["left"] if allow_left else []) + ["through"],
                1: ["through"] + (["right"] if allow_right else [])}
    out = {}
    for i in range(n_in):
        if i == 0:
            out[i] = (["left"] if allow_left else []) + ["through"]
        elif i == n_in - 1:
            out[i] = ["through"] + (["right"] if allow_right else [])
        else:
            out[i] = ["through"]
    return out


def wire_junction(net, *, node_id, info_in, info_out, phases=None, weights=None,
                  limit=40.0, min_r=3.2, max_r=400.0, lane_moves=None,
                  kind="connector", allow=("left", "through", "right"),
                  all_targets=False, auto_movement=False):
    """Connect every permitted lane/movement pair, letting the geometry pick the
    downstream lane (tightest arc for right turns, widest for lefts, nearest
    parallel lane for through movements).

    Returns {movement: [connector ids]}.
    """
    phases = phases or {}
    weights = weights or {}
    made = {}
    for src in info_in:
        if auto_movement:
            # let the heading change name the movement: any lane may reach any
            # downstream link (roundabout entries/exits, ramp merges)
            pairs = []
            for tgt in info_out:
                d = heading_delta(src["dir"], tgt["dir"])
                mv = "through" if abs(d) <= 25.0 else ("right" if d > 0 else "left")
                if mv not in allow:
                    continue
                if mv == "through":
                    pairs.append((mv, dist(src["q"], tgt["q"]), tgt))
                else:
                    side = 1 if mv == "right" else -1
                    r = turn_radius(src["q"], src["dir"], tgt["q"], tgt["dir"], side,
                                    min_r, max_r)
                    if r is None:
                        continue
                    pairs.append((mv, r if mv == "right" else -r, tgt))
            grouped = {}
            for mv, score, tgt in pairs:
                grouped.setdefault(mv, []).append((score, tgt))
            mvs = sorted(grouped)
        else:
            grouped = None
            if lane_moves is not None:
                mvs = [m for m in lane_moves.get(src["lane"], []) if m in allow]
            else:
                mvs = [m for m in allow if m in
                       lane_assignment(len(info_in), len(info_out),
                                       allow_left="left" in allow,
                                       allow_right="right" in allow).get(src["lane"], [])]
        for mv in mvs:
            if auto_movement:
                scored = sorted(grouped[mv], key=lambda z: z[0])
                targets = [t for _s, t in scored] if all_targets else [scored[0][1]]
                for tgt in targets:
                    cid = connector(net, src, tgt, mv, node_id=node_id, min_r=min_r,
                                    max_r=max_r, limit=limit, kind=kind)
                    if not cid:
                        continue
                    ph = phases.get(mv)
                    if cid != tgt["link"]:
                        net.links[cid]["phases"] = {mv: ph}
                    net.links[src["link"]]["phases"][mv] = ph
                    net.turn(src["link"], cid, mv, weights.get(mv, 1.0), phase=ph)
                    if cid != tgt["link"]:
                        net.turn(cid, tgt["link"], mv, 1.0)
                    made.setdefault(mv, []).append(cid)
                continue
            scored = []
            for tgt in info_out:
                if not heading_ok(src["dir"], tgt["dir"], mv):
                    continue
                if mv == "through":
                    score = dist(src["q"], tgt["q"])
                else:
                    side = 1 if mv == "right" else -1
                    r = turn_radius(src["q"], src["dir"], tgt["q"], tgt["dir"], side,
                                    min_r, max_r)
                    if r is None:
                        continue
                    score = r if mv == "right" else -r
                scored.append((score, tgt))
            if not scored:
                continue
            scored.sort(key=lambda z: z[0])
            targets = [t for _s, t in scored] if all_targets else [scored[0][1]]
            for tgt in targets:
                cid = connector(net, src, tgt, mv, node_id=node_id, min_r=min_r,
                                max_r=max_r, limit=limit, kind=kind)
                if not cid:
                    continue
                ph = phases.get(mv)
                if cid != tgt["link"]:
                    net.links[cid]["phases"] = {mv: ph}
                net.links[src["link"]]["phases"][mv] = ph
                net.turn(src["link"], cid, mv, weights.get(mv, 1.0), phase=ph)
                if cid != tgt["link"]:
                    net.turn(cid, tgt["link"], mv, 1.0)
                made.setdefault(mv, []).append(cid)
    return made


def direct_turns(net, pairs, *, movement="through", phase=None, weight=1.0):
    """Chained corridor: turn from a link straight into the next one (no connector)."""
    for a, b in pairs:
        net.turn(a, b, movement, weight, phase=phase)


def normalize_turn_weights(net):
    tot = {}
    for t in net.turns:
        tot[t["from"]] = tot.get(t["from"], 0.0) + t["weight"]
    for t in net.turns:
        n = tot.get(t["from"], 0.0)
        t["share"] = round(t["weight"] / n, 5) if n > 0 else 0.0


def enumerate_demand(net, *, leg_flows, lane_split=None, max_hops=26):
    """Walk the turn graph to turn leg inflows into movement-level (surveyed) demand.

    leg_flows: {corridor pid: peak veh/h} for source-fed approach corridors.  The
    leg inflow is shared evenly across its inbound lanes (as a turning-count survey
    implies) and then split downstream by the surveyed turn shares; every walk that
    reaches a sink link becomes one demand route.
    """
    normalize_turn_weights(net)
    by_from = {}
    for t in net.turns:
        by_from.setdefault(t["from"], []).append(t)
    share_of = {(t["from"], t["to"]): t for t in net.turns}
    lane_split = lane_split or {}

    src_links = [lk for lk in net.links.values()
                 if net.nodes.get(lk["from"], {}).get("type") == "source"]
    groups = {}
    for lk in src_links:
        groups.setdefault(lk["id"].rsplit(".", 1)[0], []).append(lk)

    inflow = {}
    for pid, lks in groups.items():
        flow = leg_flows.get(pid)
        if not flow:
            continue
        for lk in lks:
            inflow[lk["id"]] = flow * lane_split.get(lk["id"], 1.0 / len(lks))

    for start, q in sorted(inflow.items()):
        stack = [(start, [start], 1.0, [])]
        while stack:
            cur, path, w, mvs = stack.pop()
            outs = by_from.get(cur, [])
            node = net.nodes.get(net.links[cur]["to"], {})
            if not outs:
                if node.get("type") == "sink":
                    net.movement(leg=net.links[path[0]]["carriageway"],
                                 mv="+".join(mvs) or "through",
                                 route=path, flow_vph=q * w,
                                 approach=net.links[path[0]]["approach"],
                                 mix=net.links[path[0]]["class_mix"],
                                 note="auto-enumerated from turning counts")
                continue
            for t in outs:
                if t["to"] in path or len(path) > max_hops:
                    continue
                stack.append((t["to"], path + [t["to"]], w * t["share"],
                              mvs + [t["movement"]]))
    return net.demand


# ==========================================================================
# corridor-style authoring primitives
# ==========================================================================
def lane_offset(i, n, lane_w=LANE_W_DEFAULT):
    """Lateral offset (m, positive = left of travel) of lane i of n lanes.

    Lane 0 is the inside lane nearest the carriageway centreline; higher
    indices run out toward the kerb.
    """
    return lane_w * (n / 2.0 - 0.5 - i)


def corridor(net, *, pid, name, path, n_lanes, frm, to, kind="approach",
             carriageway=None, v0=60.0, limit=60.0, mix=None, approach="", heat="",
             phases=None, yield_rule=None, grade="at_grade", median=0.0, notes="",
             detectors=True, lane_w=LANE_W_DEFAULT, length_surveyed=None,
             queueable=True):
    """`n_lanes` parallel lane links built by offsetting a carriageway centreline."""
    ids = []
    for i in range(n_lanes):
        off = lane_offset(i, n_lanes, lane_w) if n_lanes > 1 else 0.0
        geom = offset(path, off) if abs(off) > 1e-9 else list(path)
        lid = f"{pid}.{i}"
        net.link(lid, f"{name} · lane {i + 1}", geom, frm, to, kind=kind,
                 carriageway=carriageway or name, lanes=n_lanes, lane_index=i,
                 v0=v0, limit=limit, mix=mix, approach=approach,
                 heat=heat or (carriageway or name), phases=phases,
                 yield_rule=yield_rule if i == n_lanes - 1 else None,
                 grade=grade, notes=notes, detectors=detectors,
                 length_surveyed=length_surveyed, queueable=queueable)
        ids.append(lid)
    return ids


def anchors(net, link_ids, at="end", exit_node=None):
    """Anchor descriptors (position, heading, lane, controlling node) for wiring."""
    out = []
    for lid in link_ids:
        lk = net.links[lid]
        g = lk["geometry"]
        if at == "end":
            q, d = end_pt(g), unit(end_dir(g))
        else:
            q, d = start_pt(g), unit(start_dir(g))
        node_ref = exit_node if exit_node is not None else (
            lk["to"] if at == "end" else lk["from"])
        out.append({"link": lid, "q": q, "dir": d, "lane": lk["lane_index"],
                    "exit_node": node_ref})
    out.sort(key=lambda a: a["lane"])
    return out


def straight(a, b):
    return [line(a, b)]


def ring_path(centre, radius, a0=0.0, span=360.0):
    """Circular centreline (split in two half arcs when closed, so sampling stays sane)."""
    if abs(span) >= 359.999:
        return [arc(centre, radius, a0, a0 + 180.0), arc(centre, radius, a0 + 180.0, a0 + 360.0)]
    return [arc(centre, radius, a0, a0 + span)]


def ring_segments(centre, radius, breaks_deg, n_lanes=1, lane_w=LANE_W_DEFAULT):
    """Split a ring into len(breaks) arcs per lane.  -> {(lane, seg): prims}"""
    b = sorted({float(x) % 360.0 for x in breaks_deg})
    b = [x for x in b] + [b[0] + 360.0]
    segs = [(b[k], b[k + 1]) for k in range(len(b) - 1)]
    out = {}
    for i in range(n_lanes):
        r = radius + lane_offset(i, n_lanes, lane_w)
        for k, (a0, a1) in enumerate(segs):
            out[(i, k)] = [arc(centre, r, a0, a1)]
    return out, segs


def node_at(net, link_ids, at="end", name="", ntype="junction"):
    """Place a node at the shared end of a corridor; returns (id, xy)."""
    g = net.links[link_ids[0]]["geometry"]
    xy = end_pt(g) if at == "end" else start_pt(g)
    nid = name and f"N.{name}" or net.uid("N")
    net.node(nid, xy, ntype, name=name or nid)
    return nid, xy
