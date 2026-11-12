"""Ring-road machinery: circular carriageways, radial arms, and the mouths
that join them (Gaur City's signalised roundabout, Connaught Place's twin
circles with radial penetrations).

Geometry model (tuned against the satellite captures):

* circulation keeps the island to the driver's right (India, LHT), which on a
  North-up map is clockwise = increasing angle in our screen frame;
* a ring is cut into links at junction mouths.  The mouth for traffic whose
  straight-ahead heading is H sits at ring angle

      beta = H - 90 - delta          (delta: join ~40 deg, leave ~25 deg)

  i.e. slightly *before* the tangency point, so arm<->ring connectors come out
  as natural flared arcs (what the trapezoidal mouths in the imagery look
  like) instead of hairpins.  Entry connectors routinely need the bi-arc
  (S-shaped) fallback in geo.Pen, which models the left-then-settle steer of a
  real entry; exits are gentle single arcs;
* Connaught Place penetrations between the two circles are authored as
  arm-exit + arm-entry pairs along each road's axis (the through movement from
  radial k enters the Inner Circle on its own axis and leaves on the axis of
  the opposite radial, as at the real Rani-Haveli-shaped plaza);
* every arm keeps a channelised nearside slip past the mouth (phase None)
  exactly like the channelised left turns at these junctions.
"""

from __future__ import annotations

import math

from geo import (LANE_W_DEFAULT, Pen, add, ang_of, arc, bearing, dist,
                 left_normal, line, mul, path_length, start_dir, end_dir, unit,
                 vec)
from network import (Net, anchors, connector, corridor, direct_turns,
                     heading_delta, turn_radius, wire_junction)

W = LANE_W_DEFAULT


def mouth_beta(H, delta):
    """Ring angle of the mouth for a driver heading H steering |delta| there."""
    return (H - 90.0 - delta) % 360.0


def _ray_circle(centre, r, q, u, forward=True):
    """First point q + t*u (t>0) lying on the circle of radius r about centre."""
    w = [q[0] - centre[0], q[1] - centre[1]]
    b = w[0] * u[0] + w[1] * u[1]
    c = w[0] * w[0] + w[1] * w[1] - r * r
    disc = b * b - c
    if disc < 0:
        return None
    s = math.sqrt(disc)
    for t in sorted((-b - s, -b + s)):
        if t > 0.5:
            return [q[0] + t * u[0], q[1] + t * u[1]]
    return None


# ==========================================================================
# ring construction
# ==========================================================================
def build_ring(net, *, centre, radius, lanes, specs, sig=None, phase_of=None,
               pid, tag, heat="Ring", v0=32.0, limit=35.0, mix=None,
               inside=False):
    """Nodes + circulating links for one ring.

    `specs`: list of {"kind": "in"|"out"|"xi"|"xo", "ang": deg, "arm": int,
    "name": str}.  "in"/"xi" mouths are signal nodes when `sig` is given and
    `phase_of(arm)` is not None, otherwise give-way priority nodes; "out"/"xo"
    are plain junctions.  Returns (nodes_sorted, by_lane, radii): lane 0 is the
    island-side lane and by_lane[lane][m] runs from nodes_sorted[m] to m+1.
    """
    sgn = -1.0 if inside else 1.0
    radii = [radius + sgn * (i + 0.5) * W for i in range(lanes)]
    nodes = sorted(specs, key=lambda s: s["ang"] % 360.0)
    n = len(nodes)
    # nearside circulating lane line: outboard of the island radius for an
    # outer ring, inboard (toward the centre) for a ring driven clockwise
    # around a central plaza, as at Connaught Place's Inner Circle.
    node_r = radius + 0.5 * W
    for nd in nodes:
        a = math.radians(nd["ang"])
        xy = [centre[0] + node_r * math.cos(a), centre[1] + node_r * math.sin(a)]
        nd["id"] = f"{tag}.{nd['kind']}{nd['arm']}"
        nd["xy"] = xy
        ph = phase_of(nd["arm"]) if phase_of else None
        if nd["kind"] in ("in", "xi") and ph is not None and sig:
            net.signal_node(nd["id"], xy, sig, name=nd["name"], phase=ph)
        elif nd["kind"] in ("in", "xi"):
            net.priority_node(nd["id"], xy, name=nd["name"])
        else:
            net.node(nd["id"], xy, "junction", name=nd["name"])
    by_lane = []
    for i in range(lanes):
        ids = []
        for m in range(n):
            a0 = nodes[m]["ang"] % 360.0
            a1 = nodes[(m + 1) % n]["ang"] % 360.0
            if inside:
                # a circle driven round a central plaza keeps the plaza to the
                # driver's left (India, LHT): the sweep runs the other way and
                # the tangent heading is beta - 90 rather than beta + 90.
                if a1 >= a0:
                    a1 -= 360.0
            elif a1 <= a0:
                a1 += 360.0
            ids += corridor(net, pid=f"{pid}.l{i}.m{m}",
                            name=f"{heat} · lane {i + 1} seg {m + 1}",
                            path=[arc(centre, radii[i], a0, a1)], n_lanes=1,
                            frm=nodes[m]["id"], to=nodes[(m + 1) % n]["id"],
                            kind="ring", carriageway=heat, v0=v0, limit=limit,
                            mix=mix, heat=heat, approach=f"AP.{heat}")
        by_lane.append(ids)
    for ids in by_lane:                       # keep the ring closed
        direct_turns(net, list(zip(ids, ids[1:] + ids[:1])))
    return nodes, by_lane, radii


