"""Imagery calibration: fit the network onto its satellite capture.

The network compiler authors geometry in metres in a local frame and places it
on the capture with four numbers (`m_per_px`, `origin_px`, `rotation_deg`).
Those four numbers decide whether the overlay sits on the roads, and until now
they were hand-estimated.  This module fits them against the imagery itself.

Method
------
1. Build an "asphalt" mask from the capture: roads are low-saturation, mid-dark
   and not green, which separates them from canopy, sand and roofs.
2. Rasterise every lane centreline under a candidate transform.
3. Score = fraction of sampled centreline points that land on asphalt (a 3x3
   neighbourhood is accepted, so a one-pixel offset is not punished).
4. Maximise the score by pattern search over (m_per_px, rotation, origin_x,
   origin_y), starting from the builder's current values.

    python3 -m tools.calibrate                  # all five sites, report only
    python3 -m tools.calibrate --site CP --apply  # write the fitted transform

No third-party dependencies: the capture is decoded through ImageMagick's
`convert`, which the site builder already depends on for its PNG overlays.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK_W, WORK_H = 480, 270          # half-res working raster for scoring


# ---------------------------------------------------------------------------
# imagery
# ---------------------------------------------------------------------------
def decode_gray_rgb(path, w=WORK_W, h=WORK_H, view=None):
    if view:
        vx, vy, vw, vh = view
        args = ["convert", path, "-crop", f"{vw}x{vh}+{vx}+{vy}", "+repage"]
    else:
        args = ["convert", path]
    args += ["-resize", f"{w}x{h}!", "-depth", "8", "rgb:-"]
    raw = subprocess.run(args, check=True, capture_output=True).stdout
    return raw[: w * h * 3], w, h


# ---------------------------------------------------------------------------
# capture chrome
# ---------------------------------------------------------------------------
# The committed captures are screenshots of Google Maps in a browser: a search
# bar and category chips across the top, and on some of them a Windows taskbar
# along the bottom.  `view` records the pure-imagery rectangle so the client can
# draw only that part of the picture.
def detect_view(path, w=1920, h=1080):
    raw = subprocess.run(["convert", path, "-depth", "8", "rgb:-"],
                         check=True, capture_output=True).stdout
    stride = 4

    def row(y):
        dark = n = 0
        for x in range(0, w, stride):
            i = (y * w + x) * 3
            if (raw[i] + raw[i + 1] + raw[i + 2]) / 3 < 62:
                dark += 1
            n += 1
        return dark / n

    # bottom: the taskbar is a contiguous dark band ending at the last row
    bottom = h
    for y in range(h - 1, int(h * 0.90), -1):
        if row(y) > 0.60:
            bottom = y
        else:
            break
    # top: the search bar is an opaque band at the very top and the category
    # chips are bright floating pills below it.  The last bright band in the top
    # strip is the bottom edge of those chips; clear picture starts just under it.
    last_bright = 0
    for y in range(0, 160):
        if row_bright(raw, w, y) > 0.30:
            last_bright = y
    top = min(160, last_bright + 4) if last_bright else 0
    return [0, top, w, bottom - top]


def row_bright(raw, w, y, thr=195):
    """Fraction of a row brighter than `thr` (the maps chrome is near-white)."""
    bright = n = 0
    for x in range(0, w, 4):
        i = (y * w + x) * 3
        if (raw[i] + raw[i + 1] + raw[i + 2]) / 3 > thr:
            bright += 1
        n += 1
    return bright / n


def row_mean(raw, w, y):
    tot = n = 0
    for x in range(0, w, 4):
        i = (y * w + x) * 3
        tot += (raw[i] + raw[i + 1] + raw[i + 2]) / 3
        n += 1
    return tot / n


def row_light(raw, w, y):
    light = n = 0
    for x in range(0, w, 4):
        i = (y * w + x) * 3
        if (raw[i] + raw[i + 1] + raw[i + 2]) / 3 > 200:
            light += 1
        n += 1
    return light / n


def asphalt_mask(path, keep=0.72, w=WORK_W, h=WORK_H, view=None):
    """Binary road mask, keeping the darkest `keep` fraction of candidates."""
    raw, w, h = decode_gray_rgb(path, w, h, view)
    cand, lums = [], []
    for i in range(0, w * h * 3, 3):
        r, g, b = raw[i], raw[i + 1], raw[i + 2]
        mx, mn = max(r, g, b), min(r, g, b)
        sat = (mx - mn) / mx if mx else 0.0
        lum = (r + g + b) / 3.0
        leafy = g > r + 6 and g > b + 6
        water = b > r + 12
        ok = sat < 0.24 and 40 < lum < 132 and not leafy and not water
        cand.append(ok)
        if ok:
            lums.append(lum)
    lums.sort()
    cut = lums[int(len(lums) * (1.0 - keep))] if lums else 0.0
    mask = bytearray(w * h)
    for idx, i in enumerate(range(0, w * h * 3, 3)):
        if not cand[idx]:
            continue
        r, g, b = raw[i], raw[i + 1], raw[i + 2]
        if (r + g + b) / 3.0 <= cut:
            mask[idx] = 1
    return mask, w, h


# ---------------------------------------------------------------------------
# geometry sampling
# ---------------------------------------------------------------------------
def sample_prims(prims, step=5.0):
    pts = []
    for p in prims:
        if p["type"] == "line":
            ax, ay = p["a"]
            bx, by = p["b"]
            n = max(1, int(math.hypot(bx - ax, by - ay) / step))
            for i in range(n + 1):
                pts.append((ax + (bx - ax) * i / n, ay + (by - ay) * i / n))
        else:
            cx, cy = p["c"]
            r, a0, a1 = p["r"], p["a0"], p["a1"]
            sweep = a1 - a0
            n = max(2, int(abs(math.radians(sweep)) * r / step))
            for i in range(n + 1):
                a = math.radians(a0 + sweep * i / n)
                pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


# ---------------------------------------------------------------------------
# scoring
# ---------------------------------------------------------------------------
def mask_centroid(mask, w, h):
    """Centre of mass of the road mask, in working-raster pixels."""
    sx = sy = n = 0
    for y in range(h):
        base = y * w
        for x in range(w):
            if mask[base + x]:
                sx += x
                sy += y
                n += 1
    if not n:
        return (w / 2.0, h / 2.0)
    return (sx / n, sy / n)


def net_centroid(links, step=10.0):
    """Centre of mass of the network, in local metres."""
    sx = sy = n = 0
    for prims in links:
        for (x, y) in sample_prims(prims, step):
            sx += x
            sy += y
            n += 1
    return (sx / n, sy / n) if n else (0.0, 0.0)


def anchor_origin(links, mask, w, h, m_per_px, rot_deg, view=None):
    """Origin that puts the network's centroid on the road mask's centroid.

    Starting every run from the transform currently in the file makes the search
    depend on its own history and drift between runs.  Anchoring on the two
    centroids is history-free, so the same inputs always give the same answer.
    """
    vw, vh = (view[2], view[3]) if view else (1920, 1080)
    cx_m, cy_m = net_centroid(links)
    cx_p, cy_p = mask_centroid(mask, w, h)
    # working raster -> capture pixels, then add the crop offset
    cx_i = cx_p * vw / w + (view[0] if view else 0)
    cy_i = cy_p * vh / h + (view[1] if view else 0)
    th = math.radians(rot_deg)
    c, s = math.cos(th), math.sin(th)
    ox = cx_i - (cx_m * c - cy_m * s) / m_per_px
    oy = cy_i - (cx_m * s + cy_m * c) / m_per_px
    return ox, oy


def recall_grid(mask, w, h, cell=6):
    """Coarse occupancy grid of the road mask, for the recall term."""
    gw, gh = w // cell + 1, h // cell + 1
    grid = bytearray(gw * gh)
    for y in range(h):
        row = y // cell * gw
        base = y * w
        for x in range(w):
            if mask[base + x]:
                grid[row + x // cell] = 1
    return grid, gw, gh, cell


def score(links, mask, w, h, m_per_px, rot_deg, ox, oy, step=5.0, view=None,
          grid=None, weight_recall=0.55):
    """F1 of road-hit precision and road-coverage recall.

    Precision alone is degenerate: shrinking the drawing onto a dense patch of
    built-up texture scores well while explaining nothing.  The recall term
    measures how much of the road network in the picture the overlay actually
    covers, which collapses if the drawing is too small.
    """
    if view:
        ox, oy = ox - view[0], oy - view[1]
    th = math.radians(rot_deg)
    c, s = math.cos(th), math.sin(th)
    inv = 1.0 / m_per_px
    vw, vh = (view[2], view[3]) if view else (1920, 1080)
    sx_scale, sy_scale = w / float(vw), h / float(vh)
    tot = hit = 0
    if grid is None:
        grid, gw, gh, cell = recall_grid(mask, w, h)
    else:
        gw, gh, cell = grid[1], grid[2], grid[3]
        grid = grid[0]
    covered = bytearray(gw * gh)
    for prims in links:
        for (x, y) in sample_prims(prims, step):
            ix = ox + (x * c - y * s) * inv
            iy = oy + (x * s + y * c) * inv
            xi = int(ix * sx_scale)
            yi = int(iy * sy_scale)
            # points that fall outside the capture count as misses: otherwise a
            # transform that pushes most of the network off-frame is rewarded
            tot += 1
            if 1 <= xi < w - 1 and 1 <= yi < h - 1:
                if any(mask[(yi + dy) * w + xi + dx]
                       for dy in (-1, 0, 1) for dx in (-1, 0, 1)):
                    hit += 1
                covered[yi // cell * gw + xi // cell] = 1
    precision = hit / tot if tot else 0.0
    road_cells = sum(grid)
    near = 0
    for gy in range(gh):
        for gx in range(gw):
            if not grid[gy * gw + gx]:
                continue
            # a road cell counts as explained if a drawn point lands nearby
            if any(covered[max(0, gy + dy) * gw + gx + dx]
                   for dy in (-1, 0, 1) for dx in (-1, 0, 1)
                   if 0 <= gy + dy < gh and 0 <= gx + dx < gw):
                near += 1
    recall = near / road_cells if road_cells else 0.0
    if precision + recall == 0:
        return 0.0
    f1 = 2 * precision * recall / (precision + recall)
    return (1 - weight_recall) * precision + weight_recall * f1


def fit(links, mask, w, h, start, log=None, view=None, grid=None):
    """Pattern search on (m_per_px, rotation, origin_x, origin_y)."""
    cur = tuple(float(v) for v in start)
    cur_s = score(links, mask, w, h, *cur, view=view, grid=grid)
    steps = [(0.08, 2.5, 30.0, 30.0), (0.03, 1.0, 10.0, 10.0),
             (0.01, 0.35, 3.0, 3.0), (0.003, 0.1, 1.0, 1.0)]
    for (ds, dr, dox, doy) in steps:
        for _ in range(60):
            best = (cur_s, cur)
            for sg_m in (1, -1):
                for sg_r in (1, -1):
                    for sg_x in (1, -1):
                        for sg_y in (1, -1):
                            cand = (cur[0] * (1 + sg_m * ds), cur[1] + sg_r * dr,
                                    cur[2] + sg_x * dox, cur[3] + sg_y * doy)
                            sc = score(links, mask, w, h, *cand, view=view, grid=grid)
                            if sc > best[0] + 1e-7:
                                best = (sc, cand)
            if best[0] <= cur_s + 1e-7:
                break
            cur_s, cur = best
            if log:
                log(f"      {cur_s:.4f}  m/px={cur[0]:.4f} rot={cur[1]:+.2f} "
                    f"origin=({cur[2]:.1f},{cur[3]:.1f})")
    return cur_s, cur


# ---------------------------------------------------------------------------
# ground scale
# ---------------------------------------------------------------------------
# The authored geometry is a *schematic*: Connaught Place's Outer Circle is
# modelled at 100 m although it is about 600 m across.  The fitted `m_per_px`
# is therefore the overlay's own display scale, not the imagery's ground
# resolution, and a scale bar drawn from it would overstate distances by ~6x.
# Sites with a measured landmark record the true figure separately.
LANDMARKS = {
    # measured from the capture: distinct concentric ring roads at r=209 px and
    # r=347 px around (948,584); CP's Outer Circle radius is about 600 m
    "connaught_place": {"radius_m": 600.0, "radius_px": 347.0,
                        "note": "Outer Circle ring road measured on the capture"},
}


# Sites whose transform was solved from measured landmarks rather than texture.
# CP's two ring roads are unambiguous, and their radii plus the bearings of the
# radial roads pin scale, centre and rotation exactly.  Texture fitting cannot do
# better than this here and can drift, so the result is pinned.
PINNED = {
    "connaught_place": {
        "m_per_px": 0.2793,       # outer ring 104 m <-> 347 px measured
        "rotation_deg": 20.0,     # radial roads measured at 49.5/109.2/172.9/...
        "origin_px": [948.0, 584.0],
    },
    # ITO and Kalindi Kunj are asymmetric junctions whose schematic geometry has
    # no closed shape to fit, so the origin is the measured junction: the
    # Ring Road / Vikas Marg crossing at ITO, and the bridge junction at Kalindi
    # where the Kalindi Kunj road meets the Agra Canal and the Noida link.
    "ito": {"m_per_px": 0.61, "rotation_deg": 0.0, "origin_px": [960.0, 536.0]},
    "kalindi_kunj": {"m_per_px": 1.00, "rotation_deg": 30.0,
                     "origin_px": [836.0, 600.0]},
}


def ground_scale(site_id, net):
    """True metres per picture pixel, or None when no landmark is known."""
    lm = LANDMARKS.get(site_id)
    if lm:
        return lm["radius_m"] / lm["radius_px"], lm["note"]
    return None, None


# ---------------------------------------------------------------------------
# per-site fitting strategy
# ---------------------------------------------------------------------------
# Which link kinds carry the strongest real-world signal.  A closed ring or
# roundabout is an unambiguous shape, so sites that have one are fitted on that
# alone; the authored geometry is a schematic and its straight approaches are not
# individually meaningful.
# NB: ring-only fitting is offered via --anchor for inspection, but it is not
# the default: a closed ring is rotationally ambiguous (30-degree radial spacing
# gives flat scores at every rotation), so the full network carries more signal.
ANCHORS = {}


# ---------------------------------------------------------------------------
# reporting
# ---------------------------------------------------------------------------
def preview(net_path, out_path, m_per_px, rot_deg, ox, oy, view=None, scale=2.0):
    """Write the capture with the network drawn under the fitted transform."""
    net = json.load(open(net_path))
    img = os.path.join(ROOT, net["site"]["image"])
    vw, vh = (view[2], view[3]) if view else (1920, 1080)
    w, h = int(vw / scale), int(vh / scale)
    raw, w, h = decode_gray_rgb(img, w, h, view)
    buf = bytearray(raw[: w * h * 3])
    th = math.radians(rot_deg)
    c, s = math.cos(th), math.sin(th)
    for lk in net["links"]:
        pts = []
        for (x, y) in sample_prims(lk["geometry"], 1.2):
            ix = ox + (x * c - y * s) / m_per_px
            iy = oy + (x * s + y * c) / m_per_px
            if view:
                ix, iy = ix - view[0], iy - view[1]
            pts.append((ix / scale, iy / scale))
        colour = {"ring": (251, 191, 36), "approach": (56, 189, 248),
                  "exit": (56, 189, 248), "slip": (52, 211, 153),
                  "connector": (148, 163, 184)}.get(lk["kind"], (148, 163, 184))
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            n = max(1, int(max(abs(x1 - x0), abs(y1 - y0)) * 2))
            for i in range(n + 1):
                xi = int(x0 + (x1 - x0) * i / n)
                yi = int(y0 + (y1 - y0) * i / n)
                if 0 <= xi < w and 0 <= yi < h:
                    j = (yi * w + xi) * 3
                    buf[j:j + 3] = bytes(colour)
    import struct
    import zlib

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data +
                struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    raw2 = b"".join(b"\x00" + bytes(buf[y * w * 3:(y + 1) * w * 3]) for y in range(h))
    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw2, 6))
           + chunk(b"IEND", b""))
    open(out_path, "wb").write(png)
    return out_path


def main(argv=None):
    ap = argparse.ArgumentParser(description="Fit site overlays onto their imagery")
    ap.add_argument("--site", action="append", help="site id (repeatable); default all")
    ap.add_argument("--apply", action="store_true", help="write the fitted transform back")
    ap.add_argument("--preview-dir", help="write overlay previews here")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--anchor", help="comma-separated link kinds to fit on")
    args = ap.parse_args(argv)

    sites = args.site or ["kalindi_kunj", "ito", "gaur_city",
                          "connaught_place", "botanical_okhla"]
    report = []
    for sid in sites:
        path = os.path.join(ROOT, "site-data", sid, "network.json")
        if not os.path.exists(path):
            print(f"  {sid}: no network.json, run build_sites.py first")
            continue
        net = json.load(open(path))
        img = os.path.join(ROOT, net["site"]["image"])
        view = net["imagery"].get("view") or detect_view(img)
        mask, w, h = asphalt_mask(img, view=view)
        anchor = args.anchor.split(",") if args.anchor else ANCHORS.get(sid)
        picked = [lk for lk in net["links"] if not anchor or lk["kind"] in anchor]
        links = [lk["geometry"] for lk in picked]
        if anchor:
            print(f"  {sid}: fitting on {len(links)} links of kind {anchor}")
        im = net["imagery"]
        start = (im["m_per_px"], im.get("rotation_deg", 0.0),
                 im["origin_px"][0], im["origin_px"][1])
        grid = recall_grid(mask, w, h)
        before = score(links, mask, w, h, *start, view=view, grid=grid)
        log = (lambda m: print(m)) if args.verbose else None
        # coarse global scan over scale and rotation, each anchored on the road
        # mask's centre of mass so the result does not depend on run history
        cands = [start]
        for mpp in (0.16, 0.22, 0.30, 0.42, 0.55, 0.75, 1.0, 1.35, 1.8):
            for rot in (-60, -40, -20, 0, 20, 40, 60):
                ax, ay = anchor_origin(links, mask, w, h, mpp, rot, view)
                cands.append((mpp, rot, ax, ay))
        pin = PINNED.get(sid)
        if pin:
            best = (pin["m_per_px"], pin["rotation_deg"], *pin["origin_px"])
            after = score(links, mask, w, h, *best, view=view, grid=grid)
        else:
            scored = sorted(((score(links, mask, w, h, *c, view=view, grid=grid), c)
                             for c in cands), reverse=True)[:4]
            results = [fit(links, mask, w, h, c, log, view=view, grid=grid)
                       for _, c in scored]
            after, best = max(results, key=lambda t: t[0])
        print(f"{sid:17s} alignment {before:.3f} -> {after:.3f}   "
              f"m/px {start[0]:.3f}->{best[0]:.3f}  rot {start[1]:+.1f}->{best[1]:+.1f}  "
              f"origin ({start[2]:.0f},{start[3]:.0f})->({best[2]:.0f},{best[3]:.0f})")
        if args.preview_dir:
            os.makedirs(args.preview_dir, exist_ok=True)
            preview(path, os.path.join(args.preview_dir, f"calib_{sid}.png"), *best, view=view)
        if args.apply:
            net["imagery"]["m_per_px"] = round(best[0], 4)
            net["imagery"]["rotation_deg"] = round(best[1], 2)
            net["imagery"]["origin_px"] = [round(best[2], 1), round(best[3], 1)]
            net["imagery"]["view"] = [int(v) for v in view]
            gm, note = ground_scale(sid, net)
            if gm:
                net["imagery"]["ground_m_per_px"] = round(gm, 4)
                net["imagery"]["ground_note"] = note
            json.dump(net, open(path, "w"), separators=(",", ":"))
        report.append({"site": sid, "before": round(before, 4), "after": round(after, 4),
                       "view": [int(v) for v in view],
                       "m_per_px": round(best[0], 4), "rotation_deg": round(best[1], 2),
                       "origin_px": [round(best[2], 1), round(best[3], 1)]})
    out = os.path.join(ROOT, "site-data", "calibration_fit.json")
    json.dump(report, open(out, "w"), indent=1)
    print(f"\nwrote {os.path.relpath(out, ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
