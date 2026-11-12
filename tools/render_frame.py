#!/usr/bin/env python3
"""Render one simulated frame to PNG without a browser.

Uses the same 1-D -> 2-D mapping as web/src/lib/geometry.js (arc-length lookup,
lane offset along the normal), so it is both a geometry check and a way to make
figures for the report on a machine with no headless browser.

    python3 tools/render_frame.py connaught_place --seconds 90 --out frame.png
"""
import argparse
import json
import math
import os
import subprocess

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLASS_COLORS = ["#7dd3fc", "#fbbf24", "#34d399", "#a78bfa", "#f472b6", "#fb923c", "#ef4444"]
CLASS_LEN = [4.3, 4.4, 1.9, 2.6, 5.5, 9.0, 12.0]
CLASS_W = [1.8, 1.8, 0.7, 1.4, 2.1, 2.5, 2.5]

# used until the clean crops replace the full-desktop screenshots
FALLBACK = {
    "kalindi_kunj": "KalindiKunj.png",
    "connaught_place": "CP.png",
    "ito": "ITO.png",
    "gaur_city": "GaurCIty_charmurtiG.png",
    "botanical_okhla": "Botanical_interchange.png",
}


def snapshot(site_id, seconds):
    net_path = os.path.join(ROOT, "sites", site_id, "network.json")
    engine = os.path.join(ROOT, "engine", "trackflow")
    cmds = json.dumps({"cmd": "advance", "dt": seconds}) + "\n" + json.dumps({"cmd": "quit"}) + "\n"
    out = subprocess.run([engine, "serve", net_path], input=cmds, capture_output=True, text=True, timeout=120)
    lines = [l for l in out.stdout.splitlines() if l.startswith('{"t"')]
    return json.loads(lines[-1])


def geom(link, mpp):
    pts = link["points"]
    cum = [0.0]
    for i in range(1, len(pts)):
        cum.append(cum[-1] + math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]))
    return pts, cum, cum[-1] * mpp


def point_at(pts, cum, total_px, length_m, s, lane, lanes, lane_px):
    t = max(0.0, min(1.0, s / length_m))
    target = t * total_px
    i = 1
    while i < len(cum) - 1 and cum[i] < target:
        i += 1
    a, b = pts[i - 1], pts[i]
    seg = max(1e-6, cum[i] - cum[i - 1])
    f = (target - cum[i - 1]) / seg
    x = a[0] + (b[0] - a[0]) * f
    y = a[1] + (b[1] - a[1]) * f
    ang = math.atan2(b[1] - a[1], b[0] - a[0])
    off = (lane - (lanes - 1) / 2) * lane_px
    return x + math.cos(ang + math.pi / 2) * off, y + math.sin(ang + math.pi / 2) * off, ang


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("site")
    ap.add_argument("--seconds", type=float, default=90)
    ap.add_argument("--out")
    ap.add_argument("--width", type=int, default=1300)
    args = ap.parse_args()

    site_dir = os.path.join(ROOT, "sites", args.site)
    net = json.load(open(os.path.join(site_dir, "network.json")))
    snap = snapshot(args.site, args.seconds)
    mpp = net["metres_per_pixel"]

    img_path = os.path.join(ROOT, net["image"])
    if not os.path.exists(img_path):
        img_path = os.path.join(ROOT, net.get("source_image") or "section_img/KalindiKunj.png")
    im = Image.open(img_path).convert("RGB")
    scale = args.width / im.width
    im = im.resize((args.width, int(im.height * scale)))
    d = ImageDraw.Draw(im, "RGBA")
    font = ImageFont.load_default(size=13)

    geo = []
    for link in net["links"]:
        pts, cum, tot = geom(link, mpp)
        geo.append((pts, cum, tot, tot * mpp, link))

    # lane centrelines
    for pts, cum, tot, lm, link in geo:
        lanes = link["lanes"]
        lane_px = link["lane_width_m"] / mpp
        for lane in range(lanes):
            poly = []
            for i in range(len(pts) * 3):
                s = lm * i / (len(pts) * 3 - 1)
                x, y, _ = point_at(pts, cum, tot, lm, s, lane, lanes, lane_px)
                poly.append((x * scale, y * scale))
            d.line(poly, fill=(200, 220, 240, 90), width=1)

    # vehicles
    for vid, cls, li, lane, s, v, a in snap["vehicles"]:
        pts, cum, tot, lm, link = geo[li]
        lanes = link["lanes"]
        lane_px = link["lane_width_m"] / mpp
        x, y, ang = point_at(pts, cum, tot, lm, s, lane, lanes, lane_px)
        L = max(4, (CLASS_LEN[cls] / mpp) * scale)
        W = max(3, (CLASS_W[cls] / mpp) * scale)
        ca, sa = math.cos(ang), math.sin(ang)
        cx, cy = x * scale, y * scale
        corners = [(-L / 2, -W / 2), (L / 2, -W / 2), (L / 2, W / 2), (-L / 2, W / 2)]
        poly = [(cx + px * ca - py * sa, cy + px * sa + py * ca) for px, py in corners]
        d.polygon(poly, fill=CLASS_COLORS[cls], outline=(10, 16, 26))

    # signals
    sg = {g: (st, rem) for g, st, rem in snap["signals"]}
    for pts, cum, tot, lm, link in geo:
        g = link.get("signal_group")
        if not g:
            continue
        x, y = pts[-1]
        col = {"G": (34, 197, 94), "A": (245, 158, 11), "R": (239, 68, 68)}[sg.get(g, ("G", 0))[0]]
        d.ellipse([x * scale - 9, y * scale - 9, x * scale + 9, y * scale + 9], fill=col, outline=(255, 255, 255))

    d.rectangle([0, 0, im.width, 26], fill=(15, 23, 42, 230))
    d.text((8, 6), f"{net['name']}   t={snap['t']:.1f}s   vehicles={snap['totals']['active']}   "
                   f"meanV={snap['totals']['meanV']} km/h   mode={snap['mode']}",
           fill=(229, 237, 247), font=font)

    out = args.out or os.path.join(ROOT, ".cache", f"frame_{args.site}.png")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    im.save(out)
    print(f"wrote {out}  ({snap['totals']['active']} vehicles)")


if __name__ == "__main__":
    main()
