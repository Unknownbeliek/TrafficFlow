import sys; sys.path.insert(0, 'tools')
import math
import sites
from geo import line, arc, bezier, path_length
import network as N

net = N.Net(
    site={"id": "botanical_okhla", "name": "Botanical Okhla Interchange",
          "kind": "cloverleaf_grade_separated", "image": "section_img/Botanical_interchange.png",
          "summary": "Full cloverleaf grade-separated interchange."},
    imagery={"m_per_px": 0.8484, "origin_px": [910.0, 522.0], "rotation_deg": -6.0,
             "scale_bar_m": 50, "view": [0, 56, 1920, 1024]},
    display={"px_per_m": 3.0, "origin_px": [960, 540], "rotation_deg": -28.0},
)

MAJOR = 620.0
W = 3.5
GAP = 2.5 * W
lane_in = GAP / 2.0 + W / 2.0
lane_out = GAP / 2.0 + 1.5 * W

net.node("A.core", [0, 0], "junction", name="DND mainline crossing")
net.node("B.core", [0, 0], "junction", name="Okhla Circular underpass")

MA = {}
for d, sgn in (("a", 1), ("b", -1)):
    side = sgn * lane_out
    p_in = [line([-MAJOR, side], [0, side])] if sgn > 0 else [line([MAJOR, side], [0, side])]
    p_out = [line([0, side], [MAJOR, side])] if sgn > 0 else [line([0, side], [-MAJOR, side])]
    ins = N.corridor(net, pid=f"Aa.in" if sgn > 0 else "Ab.in", name=f"DND in {d}",
                     path=p_in, n_lanes=2, frm=f"Aa.in.a" if sgn > 0 else "Ab.in.a", to="A.core",
                     kind="approach", carriageway=f"DND in {d}", v0=80, limit=80)
    outs = N.corridor(net, pid=f"Aa.out" if sgn > 0 else "Ab.out", name=f"DND out {d}",
                      path=p_out, n_lanes=2, frm="A.core", to=f"Aa.out.a" if sgn > 0 else "Ab.out.a",
                      kind="exit", carriageway=f"DND out {d}", v0=80, limit=80)
    N.term(net, ins, "start", f"DND {d} origin")
    N.term(net, outs, "end", f"DND {d} dest")
    MA[d] = {"in": ins, "out": outs, "side": side}

MB = {}
for d, sgn in (("a", 1), ("b", -1)):
    side = sgn * lane_out
    p_in = [line([side, -MAJOR], [side, 0])] if sgn > 0 else [line([side, MAJOR], [side, 0])]
    p_out = [line([side, 0], [side, MAJOR])] if sgn > 0 else [line([side, 0], [side, -MAJOR])]
    ins = N.corridor(net, pid=f"Ba.in" if sgn > 0 else "Bb.in", name=f"Circular in {d}",
                     path=p_in, n_lanes=2, frm=f"Ba.in.a" if sgn > 0 else "Bb.in.a", to="B.core",
                     kind="approach", carriageway=f"Circular in {d}", v0=80, limit=80, grade="underpass")
    outs = N.corridor(net, pid=f"Ba.out" if sgn > 0 else "Bb.out", name=f"Circular out {d}",
                      path=p_out, n_lanes=2, frm="B.core", to=f"Ba.out.a" if sgn > 0 else "Bb.out.a",
                      kind="exit", carriageway=f"Circular out {d}", v0=80, limit=80, grade="underpass")
    N.term(net, ins, "start", f"Circular {d} origin")
    N.term(net, outs, "end", f"Circular {d} dest")
    MB[d] = {"in": ins, "out": outs, "side": side}

N.direct_turns(net, list(zip(MA["a"]["in"], MA["a"]["out"])))
N.direct_turns(net, list(zip(MA["b"]["in"], MA["b"]["out"])))
N.direct_turns(net, list(zip(MB["a"]["in"], MB["a"]["out"])))
N.direct_turns(net, list(zip(MB["b"]["in"], MB["b"]["out"])))

