"""Accurate builder for Kalindi Kunj Yamuna Bridge with unified 6-lane road.

Key layout:
- Main Yamuna Bridge: A SINGLE unified 6-lane highway corridor (M_DELHI_EB) with 1 continuous safety line and 5 dashed lane dividers.
- Return Yamuna Crossing: 2-lane corridor (M_DELHI_WB) returning to Delhi across the barrage.
- Central Plaza (Chowk): Spacious 42m-radius open asphalt plaza with NO lines inside.
- Botanical Corridor: 2 lanes leaving to Botanical (EB) + 2 lanes returning (WB).
- Faridabad Corridor: 3 lanes leaving to Faridabad (SB) + 3 lanes returning (NB).
"""

import sys
import os
import math
import json

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from geo import (LANE_W_DEFAULT, line, offset, dist, path_length, start_pt, end_pt,
                 start_dir, end_dir, add, sub, mul, unit)
from network import (Net, MIX_ARTERIAL, MIX_HIGH_2W, MIX_COMMERCIAL, MIX_FREIGHT, DEFAULT_MIX)

W = LANE_W_DEFAULT # 3.5m

def build_kalindi():
    imagery = {
        "m_per_px": 0.60,
        "origin_px": [960.0, 496.0],
        "rotation_deg": 0.0,
        "scale_bar_m": 50,
        "view": [0, 0, 1919, 993],
        "bearing_note": "calibrated directly against section_img/KalindiKunj_apple.png",
    }
    display = {
        "px_per_m": 1.667,
        "origin_px": [960, 496],
        "rotation_deg": 0.0,
    }

    net = Net(
        site={
            "id": "kalindi_kunj",
            "name": "Kalindi Kunj Yamuna Bridge",
            "kind": "river_bridge_bottleneck",
            "image": "section_img/KalindiKunj_apple.png",
            "summary": "Unified 6-lane Yamuna crossing bottleneck connecting South Delhi, Noida (Botanical) and Faridabad with open central intersection plaza.",
            "survey": "Delhi-Noida-Faridabad surveyed turning movement counts and OSM directional flow.",
        },
        imagery=imagery,
        display=display,
    )

    # -------------------------------------------------------------------------
    # Signals & Junction Nodes
    # -------------------------------------------------------------------------
    net.signal("S.K_JUNCTION", "Kalindi Kunj Metro Chowk", [
        {"name": "Delhi 6-Lane Mainline Phase (Eastbound)", "green": 38, "amber": 4, "all_red": 2},
        {"name": "Faridabad Corridor Phase (Northbound)", "green": 26, "amber": 4, "all_red": 2},
        {"name": "Botanical Corridor Phase (Westbound)", "green": 20, "amber": 4, "all_red": 2},
    ], offset_s=0.0)

    # Central spacious open asphalt plaza under Kalindi Kunj Metro Station
    net.signal_node("J_MAIN", [93.0, -96.6], "S.K_JUNCTION", name="Kalindi Kunj Central Plaza",
                    radius_m=34.0, is_plaza=True)
    net.node("J_MAIN.out", [93.0, -96.6], "junction", name="Central Plaza Outbound")

    # Boundary Origin/Destination Nodes
    net.node("N_DELHI_EB_SRC", [-576.0, -156.0], "source", name="Delhi Abutment (6-Lane Origin)")
    net.node("N_DELHI_WB_SNK", [-576.0, -62.4], "sink", name="Delhi Return Abutment (WB Destination)")
    net.node("N_BOTANICAL_WB_SRC", [575.4, -88.0], "source", name="Botanical Inflow (WB Origin)")
    net.node("N_BOTANICAL_EB_SNK", [575.4, -70.0], "sink", name="Botanical Outflow (EB Destination)")
    net.node("N_FARIDABAD_NB_SRC", [92.0, 272.4], "source", name="Faridabad Inflow (NB Origin)")
    net.node("N_FARIDABAD_SB_SNK", [108.0, 272.4], "sink", name="Faridabad Outflow (SB Destination)")

    # -------------------------------------------------------------------------
    # Corridors (Unified Links with Exact Lane Counts)
    # -------------------------------------------------------------------------

    # 1. Main Yamuna Bridge: A SINGLE unified 6-lane road with smooth approach curve!
    delhi_eb_geom = [
        line([-576.0, -156.0], [12.0, -156.0]),
        # Smooth Bezier curve around the bend into the metro chowk stop line
        line([12.0, -156.0], [18.9, -155.5]),
        line([18.9, -155.5], [25.6, -154.0]),
        line([25.6, -154.0], [31.9, -151.7]),
        line([31.9, -151.7], [38.0, -148.6]),
        line([38.0, -148.6], [43.7, -144.7]),
        line([43.7, -144.7], [49.2, -140.3]),
        line([49.2, -140.3], [54.4, -135.3]),
        line([54.4, -135.3], [59.2, -129.8]),
        line([59.2, -129.8], [63.8, -124.0]),
        line([63.8, -124.0], [68.0, -117.9]),
        line([68.0, -117.9], [72.0, -111.6]),
    ]
    net.link("M_DELHI_EB", "Main Yamuna Bridge (6-Lane Eastbound)",
             delhi_eb_geom,
             "N_DELHI_EB_SRC", "J_MAIN",
             lanes=6, kind="approach", grade="bridge", v0=70.0, limit=70.0,
             mix=MIX_ARTERIAL, approach="AP.DELHI_EB", heat="Yamuna Bridge (6-Lane EB)",
             phases={"through": 0, "right": 0}, stop_line_m=657.0)

    # 2. Return Yamuna Crossing: 2-lane Westbound road across Okhla Barrage Bridge
    delhi_wb_geom = [
        # Smooth curve from plaza outbound to the lower bridge
        line([72.0, -84.0], [62.7, -82.9]),
        line([62.7, -82.9], [53.6, -80.2]),
        line([53.6, -80.2], [44.7, -76.3]),
        line([44.7, -76.3], [35.9, -72.0]),
        line([35.9, -72.0], [27.2, -67.8]),
        line([27.2, -67.8], [18.6, -64.4]),
        line([18.6, -64.4], [10.0, -62.4]),
        # Straight across lower barrage bridge into Delhi
        line([10.0, -62.4], [-576.0, -62.4]),
    ]
    net.link("M_DELHI_WB", "Return Yamuna Crossing to Delhi (2-Lane WB)",
             delhi_wb_geom,
             "J_MAIN.out", "N_DELHI_WB_SNK",
             lanes=2, kind="exit", grade="bridge", v0=60.0, limit=60.0,
             mix=MIX_ARTERIAL, approach="AP.DELHI_WB", heat="Yamuna Bridge Return (WB)")

    # 3. Botanical Corridor: North bank of Agra Canal (3 Lanes each, separated by median gap)
    bot_eb_geom = [
        line([116.0, -82.0], [174.0, -79.0]),
        line([174.0, -79.0], [575.4, -70.0]),
    ]
    net.link("M_BOTANICAL_EB", "Canal North Road to Botanical (3 Lanes Leaving EB)",
             bot_eb_geom,
             "J_MAIN.out", "N_BOTANICAL_EB_SNK",
             lanes=3, kind="exit", v0=60.0, limit=60.0, mix=MIX_ARTERIAL,
             approach="AP.BOTANICAL_EB", heat="Botanical Corridor (EB)")

    bot_wb_geom = [
        line([575.4, -88.0], [174.0, -97.0]),
        line([174.0, -97.0], [116.0, -100.0]),
    ]
    net.link("M_BOTANICAL_WB", "Canal North Road from Botanical (3 Lanes Entering WB)",
             bot_wb_geom,
             "N_BOTANICAL_WB_SRC", "J_MAIN",
             lanes=3, kind="approach", v0=60.0, limit=60.0, mix=MIX_ARTERIAL,
             approach="AP.BOTANICAL_WB", heat="Botanical Corridor (WB)",
             phases={"through": 2, "left": 2}, stop_line_m=455.0)

    # 4. Faridabad Corridor: South across Canal Bridge
    fbd_sb_geom = [
        line([102.0, -65.0], [102.0, -45.6]),
        line([102.0, -45.6], [104.0, 32.4]),
        line([104.0, 32.4], [106.0, 182.4]),
        line([106.0, 182.4], [108.0, 272.4]),
    ]
    net.link("M_FARIDABAD_SB", "Faridabad Corridor (3 Lanes Leaving SB)",
             fbd_sb_geom,
             "J_MAIN.out", "N_FARIDABAD_SB_SNK",
             lanes=3, kind="exit", v0=60.0, limit=60.0, mix=MIX_FREIGHT,
             approach="AP.FARIDABAD_SB", heat="Faridabad Corridor (SB)")

    fbd_nb_geom = [
        line([88.0, 272.4], [86.0, 182.4]),
        line([86.0, 182.4], [84.0, 32.4]),
        line([84.0, 32.4], [84.0, -45.6]),
        line([84.0, -45.6], [84.0, -65.0]),
    ]
    net.link("M_FARIDABAD_NB", "Faridabad Corridor (3 Lanes Entering NB)",
             fbd_nb_geom,
             "N_FARIDABAD_NB_SRC", "J_MAIN",
             lanes=3, kind="approach", v0=60.0, limit=60.0, mix=MIX_FREIGHT,
             approach="AP.FARIDABAD_NB", heat="Faridabad Corridor (NB)",
             phases={"through": 1, "left": 1, "right": 1}, stop_line_m=335.0)

    # -------------------------------------------------------------------------
    # Turns & Junction Connectors
    # -------------------------------------------------------------------------
    # A. From Delhi 6-Lane Mainline into Botanical & Faridabad
    net.turn("M_DELHI_EB", "M_BOTANICAL_EB", weight=0.55)
    net.turn("M_DELHI_EB", "M_FARIDABAD_SB", weight=0.45)

    # B. From Botanical WB into Delhi Return & Faridabad
    net.turn("M_BOTANICAL_WB", "M_DELHI_WB", weight=0.65)
    net.turn("M_BOTANICAL_WB", "M_FARIDABAD_SB", weight=0.35)

    # C. From Faridabad NB into Delhi Return & Botanical
    net.turn("M_FARIDABAD_NB", "M_DELHI_WB", weight=0.60)
    net.turn("M_FARIDABAD_NB", "M_BOTANICAL_EB", weight=0.40)

    # -------------------------------------------------------------------------
    # Surveyed Demand Movements
    # -------------------------------------------------------------------------
    # 1. Delhi 6-lane -> Botanical
    net.movement(leg="west", mv="through",
                 route=["M_DELHI_EB", "M_BOTANICAL_EB"],
                 flow_vph=4400, approach="AP.DELHI_EB", mix=MIX_ARTERIAL, note="Delhi 6-Lane to Botanical")

    # 2. Delhi 6-lane -> Faridabad
    net.movement(leg="west", mv="right",
                 route=["M_DELHI_EB", "M_FARIDABAD_SB"],
                 flow_vph=3200, approach="AP.DELHI_EB", mix=MIX_FREIGHT, note="Delhi 6-Lane to Faridabad")

    # 3. Botanical -> Delhi Return
    net.movement(leg="east", mv="through",
                 route=["M_BOTANICAL_WB", "M_DELHI_WB"],
                 flow_vph=3800, approach="AP.BOTANICAL_WB", mix=MIX_ARTERIAL, note="Botanical to Delhi Return")

    # 4. Botanical -> Faridabad
    net.movement(leg="east", mv="left",
                 route=["M_BOTANICAL_WB", "M_FARIDABAD_SB"],
                 flow_vph=1200, approach="AP.BOTANICAL_WB", mix=MIX_COMMERCIAL, note="Botanical to Faridabad")

    # 5. Faridabad -> Delhi Return
    net.movement(leg="south", mv="left",
                 route=["M_FARIDABAD_NB", "M_DELHI_WB"],
                 flow_vph=3000, approach="AP.FARIDABAD_NB", mix=MIX_FREIGHT, note="Faridabad to Delhi Return")

    # 6. Faridabad -> Botanical
    net.movement(leg="south", mv="right",
                 route=["M_FARIDABAD_NB", "M_BOTANICAL_EB"],
                 flow_vph=1600, approach="AP.FARIDABAD_NB", mix=MIX_COMMERCIAL, note="Faridabad to Botanical")

    # -------------------------------------------------------------------------
    # Approaches & Scenarios
    # -------------------------------------------------------------------------
    net.approach("AP.DELHI_EB", "Delhi 6-Lane Yamuna Bridge (EB)", leg="west")
    net.approach("AP.DELHI_WB", "Delhi Return Yamuna Crossing (WB)", leg="west")
    net.approach("AP.BOTANICAL_WB", "Botanical Approach (WB)", leg="east")
    net.approach("AP.BOTANICAL_EB", "Botanical Exit (EB)", leg="east")
    net.approach("AP.FARIDABAD_NB", "Faridabad Approach (NB)", leg="south")
    net.approach("AP.FARIDABAD_SB", "Faridabad Exit (SB)", leg="south")

    net.scenarios.extend([
        {
            "id": "morning_peak",
            "name": "Morning Peak (Noida/Faridabad -> Delhi Rush)",
            "hour": 9,
            "multipliers": {"AP.BOTANICAL_WB": 1.25, "AP.FARIDABAD_NB": 1.25, "AP.DELHI_EB": 0.85},
            "note": "Peak commuter traffic returning into South Delhi.",
        },
        {
            "id": "evening_peak",
            "name": "Evening Peak (Delhi -> Noida/Faridabad Rush)",
            "hour": 18,
            "multipliers": {"AP.DELHI_EB": 1.35, "AP.BOTANICAL_WB": 0.75, "AP.FARIDABAD_NB": 0.80},
            "note": "Massive outbound rush over the 6-lane Yamuna Bridge.",
        },
    ])

    return net


if __name__ == "__main__":
    net = build_kalindi()
    checks, problems, tot = net.validate()
    print(f"Validation: {len(problems)} problem(s), total flow {tot:,} vph")
    if problems:
        for p in problems[:10]:
            print("  -", p)
        sys.exit(1)
    
    out_dir = os.path.join(ROOT if 'ROOT' in globals() else os.path.dirname(HERE), "site-data", "kalindi_kunj")
    out_file = os.path.join(out_dir, "network.json")
    with open(out_file, "w") as f:
        json.dump(net.to_json(), f, indent=2)
    print(f"Successfully saved {out_file} ({os.path.getsize(out_file):,} bytes)")