def node_for(nodes, kind, arm):
    for nd in nodes:
        if nd["kind"] == kind and nd["arm"] == arm:
            return nd["id"]
    raise KeyError(f"no {kind} node for arm {arm}")


def ends_at(net, node_id, lane_ids):
    return [l for l in lane_ids if net.links[l]["to"] == node_id]


def starts_at(net, node_id, lane_ids):
    return [l for l in lane_ids if net.links[l]["from"] == node_id]


# ==========================================================================
# arms and penetrations
# ==========================================================================
def ring_arm(net, *, centre, radius, ring_lanes, arm_index, bearing_out, name,
             n_in, n_out, arm_len, nodes, delta_in=40.0, delta_out=25.0,
             v0=45.0, limit=45.0, mix=None, median=2.0, mouth_clear_in=16.0,
             mouth_clear_out=13.0, slip=True, pid_root=None, heat=None,
             open_ends=True, from_id=None, to_id=None, kind_in="approach",
             kind_out="exit", detectors=True, inside=False, in_from=None,
             out_to=None):
    """Radial arm: entry corridor to the give-way line, exit corridor, plus a
    channelised nearside slip.  Also builds the two inward/outward penetration
    corridors to the next ring in when `penetration` data is supplied by the
    caller through from_id/to_id (see ring_penetration)."""
    from sites import term
    pid_root = pid_root or f"AR{arm_index}"
    A = vec(bearing_out)                      # outward along the arm
    edge = radius + ring_lanes * W

    def nrm_left(d):
        return [d[1], -d[0]]

    e_in = (bearing_out + 180.0) % 360.0
    sgn = -1.0 if inside else 1.0
    c_in = add(centre, mul(nrm_left(vec(e_in)),
                           sgn * (median / 2.0 + n_in * W / 2.0)))
    c_out = add(centre, mul(nrm_left(A), sgn * (median / 2.0 + n_out * W / 2.0)))
    # mouth nodes live on the band's nearside lane line, exactly where
    # build_ring puts them (radius + W/2 for both bands: for a circle driven
    # round a central island the nearside line is the *outer* edge of the
    # band, for a ring driven around a plaza it is the plaza-side edge, which
    # is likewise radius + W/2 measured from the carriageway's own centre).
    r_arm = radius + 0.5 * W
    m_in = math.radians(mouth_beta(e_in, delta_in))
    m_out = math.radians(mouth_beta(bearing_out, delta_out))
    q_in = add(centre, [r_arm * math.cos(m_in), r_arm * math.sin(m_in)])
    q_out = add(centre, [r_arm * math.cos(m_out), r_arm * math.sin(m_out)])
    # the arm's innermost inbound lane (highest index, closest to the island)
    # ends exactly on the ring's nearside lane line, so that movement is the
    # direct kink-in at the mouth; kerbside lanes stop staggered outside it.
    # The outbound corridor mirrors this: lane 0 starts at the mouth node.
    nin_u = left_normal(vec(e_in))
    nout_u = left_normal(A)
    in_end = add(q_in, mul(nin_u, sgn * W * (n_in - 1) / 2.0))
    out_start = add(q_out, mul(nout_u, -sgn * W * (n_out - 1) / 2.0))
    in_start = add(in_end, mul(A, arm_len))
    out_end = add(out_start, mul(A, arm_len))
    nd_in = node_for(nodes, "in", arm_index)
    nd_out = node_for(nodes, "out", arm_index)
    res = {"arm": arm_index, "name": name, "bearing": bearing_out,
           "pid_in": f"{pid_root}.in", "pid_out": f"{pid_root}.out",
           "nid": nd_in, "xid": nd_out, "c_in": c_in, "c_out": c_out,
           "edge": edge, "A": A, "n_in": n_in, "n_out": n_out,
           "in_end": in_end, "out_start": out_start,
           "in_end_inner": q_in, "out_start_inner": q_out,
           "q_in": q_in, "q_out": q_out,
           "delta_in": delta_in, "delta_out": delta_out}
    res["beta_in"] = mouth_beta(e_in, delta_in)
    res["beta_out"] = mouth_beta(bearing_out, delta_out)
    ins = corridor(net, pid=res["pid_in"], name=f"{name} entry",
                   path=[line(in_start, in_end)], n_lanes=n_in,
                   frm=in_from or from_id or f"{pid_root}.in.a", to=nd_in,
                   kind=kind_in,
                   carriageway=f"{name} in", v0=v0, limit=limit, mix=mix,
                   approach=f"AP.{name}", heat=heat or name, detectors=detectors)
    res["in"] = ins
    outs = corridor(net, pid=res["pid_out"], name=f"{name} exit",
                    path=[line(out_start, out_end)], n_lanes=n_out,
                    frm=nd_out, to=out_to or to_id or f"{pid_root}.out.a",
                    kind=kind_out,
                    carriageway=f"{name} out", v0=v0, limit=limit, mix=mix,
                    approach=f"AP.{name}", heat=heat or name, detectors=detectors)
    res["out"] = outs
    if open_ends:
        term(net, ins, "start", f"{name} entry")
        term(net, outs, "end", f"{name} exit")
    res["a_in"] = anchors(net, ins, "end")
    res["a_out"] = anchors(net, outs, "start")
    if slip:
        s0 = add(in_end, mul(A, 46.0))
        s1 = add(q_in, mul(nin_u, sgn * W))
        pid = f"{pid_root}.sl"
        lids = corridor(net, pid=pid, name=f"{name} nearside slip",
                        path=[line(s0, s1)], n_lanes=1, frm=f"{pid}.a", to=nd_in,
                        kind="slip", carriageway=f"{name} slip", v0=32, limit=35,
                        mix=mix, approach=f"AP.{name}", heat=f"{name} slip")
        term(net, lids, "start", f"{name} slip")
        res["slip"] = lids[0]
    return res


