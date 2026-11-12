# Trackflow network compiler

Builds the five Delhi-NCR microscopic networks from the committed
`section_img/` satellite captures.

```bash
python3 tools/build_sites.py                       # all five sites
python3 tools/build_sites.py --site connaught_place
python3 tools/build_sites.py --preview-dir /tmp/prev   # + overlay PNGs
```

Output lands in `site-data/<site_id>/`:

| file | contents |
| --- | --- |
| `network.json` | nodes, lane-level links, turns, signals, surveyed demand (schema 4) |
| `survey.csv` | turning-movement counts by hour and vehicle class |
| `calibration.json` | measured vs modelled values for the verification panel |
| `notes.md` | site notes, geometry provenance, demand reconciliation |

| module | role |
| --- | --- |
| `geo.py` | metre-space geometry (x east, y south; bearings clockwise from east) |
| `network.py` | schema, vehicle classes, `Net`, junction wiring, demand enumeration |
| `rings.py` | roundabout / circle construction and ring-entry, ring-exit and ring-penetration wiring |
| `sites.py` | the five site builders |
| `pngout.py` | self-contained PNG rasteriser for the overlays (no PIL) |
| `build_sites.py` | CLI, calibration and notes |

Every build ends with `Net.validate()`; the build fails unless all sites report
zero topology problems (unreachable links, links that cannot drain to a sink,
non-positive movement flow).

India is left-hand traffic: `TRAFFIC_SIDE = -1`, the Outer Circle circulates
clockwise and the Inner Circle counter-clockwise about the island.
