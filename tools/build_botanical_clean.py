import sys; sys.path.insert(0, 'tools')
import math
import sites
from geo import line, arc, bezier, path_length
import network as N

def build_botanical_clean():
    net = N.Net(
        site={"id": "botanical_okhla", "name": "Botanical Okhla Interchange",
              "kind": "cloverleaf_grade_separated", "image": "section_img/Botanical_interchange.png",
              "survey": "DND / Okhla-Circular ramp counts (toll-plaza classified counts reconstruction)",
              "summary": "Full cloverleaf grade-separated interchange."},
        imagery={"m_per_px": 0.8484, "origin_px": [910.0, 522.0], "rotation_deg": -6.0,
                 "scale_bar_m": 50, "view": [0, 56, 1920, 1024],
                 "bearing_note": "local +x follows the DND mainline"},
        display={"px_per_m": 3.0, "origin_px": [960, 540], "rotation_deg": -28.0},
    )

    MAJOR = 620.0
    W = 3.5
    GAP = 2.5 * W
    lane_in = GAP / 2.0 + W / 2.0  # 6.125
    lane_out = GAP / 2.0 + 1.5 * W # 9.625

    net.node("A.core", [0, 0], "junction", name="DND mainline crossing")
    net.node("B.core", [0, 0], "junction", name="Okhla Circular underpass")

    def mainline(pid_root, axis, half, n, v0, mix, heat, name, gap=GAP, grade="at_grade"):
        out = {}
        for d, sgn in (("a", 1), ("b", -1)):
            side = sgn * (gap / 2.0 + n * W / 2.0)
            if axis == "x":
                p_in = [line([-half, side], [0, side])] if sgn > 0 else [line([half, side], [0, side])]
                p_out = [line([0, side], [half, side])] if sgn > 0 else [line([0, side], [-half, side])]
            else:
                p_in = [line([side, -half], [side, 0])] if sgn > 0 else [line([side, half], [side, 0])]
                p_out = [line([side, 0], [side, half])] if sgn > 0 else [line([side, 0], [side, -half])]
            ins = N.corridor(net, pid=f"{pid_root}{d}.in", name=f"{name} in ({d})",
                             path=p_in, n_lanes=n, frm=f"{pid_root}{d}.in.a", to=f"{pid_root}.core",
                             kind="approach", carriageway=f"{name} in {d}", v0=v0, limit=v0,
                             mix=mix, approach=f"AP.{name} {d}", heat=heat, grade=grade)
            outs = N.corridor(net, pid=f"{pid_root}{d}.out", name=f"{name} out ({d})",
                              path=p_out, n_lanes=n, frm=f"{pid_root}.core", to=f"{pid_root}{d}.out.a",
                              kind="exit", carriageway=f"{name} out {d}", v0=v0, limit=v0,
                              mix=mix, approach=f"AP.{name} {d}", heat=heat, grade=grade)
            sites.term(net, ins, "start", f"{name} {d} origin")
            sites.term(net, outs, "end", f"{name} {d} destination")
            out[d] = {"in": ins, "out": outs, "side": side}
        return out

    MA = mainline("A", "x", MAJOR, 2, 80, sites.MIX_ARTERIAL, "DND mainline (SW-NE)", "DND mainline", grade="at_grade")
    MB = mainline("B", "y", MAJOR, 2, 80, sites.MIX_FREIGHT, "Okhla Circular Rd (NW-SE)", "Okhla Circular Rd", grade="underpass")

    N.direct_turns(net, list(zip(MA["a"]["in"], MA["a"]["out"])), weight=0.70)
    N.direct_turns(net, list(zip(MA["b"]["in"], MA["b"]["out"])), weight=0.70)
    N.direct_turns(net, list(zip(MB["a"]["in"], MB["a"]["out"])), weight=0.70)
    N.direct_turns(net, list(zip(MB["b"]["in"], MB["b"]["out"])), weight=0.70)

    # 4 True 270-degree Cloverleaf Loops:
    # Quadrant Centers calibrated to satellite imagery:
    # SW: (-115.0, 90.0), R=44.0m
    # SE: (95.0, 95.0), R=44.0m
    # NE: (120.0, -95.0), R=44.0m
    # NW: (-115.0, -85.0), R=44.0m
    loop_configs = [
        # (id, name, src_link, tgt_link, cx, cy, r, a0, a1, entry_p, merge_p, in_tan, out_tan)
        ("R_SW", "DND East -> Circular North Loop",
         MA["a"]["in"][1], MB["b"]["out"][1],
         -115.0, 90.0, 44.0, 90.0, 360.0,
         [-180.0, lane_out], [-lane_out, -40.0], [1, 0], [0, -1]),
         
        ("R_SE", "Circular South -> DND West Loop",
         MB["a"]["in"][1], MA["b"]["out"][1],
         95.0, 95.0, 44.0, 180.0, 450.0,
         [lane_out, 180.0], [-40.0, -lane_out], [0, 1], [-1, 0]),
         
        ("R_NE", "DND West -> Circular South Loop",
         MA["b"]["in"][1], MB["a"]["out"][1],
         120.0, -95.0, 44.0, 270.0, 540.0,
         [180.0, -lane_out], [lane_out, 40.0], [-1, 0], [0, 1]),
         
        ("R_NW", "Circular North -> DND East Loop",
         MB["b"]["in"][1], MA["a"]["out"][1],
         -115.0, -85.0, 44.0, 0.0, 270.0,
         [-lane_out, -180.0], [40.0, lane_out], [0, -1], [1, 0]),
    ]

    for lid, name, src_l, tgt_l, cx, cy, r, a0, a1, ep, mp, itan, otan in loop_configs:
        ang0 = math.radians(a0)
        p_arc_s = [cx + r * math.cos(ang0), cy + r * math.sin(ang0)]
        t_arc_s = [-math.sin(ang0), math.cos(ang0)]
        
        ang1 = math.radians(a1)
        p_arc_e = [cx + r * math.cos(ang1), cy + r * math.sin(ang1)]
        t_arc_e = [-math.sin(ang1), math.cos(ang1)]
        
        # Entry bezier: from ep to p_arc_s
        d_in = math.hypot(p_arc_s[0] - ep[0], p_arc_s[1] - ep[1]) * 0.45
        p1 = [ep[0] + d_in * itan[0], ep[1] + d_in * itan[1]]
        p2 = [p_arc_s[0] - d_in * t_arc_s[0], p_arc_s[1] - d_in * t_arc_s[1]]
        
        # Exit merge bezier: from p_arc_e to mp
        d_out = math.hypot(mp[0] - p_arc_e[0], mp[1] - p_arc_e[1]) * 0.45
        m1 = [p_arc_e[0] + d_out * t_arc_e[0], p_arc_e[1] + d_out * t_arc_e[1]]
        m2 = [mp[0] - d_out * otan[0], mp[1] - d_out * otan[1]]
        
        prims = [
            bezier(ep, p1, p2, p_arc_s),
            arc([cx, cy], r, a0, a1),
            bezier(p_arc_e, m1, m2, mp),
        ]
        net.node(f"{lid}.n", ep, "junction", name=f"{name} gore")
        net.node(f"{lid}.m", mp, "priority", name=f"{name} merge")
        net.link(f"{lid}.0", name, prims, f"{lid}.n", f"{lid}.m",
                 kind="ramp", carriageway=name, v0=45, limit=35, grade="at_grade")
        net.turn(src_l, f"{lid}.0", movement="left", weight=0.15)
        net.turn(f"{lid}.0", tgt_l, movement="merge", weight=1.0)

    # 4 Direct Right-Turn Slips (gentle 90° curves):
    slip_configs = [
        # Eastbound to Southbound (SE quadrant)
        ("S_SE", "DND East -> Circular South Slip",
         MA["a"]["in"][1], MB["a"]["out"][1],
         [-90.0, lane_out], [lane_out, 90.0], [1, 0], [0, 1]),
        # Southbound to Westbound (SW quadrant)
        ("S_SW", "Circular South -> DND West Slip",
         MB["a"]["in"][1], MA["b"]["out"][1],
         [lane_out, -90.0], [-90.0, -lane_out], [0, 1], [-1, 0]),
        # Westbound to Northbound (NW quadrant)
        ("S_NW", "DND West -> Circular North Slip",
         MA["b"]["in"][1], MB["b"]["out"][1],
         [90.0, -lane_out], [-lane_out, -90.0], [-1, 0], [0, -1]),
        # Northbound to Eastbound (NE quadrant)
        ("S_NE", "Circular North -> DND East Slip",
         MB["b"]["in"][1], MA["a"]["out"][1],
         [-lane_out, 90.0], [90.0, lane_out], [0, -1], [1, 0]),
    ]

    for sid, name, src_l, tgt_l, p0, p3, itan, otan in slip_configs:
        d = math.hypot(p3[0] - p0[0], p3[1] - p0[1]) * 0.45
        p1 = [p0[0] + d * itan[0], p0[1] + d * itan[1]]
        p2 = [p3[0] - d * otan[0], p3[1] - d * otan[1]]
        prims = [bezier(p0, p1, p2, p3)]
        net.node(f"{sid}.n", p0, "junction", name=f"{name} gore")
        net.node(f"{sid}.m", p3, "priority", name=f"{name} merge")
        net.link(f"{sid}.0", name, prims, f"{sid}.n", f"{sid}.m",
                 kind="slip", carriageway=name, v0=55, limit=45, grade="at_grade")
        net.turn(src_l, f"{sid}.0", movement="right", weight=0.15)
        net.turn(f"{sid}.0", tgt_l, movement="merge", weight=1.0)

    sites.heal_lane_gains(net)
    sites.enumerate_demand(net, leg_flows={"Aa.in": 5200, "Ab.in": 4800, "Ba.in": 4300, "Bb.in": 4100})
    return net

net = build_botanical_clean()
print(f"Clean botanical built! Links: {len(net.links)}, Nodes: {len(net.nodes)}, Turns: {len(net.turns)}, Demand: {len(net.demand)}")
checks, problems, tot = net.validate()
print(f"Validation: {len(problems)} problems")
for p in problems:
    print("  Problem:", p)
