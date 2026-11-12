"""Trackflow geometry kit.

Networks are authored in real-world **metres** in a local screen frame
(x -> east/right, y -> south/down, so increasing bearing angle is clockwise on
screen).  Bearings are degrees; 0 = east, 90 = south.

A path is a list of primitives:

    {"type": "line", "a": [x, y], "b": [x, y]}
    {"type": "arc",  "c": [x, y], "r": R, "a0": deg, "a1": deg}

An arc is traversed from `a0` to `a1` (a1 may be smaller than a0, which means
the arc curves the other way).  This makes the representation symmetric and
lets both the C++ engine and the browser renderer sample exactly the same
polyline, so simulated path lengths and drawn path lengths agree by
construction.
"""

from __future__ import annotations

import math

R = 3                   # decimals kept in JSON
LANE_W_DEFAULT = 3.5     # metres per lane
TWO_PI = 2.0 * math.pi


def _p(x, y):
    return [round(float(x), R), round(float(y), R)]


def line(a, b):
    return {"type": "line", "a": _p(*a), "b": _p(*b)}


def arc(c, r, a0, a1):
    return {"type": "arc", "c": _p(*c), "r": round(float(r), R),
            "a0": round(float(a0), R), "a1": round(float(a1), R)}


def vec(bearing_deg):
    a = math.radians(bearing_deg)
    return [math.cos(a), math.sin(a)]


def left_normal(d):
    """Driver's left in a y-down frame."""
    return [d[1], -d[0]]


def right_normal(d):
    return [-d[1], d[0]]


def add(a, b, s=1.0):
    return [a[0] + s * b[0], a[1] + s * b[1]]


def sub(a, b):
    return [a[0] - b[0], a[1] - b[1]]


def mul(a, s):
    return [a[0] * s, a[1] * s]


def unit(a, b=None):
    if b is None:
        n = math.hypot(a[0], a[1])
        return [a[0] / n, a[1] / n] if n > 1e-12 else [1.0, 0.0]
    return unit(sub(b, a))


def dist(a, b):
    return math.hypot(b[0] - a[0], b[1] - a[1])


def ang_of(v):
    return math.degrees(math.atan2(v[1], v[0]))


def bearing(a, b):
    return ang_of(sub(b, a))


# --------------------------------------------------------------------------
# measurement / sampling
# --------------------------------------------------------------------------
def prim_length(p):
    if p["type"] == "arc":
        return p["r"] * abs(math.radians(p["a1"] - p["a0"]))
    return dist(p["a"], p["b"])


def path_length(prims):
    return sum(prim_length(p) for p in prims)


def prim_radius(p):
    """Signed turn: +r for a right-hand (clockwise-on-screen) arc, -r for left."""
    if p["type"] != "arc":
        return None
    d = p["a1"] - p["a0"]
    return p["r"] if d > 0 else -p["r"]


def sample(prims, step=1.0):
    """-> [(x, y, s, signed_R_or_None)] with one sample per `step` metres."""
    pts, acc = [], 0.0
    for p in prims:
        if p["type"] == "arc":
            r, c = p["r"], p["c"]
            a0, a1 = math.radians(p["a0"]), math.radians(p["a1"])
            sweep = a1 - a0
            L = r * abs(sweep)
            n = max(2, int(math.ceil(L / step)))
            for i in range(n + 1):
                t = a0 + sweep * i / n
                pts.append((c[0] + r * math.cos(t), c[1] + r * math.sin(t),
                            acc + L * i / n, r if sweep > 0 else -r))
            acc += L
        else:
            L = dist(p["a"], p["b"])
            n = max(1, int(math.ceil(L / step)))
            for i in range(n + 1):
                t = i / n
                pts.append((p["a"][0] + t * (p["b"][0] - p["a"][0]),
                            p["a"][1] + t * (p["b"][1] - p["a"][1]),
                            acc + L * t, None))
            acc += L
    out = [pts[0]]
    for q in pts[1:]:
        if abs(q[0] - out[-1][0]) > 1e-9 or abs(q[1] - out[-1][1]) > 1e-9:
            out.append(q)
    return out