# 4 Smooth 270-degree Cloverleaf Loops
def add_loop(lid, name, src_link, tgt_link, cx, cy, r, a0, a1, entry_p, merge_p):
    # entry bezier from entry_p to arc start
    ang0 = math.radians(a0)
    p_arc_start = [cx + r * math.cos(ang0), cy + r * math.sin(ang0)]
    t_arc_start = [-math.sin(ang0), math.cos(ang0)] if a1 > a0 else [math.sin(ang0), -math.cos(ang0)]
    
    ang1 = math.radians(a1)
    p_arc_end = [cx + r * math.cos(ang1), cy + r * math.sin(ang1)]
    t_arc_end = [-math.sin(ang1), math.cos(ang1)] if a1 > a0 else [math.sin(ang1), -math.cos(ang1)]
    
    # Primitives: Entry Bézier + 270° Arc + Exit Merge Bézier
    # Entry control points
    p0 = entry_p
    p3 = p_arc_start
    d_in = math.hypot(p3[0] - p0[0], p3[1] - p0[1]) * 0.4
    # entry heading is along approach
    p1 = [p0[0] + d_in * (1 if abs(p0[1]) > abs(p0[0]) else (1 if p0[0] < 0 else -1)), p0[1]]
    if abs(p0[0]) < 20: # vertical entry
        p1 = [p0[0], p0[1] + d_in * (1 if p0[1] < 0 else -1)]
    p2 = [p3[0] - d_in * t_arc_start[0], p3[1] - d_in * t_arc_start[1]]
    
    # Exit merge control points
    m0 = p_arc_end
    m3 = merge_p
    d_out = math.hypot(m3[0] - m0[0], m3[1] - m0[1]) * 0.4
    m1 = [m0[0] + d_out * t_arc_end[0], m0[1] + d_out * t_arc_end[1]]
    m2 = [m3[0] - d_out * (1 if abs(m3[1]) > abs(m3[0]) else (1 if m3[0] < 0 else -1)), m3[1]]
    if abs(m3[0]) < 20: # vertical merge
        m2 = [m3[0], m3[1] - d_out * (1 if m3[1] < 0 else -1)]
    
    prims = [
        bezier(p0, p1, p2, p3),
        arc([cx, cy], r, a0, a1),
        bezier(m0, m1, m2, m3),
    ]
    net.node(f"{lid}.start", p0, "junction")
    net.node(f"{lid}.end", m3, "junction")
    net.link(f"{lid}.0", name, prims, f"{lid}.start", f"{lid}.end",
             kind="ramp", carriageway=name, v0=40, limit=40, grade="at_grade")
    # turns: from src_link to ramp, and ramp to tgt_link
    net.turn(src_link, f"{lid}.0", movement="left")
    net.turn(f"{lid}.0", tgt_link, movement="merge")

# Add the 4 loops
# 1. SW Loop: Eastbound to Northbound
add_loop("R_SW", "DND East -> Circular North Loop",
         MA["a"]["in"][1], MB["b"]["out"][1],
         -115.0, 90.0, 44.0, 90.0, 360.0,
         [-180.0, lane_out], [-lane_out, 30.0])

# 2. SE Loop: Northbound to Westbound
add_loop("R_SE", "Circular North -> DND West Loop",
         MB["b"]["in"][1], MA["b"]["out"][1],
         95.0, 95.0, 44.0, 180.0, 450.0,
         [-lane_out, 180.0], [30.0, -lane_out])

# 3. NE Loop: Westbound to Southbound
add_loop("R_NE", "DND West -> Circular South Loop",
         MA["b"]["in"][1], MB["a"]["out"][1],
         120.0, -95.0, 44.0, 270.0, 540.0,
         [180.0, -lane_out], [lane_out, -30.0])

# 4. NW Loop: Southbound to Eastbound
add_loop("R_NW", "Circular South -> DND East Loop",
         MB["a"]["in"][1], MA["a"]["out"][1],
         -115.0, -85.0, 44.0, 0.0, 270.0,
         [lane_out, -180.0], [-30.0, lane_out])

print(f"Total links with loops: {len(net.links)}")
checks, problems, tot = net.validate()
print(f"Validation: {len(problems)} problems")
for p in problems:
    print("  Problem:", p)