# ==========================================================================
# wiring
# ==========================================================================
def wire_ring_penetration(net, *, src_node, by_lane_src, tgt_node=None,
                          by_lane_tgt=None, tgt_lids=None, p=0.5, phase=None,
                          limit=32.0, min_r=4.0, max_r=420.0):
    """Outer band -> inner band: connect every circulating lane ending at
    `src_node` to whichever inner-circle lane it can actually reach with a
    solable entry arc, and gate the movement with `phase`.

    This is the plaza penetration.  A driver who has crossed the Outer Circle
    keeps going round it until the inner entry lines up, so the pair is chosen
    by heading compatibility (the arc's own geometry decides feasibility), not
    by arm numbering.  Returns the number of connectors built.
    """
    srcs, src_rank = [], {}
    for gi, ids in enumerate(by_lane_src):
        for l in ends_at(net, src_node, ids):
            srcs.append(l)
            src_rank[l] = gi
    tgts, tgt_rank = [], {}
    if tgt_lids:
        for gi, l in enumerate(tgt_lids):
            tgts.append(l)
            tgt_rank[l] = net.links[l].get("lane_index", gi)
    else:
        for gi, ids in enumerate(by_lane_tgt):
            for l in starts_at(net, tgt_node, ids):
                tgts.append(l)
                tgt_rank[l] = gi
    if not srcs or not tgts:
        return 0
    a_src = anchors(net, srcs, "end")
    a_tgt = anchors(net, tgts, "start")
    ranks_t = sorted(set(tgt_rank.values()))
    built = 0
    for si, src in enumerate(a_src):
        cands = []
        for tgt in a_tgt:
            d = heading_delta(src["dir"], tgt["dir"])
            if abs(d) > 70.0:
                continue
            cands.append((abs(d), dist(src["q"], tgt["q"]), tgt))
        if not cands:
            continue
        # each circulating lane of the far band takes a distinct lane of its
        # own rank, so a 3-lane band diving into a 2-lane one still feeds both
        want = ranks_t[src_rank[src["link"]] % len(ranks_t)]
        cands = [z for z in cands if tgt_rank[z[2]["link"]] == want] + \
                [z for z in cands if tgt_rank[z[2]["link"]] != want]
        tgt, mv, cid = None, None, None
        for _cost, _dd, _t in cands:
            # a plaza penetration is a shallow, strongly skewed cross: try the
            # geometric classes in order of how close the deflection is.
            for _mv in ("through", "right", "left"):
                _cid = connector(net, src, _t, _mv,
                                 node_id=tgt_node or _t["exit_node"] or
                                 net.links[_t["link"]]["from"],
                                 limit=limit, min_r=min_r, max_r=max_r,
                                 kind="connector")
                if _cid:
                    tgt, mv, cid = _t, _mv, _cid
                    break
            if cid:
                break
        if not cid:
            continue
        if phase is not None and cid in net.links:
            net.links[cid]["phases"] = {"through": phase}
        net.turn(src["link"], cid, mv, p)
        net.turn(cid, tgt["link"], "through", 1.0)
        for t in net.turns:
            if t["from"] == src["link"] and t["to"] != cid and \
                    net.links.get(t["to"], {}).get("kind") == "ring":
                t["weight"] = round(max(1.0 - p, 0.02), 5)
        built += 1
    return built


