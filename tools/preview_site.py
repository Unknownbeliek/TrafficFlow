#!/usr/bin/env python3
"""Draw a site's traced geometry back onto its satellite image.

Used to check the overlay before trusting it: if the coloured lane lines do not
sit on the road in the photo, the calibration or the trace is wrong.

    python3 tools/preview_site.py kalindi_kunj [--out file.png] [--crop x0,y0,x1,y1]
"""
import argparse
import json
import os
import sys

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COLORS = [(0, 255, 180), (255, 90, 90), (120, 180, 255), (255, 210, 80), (200, 130, 255), (90, 255, 120)]

FALLBACK = {
    "kalindi_kunj": "KalindiKunj.png",
    "connaught_place": "CP.png",
    "ito": "ITO.png",
    "gaur_city": "GaurCIty_charmurtiG.png",
    "botanical_okhla": "Botanical_interchange.png",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("site")
    ap.add_argument("--out")
    ap.add_argument("--width", type=int, default=1300)
    ap.add_argument("--crop")
    args = ap.parse_args()

    site_dir = os.path.join(ROOT, "sites", args.site)
    with open(os.path.join(site_dir, "network.json")) as f:
        net = json.load(f)
    img_path = os.path.join(ROOT, net["image"])
    if not os.path.exists(img_path):
        img_path = os.path.join(ROOT, net.get("source_image") or "section_img/KalindiKunj.png")
        print("no base.png yet, previewing on the original screenshot", file=sys.stderr)

    im = Image.open(img_path).convert("RGB")
    if args.crop:
        x0, y0, x1, y1 = [int(v) for v in args.crop.split(",")]
        im = im.crop((x0, y0, x1, y1))
    else:
        x0 = y0 = 0

    scale = args.width / im.width
    im = im.resize((args.width, int(im.height * scale)))
    d = ImageDraw.Draw(im)
    font = ImageFont.load_default(size=15)

    groups = {}
    for i, l in enumerate(net["links"]):
        pts = [((p[0] - x0) * scale, (p[1] - y0) * scale) for p in l["points"]]
        col = COLORS[i % len(COLORS)]
        width = 1 + min(l["lanes"], 4)
        d.line(pts, fill=col, width=width)
        d.ellipse([pts[0][0] - 3, pts[0][1] - 3, pts[0][0] + 3, pts[0][1] + 3], fill=col)
        d.text((pts[0][0] + 5, pts[0][1] - 12), l["id"], fill=col, font=font)
        if l.get("signal_group"):
            x, y = pts[-1]
            d.ellipse([x - 7, y - 7, x + 7, y + 7], outline=(255, 40, 40), width=2)
            groups.setdefault(l["signal_group"], 0)
            groups[l["signal_group"]] += 1

    d.text((8, 8), f"{net['id']}  {len(net['links'])} links  groups={len(groups)}  "
                    f"m/px={net['metres_per_pixel']}", fill=(255, 255, 0), font=font)
    out = args.out or os.path.join(ROOT, ".cache", f"{args.site}_overlay.png")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    im.save(out)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