def start_pt(prims):
    p = prims[0]
    if p["type"] == "arc":
        a = math.radians(p["a0"])
        return [p["c"][0] + p["r"] * math.cos(a), p["c"][1] + p["r"] * math.sin(a)]
    return list(p["a"])


def end_pt(prims):
    p = prims[-1]
    if p["type"] == "arc":
        a = math.radians(p["a1"])
        return [p["c"][0] + p["r"] * math.cos(a), p["c"][1] + p["r"] * math.sin(a)]
    return list(p["b"])


def _tangent(p, at_end):
    """Exact unit tangent of a primitive at its start (at_end=False) or end."""
    if p["type"] == "arc":
        a = p["a1"] if at_end else p["a0"]
        rad = math.radians(a)
        fwd = 1.0 if p["a1"] > p["a0"] else -1.0
        return [-math.sin(rad) * fwd, math.cos(rad) * fwd]
    return unit(p["a"], p["b"])


def start_dir(prims):
    return _tangent(prims[0], False)


def end_dir(prims):
    return _tangent(prims[-1], True)


# --------------------------------------------------------------------------
# pen-style builder
# --------------------------------------------------------------------------


def _norm_sweep(d, want_sign):
    """Normalise a signed angle change so its sign matches want_sign (+1 = cw on
    screen).  Returns None if no representation within +-180 deg has that sign."""
    x = (d + 180.0) % 360.0 - 180.0
    if want_sign > 0:
        return x if x > 1e-9 else None
    return x if x < -1e-9 else None


