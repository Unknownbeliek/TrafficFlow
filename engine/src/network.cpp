#include "network.h"

#include <fstream>
#include <sstream>

namespace tj {

namespace {

Prim read_prim(const Value &v) {
    Prim p;
    if (v.str("type") == "arc") {
        p.kind = Prim::ARC;
        p.c = Vec2(v.num("c", 0.0), 0.0);
        const Value &c = v["c"];
        p.c = Vec2(c[0].n, c[1].n);
        p.r = v.num("r", 1.0);
        p.a0 = v.num("a0", 0.0);
        p.a1 = v.num("a1", 0.0);
    } else {
        p.kind = Prim::LINE;
        const Value &a = v["a"], &b = v["b"];
        p.a = Vec2(a[0].n, a[1].n);
        p.b = Vec2(b[0].n, b[1].n);
    }
    return p;
}

}  // namespace

bool Network::load(const Value &root) {
    const Value &site = root["site"];
    site_id = site.str("id");
    site_name = site.str("name");
    site_kind = site.str("kind");
    summary = site.str("summary");
    survey = site.str("survey");

    const Value &im = root["imagery"];
    m_per_px = im.num("m_per_px", 0.55);
    const Value &o = im["origin_px"];
    if (o.is_arr() && o.size() >= 2) origin_px = {o[0].n, o[1].n};
    rotation_deg = im.num("rotation_deg", 0.0);
    scale_bar_m = im.num("scale_bar_m", 50.0);

    const Value &dp = root["display"];
    display_px_per_m = dp.num("px_per_m", 3.0);
    const Value &do_ = dp["origin_px"];
    if (do_.is_arr() && do_.size() >= 2) display_origin_px = {do_[0].n, do_[1].n};
    lane_width_m = root.num("lane_width_m", 3.5);

    const Value &vc = root["vehicle_classes"];
    for (auto it = vc.o.begin(); it != vc.o.end(); ++it) {
        VehicleClass c;
        c.id = it->first;
        c.name = it->second.str("name", it->first);
        c.length = it->second.num("length", 4.3);
        c.width = it->second.num("width", 1.8);
        c.v0_kmph = it->second.num("v0_kmph", 80.0);
        c.pcu = it->second.num("pcu", 1.0);
        c.color = it->second.str("color", "#cbd5e1");
        c.v0_mps = c.v0_kmph / 3.6;
        vehicle_classes[c.id] = c;
        class_order.push_back(c.id);
    }
    for (const Value &h : root.arr("hour_factors")) hour_factors.push_back(h.n);

    for (const Value &n : root.arr("nodes")) {
        Node nd;
        nd.id = n.str("id");
        nd.x = n.num("x");
        nd.y = n.num("y");
        nd.type = n.str("type", "junction");
        nd.signal = n.str("signal");
        nd.name = n.str("name", nd.id);
        nodes[nd.id] = nd;
    }

    for (const Value &s : root.arr("signals")) {
        Signal sig;
        sig.id = s.str("id");
        sig.name = s.str("name");
        sig.strategy = s.str("strategy", "fixed_time");
        sig.coordinator = s.str("coordinator");
        sig.offset_s = s.num("offset_s", 0.0);
        for (const Value &p : s.arr("phases")) {
            Phase ph;
            ph.index = int(p.num("index", sig.phases.size()));
            ph.name = p.str("name");
            ph.green = p.num("green", 30.0);
            ph.amber = p.num("amber", 4.0);
            ph.all_red = p.num("all_red", 3.0);
            ph.min_green = p.num("min_green", 5.0);
            ph.max_green = p.num("max_green", ph.green);
            sig.phases.push_back(ph);
        }
        sig.finalise();
        signals[sig.id] = sig;
    }

    for (const Value &l : root.arr("links")) {
        Link lk;
        lk.id = l.str("id");
        lk.name = l.str("name");
        lk.kind = l.str("kind", "approach");
        lk.carriageway = l.str("carriageway");
        lk.from = l.str("from");
        lk.to = l.str("to");
        lk.approach = l.str("approach");
        lk.heat_group = l.str("heat_group");
        lk.notes = l.str("notes");
        lk.lanes = int(l.num("lanes", 1));
        lk.lane_index = int(l.num("lane_index", 0));
        lk.length_m = l.num("length_m");
        lk.length_surveyed_m = l.num("length_surveyed_m", lk.length_m);
        lk.v0_kmph = l.num("v0_kmph", 60.0);
        lk.speed_limit_kmph = l.num("speed_limit_kmph", lk.v0_kmph);
        lk.stop_line_m = l.num("stop_line_m", lk.length_m);
        lk.capacity_vph = l.num("capacity_vph", 1800.0);
        lk.queueable = l.boolean("queueable", true);
        for (const Value &p : l.arr("geometry")) lk.geom.add(read_prim(p));
        if (lk.length_m <= 0.0) lk.length_m = lk.geom.length();
        for (const Value &c : l.arr("curves")) {
            Curve cv;
            cv.s0 = c.num("s0");
            cv.s1 = c.num("s1");
            cv.R_m = c.num("R_m", 0.0);
            lk.curves.push_back(cv);
        }
        for (const Value &d : l.arr("detectors")) {
            Detector dd;
            dd.id = d.str("id");
            dd.s_m = d.num("s_m");
            dd.kind = d.str("kind", "loop");
            lk.detectors.push_back(dd);
        }
        const Value &ph = l["phases"];
        for (auto it = ph.o.begin(); it != ph.o.end(); ++it)
            lk.phases[it->first] = int(it->second.n);
        const Value &mx = l["class_mix"];
        for (auto it = mx.o.begin(); it != mx.o.end(); ++it)
            lk.class_mix[it->first] = it->second.n;
        link_index[lk.id] = links.size();
        links.push_back(std::move(lk));
    }

    for (const Value &t : root.arr("turns")) {
        Turn tn;
        tn.from = t.str("from");
        tn.to = t.str("to");
        tn.movement = t.str("movement", "through");
        tn.weight = t.num("weight", 1.0);
        tn.phase = int(t.num("phase", -1.0));
        turns.push_back(tn);
    }

    for (const Value &d : root.arr("demand")) {
        DemandRow r;
        r.id = d.str("id");
        r.leg = d.str("leg");
        r.movement = d.str("movement");
        r.approach = d.str("approach");
        r.note = d.str("note");
        r.connector = d.str("connector");
        r.flow_vph_peak = d.num("flow_vph_peak");
        for (const Value &a : d.arr("route")) r.route.push_back(a.s);
        const Value &mx = d["class_mix"];
        for (auto it = mx.o.begin(); it != mx.o.end(); ++it)
            r.class_mix[it->first] = it->second.n;
        demand.push_back(std::move(r));
    }

    for (const Value &a : root.arr("approaches")) {
        Approach ap;
        ap.id = a.str("id");
        ap.name = a.str("name");
        ap.leg = a.str("leg");
        ap.demand_scale = a.num("demand_scale", 1.0);
        for (const Value &l : a.arr("links")) ap.links.push_back(l.s);
        approaches.push_back(std::move(ap));
    }

    for (const Value &h : root.arr("heat_groups")) {
        HeatGroup g;
        g.id = h.str("id");
        g.name = h.str("name", g.id);
        heat_groups.push_back(std::move(g));
    }

    for (const Value &s : root.arr("scenarios")) {
        Scenario sc;
        sc.id = s.str("id");
        sc.name = s.str("name");
        sc.note = s.str("note");
        sc.hour = s.num("hour", -1.0);
        const Value &m = s["multipliers"];
        for (auto it = m.o.begin(); it != m.o.end(); ++it) sc.multipliers[it->first] = it->second.n;
        const Value &sl = s["speed_limits"];
        for (auto it = sl.o.begin(); it != sl.o.end(); ++it) sc.speed_limits[it->first] = it->second.n;
        const Value &ds = s["demand_scale"];
        for (auto it = ds.o.begin(); it != ds.o.end(); ++it) sc.demand_scale[it->first] = it->second.n;
        for (const Value &c : s.arr("close_links")) sc.close_links.push_back(c.s);
        if (s.has("signal_override")) {
            sc.has_signal_override = true;
            sc.signal_override = s["signal_override"];
        }
        scenarios.push_back(std::move(sc));
    }
    return !links.empty();
}

bool Network::load_file(const std::string &path) {
    std::ifstream f(path, std::ios::binary);
    if (!f) return false;
    std::ostringstream ss;
    ss << f.rdbuf();
    Value root = parse(ss.str());
    return load(root);
}

std::vector<size_t> Network::source_links() const {
    std::vector<size_t> out;
    for (size_t i = 0; i < links.size(); ++i) {
        auto it = nodes.find(links[i].from);
        if (it != nodes.end() && it->second.type == "source") out.push_back(i);
    }
    return out;
}

std::vector<size_t> Network::sink_links() const {
    std::vector<size_t> out;
    for (size_t i = 0; i < links.size(); ++i) {
        auto it = nodes.find(links[i].to);
        if (it != nodes.end() && it->second.type == "sink") out.push_back(i);
    }
    return out;
}

}  // namespace tj
