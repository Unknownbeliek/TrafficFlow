import json
import math
import numpy as np

def build_osm_network():
    with open('site-data/botanical_okhla/osm_raw.json') as f:
        d = json.load(f)

    nodes = d['nodes']
    ways = d['ways']

    # Focus on the interchange core (within ~500m of interchange center)
    lat_c = 28.556505
    lon_c = 77.325819
    m_lat = 111320.0
    m_lon = 111320.0 * math.cos(math.radians(lat_c))

    def to_m(lat, lon):
        x = (lon - lon_c) * m_lon
        y = -(lat - lat_c) * m_lat
        return round(x, 2), round(y, 2)

    # Filter relevant highway ways:
    # We want motorways, trunks, primaries, and their links (ramps)
    selected_ways = []
    for w in ways:
        hw = w['tags'].get('highway', '')
        if hw in ('motorway', 'trunk', 'primary', 'secondary',
                  'motorway_link', 'trunk_link', 'primary_link', 'secondary_link'):
            pts = [to_m(*nodes[nid]) for nid in w['nodes'] if nid in nodes]
            if len(pts) >= 2:
                # check if at least one point is within 600m
                dists = [math.hypot(p[0], p[1]) for p in pts]
                if min(dists) < 600:
                    selected_ways.append((w, pts))

    print(f"Selected {len(selected_ways)} relevant highway ways in interchange")

    # Build nodes dictionary
    net_nodes = {}
    net_links = []
    
    for idx, (w, pts) in enumerate(selected_ways):
        wid = w['id']
        tags = w['tags']
        name = tags.get('name', f"Road {wid}")
        hw = tags.get('highway', 'primary')
        lanes = int(tags.get('lanes', 1 if 'link' in hw else 2))
        layer = int(tags.get('layer', 1 if tags.get('bridge') == 'yes' else 0))
        is_ramp = 'link' in hw
        speed = 80 if 'motorway' in hw else (50 if is_ramp else 60)
        
        # Build piecewise lines
        prims = []
        total_len = 0.0
        for i in range(len(pts) - 1):
            p1 = pts[i]
            p2 = pts[i+1]
            seg_len = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
            if seg_len > 0.5:
                prims.append({'type': 'line', 'a': p1, 'b': p2})
                total_len += seg_len
        
        if not prims:
            continue
            
        start_nid = f"N_{w['nodes'][0]}"
        end_nid = f"N_{w['nodes'][-1]}"
        net_nodes[start_nid] = {'id': start_nid, 'x': pts[0][0], 'y': pts[0][1], 'type': 'junction'}
        net_nodes[end_nid] = {'id': end_nid, 'x': pts[-1][0], 'y': pts[-1][1], 'type': 'junction'}
        
        link_id = f"osm_{wid}"
        net_links.append({
            'id': link_id,
            'name': f"{name} ({hw})",
            'kind': 'ramp' if is_ramp else ('flyover' if layer > 0 else 'approach'),
            'carriageway': name,
            'from': start_nid,
            'to': end_nid,
            'lanes': lanes,
            'lane_index': 0,
            'length_m': round(total_len, 2),
            'length_surveyed_m': round(total_len * 1.02, 2),
            'geometry': prims,
            'curves': [],
            'v0_kmph': speed,
            'speed_limit_kmph': speed,
            'phases': {},
            'yield': None,
            'approach': f"AP.{name}",
            'heat_group': name,
            'class_mix': {
                'car': 0.50, 'taxi': 0.10, 'two_wheeler': 0.20,
                'auto_rickshaw': 0.10, 'lcv': 0.05, 'truck': 0.03, 'bus': 0.02
            },
            'stop_line_m': round(total_len, 2),
            'capacity_vph': 1800 * lanes,
            'grade': 'flyover' if layer > 0 else ('underpass' if layer < 0 else 'at_grade'),
            'layer': layer,
            'lane_width_m': 3.5,
            'queueable': True,
            'notes': f"Imported from OSM way {wid}",
            'detectors': []
        })

    # Build turns where link end == another link start
    net_turns = []
    incoming_by_node = {}
    outgoing_by_node = {}
    for l in net_links:
        incoming_by_node.setdefault(l['to'], []).append(l['id'])
        outgoing_by_node.setdefault(l['from'], []).append(l['id'])

    for nid in incoming_by_node:
        if nid in outgoing_by_node:
            for from_l in incoming_by_node[nid]:
                for to_l in outgoing_by_node[nid]:
                    if from_l != to_l:
                        net_turns.append({
                            'from': from_l,
                            'to': to_l,
                            'movement': 'through',
                            'weight': round(1.0 / len(outgoing_by_node[nid]), 2)
                        })

    # Find boundary source nodes (links with no incoming)
    all_tos = set(l['to'] for l in net_links)
    all_froms = set(l['from'] for l in net_links)
    sources = [l['id'] for l in net_links if l['from'] not in all_tos]
    
    net_demand = []
    for s in sources:
        net_demand.append({
            'id': f"D_{s}",
            'leg': s,
            'from_link': s,
            'to_link': s, # simple flow
            'flow_vph_peak': 1200,
            'movement': 'through',
            'route': [s]
        })

    print(f"Generated network: {len(net_links)} links, {len(net_nodes)} nodes, {len(net_turns)} turns, {len(net_demand)} demands")

    out_payload = {
        'schema': 'trackflow.v1',
        'site': {
            'id': 'botanical_okhla',
            'name': 'Botanical / Mahamaya Interchange',
            'kind': 'cloverleaf_grade_separated',
            'image': 'section_img/Botanical_interchange.png',
            'summary': 'Real OpenStreetMap road network of the Mahamaya / Botanical interchange.'
        },
        'imagery': {
            'm_per_px': 1.0,
            'origin_px': [960.0, 540.0],
            'rotation_deg': 0.0,
            'scale_bar_m': 50,
            'view': [0, 56, 1920, 1024]
        },
        'display': {
            'px_per_m': 2.0,
            'origin_px': [960, 540],
            'rotation_deg': 0.0
        },
        'lane_width_m': 3.5,
        'vehicle_classes': [
            {'id': 'car', 'name': 'Car', 'length_m': 4.2, 'width_m': 1.8, 'pcu': 1.0, 'v0_kmph': 70, 'color': '#38bdf8'},
            {'id': 'taxi', 'name': 'Taxi', 'length_m': 4.4, 'width_m': 1.8, 'pcu': 1.0, 'v0_kmph': 65, 'color': '#facc15'},
            {'id': 'two_wheeler', 'name': 'Two Wheeler', 'length_m': 1.9, 'width_m': 0.8, 'pcu': 0.5, 'v0_kmph': 60, 'color': '#67e8f9'},
            {'id': 'auto_rickshaw', 'name': 'Auto Rickshaw', 'length_m': 2.6, 'width_m': 1.3, 'pcu': 0.8, 'v0_kmph': 45, 'color': '#34d399'},
            {'id': 'lcv', 'name': 'LCV', 'length_m': 5.5, 'width_m': 2.0, 'pcu': 1.5, 'v0_kmph': 55, 'color': '#c084fc'},
            {'id': 'truck', 'name': 'Truck', 'length_m': 8.5, 'width_m': 2.5, 'pcu': 3.0, 'v0_kmph': 45, 'color': '#f87171'},
            {'id': 'bus', 'name': 'Bus', 'length_m': 10.5, 'width_m': 2.6, 'pcu': 3.0, 'v0_kmph': 45, 'color': '#fb923c'}
        ],
        'hour_factors': [0.2, 0.15, 0.1, 0.1, 0.15, 0.3, 0.6, 0.9, 1.0, 0.95, 0.85, 0.8, 0.8, 0.8, 0.85, 0.9, 0.95, 1.0, 0.95, 0.8, 0.65, 0.5, 0.35, 0.25],
        'signals': [],
        'nodes': list(net_nodes.values()),
        'links': net_links,
        'turns': net_turns,
        'demand': net_demand,
        'approaches': [],
        'heat_groups': [],
        'scenarios': []
    }

    with open('site-data/botanical_okhla/network.json', 'w') as f:
        json.dump(out_payload, f, indent=2)
    print("Successfully wrote site-data/botanical_okhla/network.json from real OSM data!")

if __name__ == '__main__':
    build_osm_network()