class Pen:
    """Trace a path: forward(), turn(), arc(), line_to() with tangent continuity."""

    def __init__(self, start, bearing_deg):
        self.prims = []
        self.pos = list(start)
        self.dir = vec(bearing_deg)

    @property
    def bearing(self):
        return ang_of(self.dir)

    def line_to(self, xy):
        if dist(self.pos, xy) > 1e-6:
            self.prims.append(line(self.pos, xy))
            self.pos = list(xy)
            self.dir = unit(self.pos, add(self.pos, self.dir))
        return self

    def forward(self, length):
        return self.line_to(add(self.pos, mul(self.dir, length)))

    def turn(self, delta_deg, radius):
        """Sweep `delta_deg` (+ = right/clockwise) on a circular arc of `radius`."""
        if abs(delta_deg) < 1e-6:
            return self
        d = self.dir
        n = right_normal(d) if delta_deg > 0 else left_normal(d)
        sgn = 1.0 if delta_deg > 0 else -1.0
        c = add(self.pos, mul(n, radius))
        a0 = ang_of(sub(self.pos, c))
        a1 = a0 + sgn * abs(delta_deg)
        self.prims.append(arc(c, radius, a0, a1))
        a1r = math.radians(a1)
        self.pos = [c[0] + radius * math.cos(a1r), c[1] + radius * math.sin(a1r)]
        self.dir = vec(self.bearing + delta_deg)
        return self

    def tangent_arc(self, q2, u2, side, min_r=5.0, max_r=400.0):
        """Single arc tangent to the current heading that lands on the line
        (q2, u2).  side=+1 right turn, -1 left turn.  Returns True on success."""
        u1 = self.dir
        n1 = right_normal(u1) if side > 0 else left_normal(u1)
        n2 = right_normal(u2) if side > 0 else left_normal(u2)
        denom = n1[0] * n2[0] + n1[1] * n2[1] - 1.0
        if abs(denom) < 1e-9:
            return False
        rhs = (q2[0] - self.pos[0]) * n2[0] + (q2[1] - self.pos[1]) * n2[1]
        r = rhs / denom
        if not (min_r <= r <= max_r):
            return False
        c = add(self.pos, mul(n1, r))
        t2 = (c[0] - q2[0]) * u2[0] + (c[1] - q2[1]) * u2[1]
        b = add(q2, mul(u2, t2))
        a0 = ang_of(sub(self.pos, c))
        a1 = ang_of(sub(b, c))
        if side > 0:
            while a1 <= a0:
                a1 += 360.0
        else:
            while a1 >= a0:
                a1 -= 360.0
        if a1 - a0 > 270.0:
            return False
        self.prims.append(arc(c, r, a0, a1))
        self.pos = b
        self.dir = list(u2)
        return True

    def loop_arc(self, q2, u2, side, radius):
        """Arc of a *fixed* radius, tangent to the current heading, that leaves the
        traveller aligned with u2.  Used for 270-degree cloverleaf loops, where the
        centre is on the right of entry but on the left of exit.

        side = +1 curves right (clockwise on screen), -1 curves left.
        """
        u1 = unit(self.dir)
        u2 = unit(u2)
        n1 = right_normal(u1) if side > 0 else left_normal(u1)
        c = add(self.pos, mul(n1, radius))
        a_start = ang_of(sub(self.pos, c))          # radius angle, not heading
        h_in, h_out = ang_of(u1), ang_of(u2)
        if side > 0:
            sweep = (h_out - h_in) % 360.0
        else:
            sweep = -((h_in - h_out) % 360.0)
        if abs(sweep) < 1e-9:
            sweep = 360.0 if side > 0 else -360.0
        th = math.radians(a_start + sweep)
        b = [c[0] + radius * math.cos(th), c[1] + radius * math.sin(th)]
        self.prims.append(arc(c, radius, a_start, a_start + sweep))
        self.pos = b
        self.dir = vec(h_out)
        self.sweep = sweep
        return True

    def biarc(self, q2, u2, radius=None, min_r=3.0, max_r=400.0):
        """S-shaped curve: two arcs of equal radius turning in opposite directions,
        starting at the pen point/heading and ending at (q2, u2).

        Used where a single tangent arc cannot join two lane lines (the flared
        mouth of a roundabout, ramp terminals).  With centres c0, c1 the two arcs
        touch externally when |c1 - c0| = 2r, which is quadratic in r:
            r^2 (|w|^2 - 4) - 2 r (dp . w) + |dp|^2 = 0,  w = sigma (n0 + n1)
        Each arc's traversal direction is chosen so its own start tangent agrees
        with the travel direction, so the joins are tangent by construction.
        Returns True on success.
        """
        p0 = self.pos
        u0 = unit(self.dir)
        u2 = unit(u2)
        dp = [q2[0] - p0[0], q2[1] - p0[1]]
        best = None
        for sigma in (1.0, -1.0):
            n0 = left_normal(u0)
            n1 = left_normal(u2)
            w = [sigma * (n0[0] + n1[0]), sigma * (n0[1] + n1[1])]
            a = w[0] * w[0] + w[1] * w[1] - 4.0
            b = -2.0 * (dp[0] * w[0] + dp[1] * w[1])
            c = dp[0] * dp[0] + dp[1] * dp[1]
            roots = []
            if abs(a) < 1e-9:
                if abs(b) > 1e-9:
                    roots.append(-c / b)
            else:
                disc = b * b - 4.0 * a * c
                if disc < 0:
                    continue
                sq = math.sqrt(disc)
                roots += [(-b + sq) / (2.0 * a), (-b - sq) / (2.0 * a)]
            for r in [abs(x) for x in roots if x != 0.0]:
                if radius is not None and abs(r - radius) > 1e-6:
                    continue
                if not (min_r <= r <= max_r):
                    continue
                c0 = [p0[0] + sigma * r * n0[0], p0[1] + sigma * r * n0[1]]
                c1 = [q2[0] - sigma * r * n1[0], q2[1] - sigma * r * n1[1]]
                if math.hypot(c1[0] - c0[0], c1[1] - c0[1]) <= 1e-6:
                    continue
                jx, jy = (c0[0] + c1[0]) / 2.0, (c0[1] + c1[1]) / 2.0
                a0 = math.degrees(math.atan2(p0[1] - c0[1], p0[0] - c0[0]))
                aj = math.degrees(math.atan2(jy - c0[1], jx - c0[0]))
                bj = math.degrees(math.atan2(jy - c1[1], jx - c1[0]))
                a2 = math.degrees(math.atan2(q2[1] - c1[1], q2[0] - c1[0]))
                # arc 0 starts at a0 travelling in the direction whose tangent is u0
                tinc = [-math.sin(math.radians(a0)), math.cos(math.radians(a0))]
                d0 = 1 if (u0[0] * tinc[0] + u0[1] * tinc[1]) > 0 else -1
                if d0 > 0:
                    s0 = (aj - a0) % 360.0
                else:
                    s0 = -((a0 - aj) % 360.0)
                d1 = -d0
                if d1 > 0:
                    s1 = (a2 - bj) % 360.0
                else:
                    s1 = -((bj - a2) % 360.0)
                if abs(s0) > 179.5 or abs(s1) > 179.5:
                    continue
                # tangents at the joint must agree, end tangent must match u2
                t0e = [d0 * -math.sin(math.radians(aj)), d0 * math.cos(math.radians(aj))]
                t1s = [d1 * -math.sin(math.radians(bj)), d1 * math.cos(math.radians(bj))]
                if t0e[0] * t1s[0] + t0e[1] * t1s[1] < 0.999:
                    continue
                t1e = [d1 * -math.sin(math.radians(a2)), d1 * math.cos(math.radians(a2))]
                if t1e[0] * u2[0] + t1e[1] * u2[1] < 0.999:
                    continue
                if best is None or r < best[0]:
                    best = (r, c0, c1, a0, s0, bj, s1)
        if best is None:
            return False
        r, c0, c1, a0, s0, bj, s1 = best
        self.prims.append(arc(c0, r, a0, a0 + s0))
        self.prims.append(arc(c1, r, bj, bj + s1))
        self.pos = [q2[0], q2[1]]
        self.dir = list(u2)
        return True

    def tangent_arc_to_line(self, q2, u2, side, min_r=5.0, max_r=400.0,
                            tol=0.06, min_run=0.0):
        """Single circular arc, tangent to the current heading, that meets the
        *infinite line* through (q2, u2) tangentially, touching at or past q2.

        This is how a flared roundabout mouth really works: the deflected path
        joins the circulating lane line, not the node marker on it, so q2 itself
        may be upstream of the tangency point.  Returns True on success.
        """
        u1 = unit(self.dir)
        u2 = unit(u2)
        n1 = right_normal(u1) if side > 0 else left_normal(u1)
        n2 = right_normal(u2) if side > 0 else left_normal(u2)
        denom = n1[0] * n2[0] + n1[1] * n2[1] - 1.0
        if abs(denom) < 1e-9:
            return False
        rhs = (q2[0] - self.pos[0]) * n2[0] + (q2[1] - self.pos[1]) * n2[1]
        r = rhs / denom
        if not (min_r <= abs(r) <= max_r):
            return False
        r = abs(r)
        c = add(self.pos, mul(n1, r if rhs / denom > 0 else -r))
        # recompute with the sign-consistent radius
        c = add(self.pos, mul(n1, rhs / denom))
        t2 = (c[0] - q2[0]) * u2[0] + (c[1] - q2[1]) * u2[1]
        b = add(q2, mul(u2, t2))
        run = t2
        if run < min_run - 1e-9:
            return False
        a0 = ang_of(sub(self.pos, c))
        a1 = ang_of(sub(b, c))
        if side > 0:
            while a1 <= a0:
                a1 += 360.0
        else:
            while a1 >= a0:
                a1 -= 360.0
        if abs(a1 - a0) > 179.9:
            return False
        self.prims.append(arc(c, r, a0, a1))
        self.pos = b
        self.dir = list(u2)
        return True

    def path(self):
        return self.prims


def offset(prims, d):
    """Offset a whole path d metres to the left of travel (negative = right).
    Lines shift; arcs change radius about the same centre."""
    out = []
    for p in prims:
        if p["type"] == "arc":
            sgn = 1.0 if p["a1"] > p["a0"] else -1.0
            r2 = p["r"] - sgn * d
            if r2 <= 0.2:
                r2 = 0.2
            out.append(arc(p["c"], r2, p["a0"], p["a1"]))
        else:
            n = left_normal(unit(p["a"], p["b"]))
            out.append(line(add(p["a"], n, d), add(p["b"], n, d)))
    return out


def reverse_path(prims):
    """Traverse the same shape in the opposite direction."""
    out = []
    for p in reversed(prims):
        if p["type"] == "arc":
            out.append(arc(p["c"], p["r"], p["a1"], p["a0"]))
        else:
            out.append(line(p["b"], p["a"]))
    return out


def lane_index_offset(i, n, width=3.5):
    """Lateral offset (metres, left of the carriageway centreline) of lane i."""
    return width * ((n - 1) / 2.0 - i)
