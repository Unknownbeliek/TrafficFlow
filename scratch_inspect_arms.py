import json
import math

d = json.load(open('TrafficFlow/site-data/kalindi_kunj/network.json'))
for l in d['links']:
    if l.get('kind') in ['approach', 'exit']:
        g = l['geometry']
        p_start = g[0]['a']
        p_end = g[-1]['b']
        d_start = [g[0]['b'][0] - g[0]['a'][0], g[0]['b'][1] - g[0]['a'][1]]
        d_end = [g[-1]['b'][0] - g[-1]['a'][0], g[-1]['b'][1] - g[-1]['a'][1]]
        l_start = math.hypot(d_start[0], d_start[1])
        l_end = math.hypot(d_end[0], d_end[1])
        d_start = [round(d_start[0]/l_start, 3), round(d_start[1]/l_start, 3)]
        d_end = [round(d_end[0]/l_end, 3), round(d_end[1]/l_end, 3)]
        print(f"{l['id']:16s} kind={l['kind']:8s} lanes={l['lanes']} start={p_start} dir_s={d_start} end={p_end} dir_e={d_end}")