def _tag_turns(net, node_id, src_lids, made, phase):
    """Give the arm/connector links and the turns just made a signal phase."""
    for lid in src_lids:
        net.links[lid]["phases"] = {"through": phase}
    for _lane, cid in made.items():
        if cid in net.links and net.links[cid]["kind"] == "connector":
            net.links[cid]["phases"] = {"through": phase}
        for t in net.turns:
            if t["phase"] is None and (t["from"] in src_lids or (phase is not None and t["to"] in made.values())):
                if t["from"] in src_lids or t["to"] in made.values():
                    t["phase"] = phase


def wire_ring_entry(net, *, node_id, src_lids, by_lane, phase=None,
                    extra_tgt=None, slip=None, yield_conflicts=None,
                    limit=40.0, weights=None, tol=60.0):
    """Arm -> ring mouths.  Every source lane fans to the ring lanes starting
    at the mouth (plus `extra_tgt`, e.g. the plaza chord continuing straight);
    the nearside slip merges past the signal with gap acceptance."""
    from sites import taper_into, set_yield
    starts = []
    for ids in by_lane:
        starts += starts_at(net, node_id, ids)
    tgts = list(starts)
    tgts += list(extra_tgt or [])
    if not tgts or not src_lids:
        return False
    made = taper_into(net, node_id=node_id, src_lids=src_lids, tgt_lids=tgts,
                      weights=weights, limit=limit, all_targets=True,
                      max_lat=W * (len(by_lane) + 6.0), tol=tol)
    if phase is not None:
        _tag_turns(net, node_id, list(src_lids), made, phase)
    m2 = {}
    if slip and starts:
        m2 = taper_into(net, node_id=node_id, src_lids=[slip],
                        tgt_lids=[starts[-1]], limit=limit, all_targets=False)
        if m2 and yield_conflicts:
            set_yield(net, [slip], yield_conflicts, gap_s=1.9, kind="merge",
                      note="nearside slip gives way to the circulating lane")
        if phase is not None:
            _tag_turns(net, node_id, [slip], m2, phase)
    return bool(made)


def wire_ring_exit(net, *, node_id, tgt_lids, by_lane, p, limit=40.0,
                   src_override=None, tol=60.0):
    """Ring -> arm mouths: each circulating lane ending at the mouth may leave.
    The keep-going turn is re-weighted so `p` is the share exiting here
    (constant-hazard discharge around the ring)."""
    from sites import taper_into
    srcs = list(src_override) if src_override is not None else []
    if not srcs:
        for ids in by_lane:
            srcs += ends_at(net, node_id, ids)
    if not srcs or not tgt_lids:
        return False
    made = taper_into(net, node_id=node_id, src_lids=srcs, tgt_lids=tgt_lids,
                      limit=limit, all_targets=True,
                      max_lat=W * (len(by_lane) + 6.0), tol=tol)
    # group connectors by their source link
    by_src = {}
    for cid in made.values():
        by_src.setdefault(net.links[cid]["from"], []).append(cid)
    for src, conns in by_src.items():
        for t in net.turns:
            if t["from"] == src and net.links.get(t["to"], {}).get("kind") == "ring":
                t["weight"] = round(max(1.0 - p, 0.02), 5)
        for c in conns:
            for t in net.turns:
                if t["from"] == src and t["to"] == c:
                    t["weight"] = round(p / len(conns), 5)
    return bool(made)
