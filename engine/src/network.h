// The network model: nodes, lane-level links, turns, signals and demand, as
// emitted by tools/build_sites.py (schema 4).
#pragma once

#include <map>
#include <string>
#include <vector>

#include "geometry.h"
#include "json.h"

namespace tj {

struct VehicleClass {
    std::string id, name, color;
    double length = 4.3, width = 1.8, v0_kmph = 80.0, pcu = 1.0;
    double v0_mps = 22.2;
};

struct Detector {
    std::string id;
    double s_m = 0.0;
    std::string kind = "loop";
};

struct Phase {
    int index = 0;
    std::string name;
    double green = 30.0, amber = 4.0, all_red = 3.0;
    double min_green = 5.0, max_green = 60.0;
};

struct Signal {
    std::string id, name, strategy = "fixed_time", coordinator;
    double cycle_s = 60.0, offset_s = 0.0;
    std::vector<Phase> phases;

    void finalise() {
        cycle_s = 0.0;
        for (auto &p : phases) cycle_s += p.green + p.amber + p.all_red;
        if (cycle_s <= 0.0) cycle_s = 60.0;
    }
};

struct Curve {
    double s0 = 0.0, s1 = 0.0, R_m = 0.0;
};

// One approach as the UI knows it: a named group of links whose demand can be
// scaled by a slider (PRD section 7, Manual mode).
struct Approach {
    std::string id, name, leg;
    double demand_scale = 1.0;
    std::vector<std::string> links;
};

struct Link {
    std::string id, name, kind, carriageway, from, to, approach, heat_group, notes;
    int lanes = 1, lane_index = 0;
    double length_m = 0.0, length_surveyed_m = 0.0;
    double v0_kmph = 60.0, speed_limit_kmph = 60.0;
    double stop_line_m = 0.0, capacity_vph = 1800.0;
    bool queueable = true;
    Polyline geom;
    std::vector<Curve> curves;
    std::vector<Detector> detectors;
    std::map<std::string, int> phases;  // movement -> signal phase index
    std::map<std::string, double> class_mix;

    double v_limit_mps() const { return speed_limit_kmph / 3.6; }
    double v0_mps() const { return v0_kmph / 3.6; }
};

struct Turn {
    std::string from, to, movement;
    double weight = 1.0;
    int phase = -1;
};

struct DemandRow {
    std::string id, leg, movement, approach, note, connector;
    std::vector<std::string> route;
    double flow_vph_peak = 0.0;
    std::map<std::string, double> class_mix;
};

struct Node {
    std::string id, name, type, signal;
    double x = 0.0, y = 0.0;
};

struct Scenario {
    std::string id, name, note;
    double hour = -1.0;
    std::map<std::string, double> multipliers;
    std::map<std::string, double> speed_limits;
    std::map<std::string, double> demand_scale;
    std::vector<std::string> close_links;
    bool has_signal_override = false;
    Value signal_override;
};

struct HeatGroup {
    std::string id, name;
};

class Network {
public:
    std::string site_id, site_name, site_kind, summary, survey;
    double m_per_px = 0.55;
    std::vector<double> origin_px{960.0, 540.0};
    double rotation_deg = 0.0, scale_bar_m = 50.0;
    double display_px_per_m = 3.0;
    std::vector<double> display_origin_px{960.0, 540.0};
    double lane_width_m = 3.5;

    std::map<std::string, VehicleClass> vehicle_classes;
    std::vector<std::string> class_order;
    std::vector<double> hour_factors;

    std::map<std::string, Node> nodes;
    std::map<std::string, Signal> signals;
    std::vector<Link> links;
    std::map<std::string, size_t> link_index;
    std::vector<Turn> turns;
    std::vector<DemandRow> demand;
    std::vector<Approach> approaches;
    std::vector<HeatGroup> heat_groups;
    std::vector<Scenario> scenarios;

    bool load(const tj::Value &root);
    bool load_file(const std::string &path);

    const Link *link(const std::string &id) const {
        auto it = link_index.find(id);
        return it == link_index.end() ? nullptr : &links[it->second];
    }
    Link *link_mut(const std::string &id) {
        auto it = link_index.find(id);
        return it == link_index.end() ? nullptr : &links[it->second];
    }

    // Source links: links whose `from` node has no inbound link (the compiler
    // marks those nodes "source").  Vehicles are injected here.
    std::vector<size_t> source_links() const;
    std::vector<size_t> sink_links() const;

    double hour_factor(double hour) const {
        int h = int(hour) % 24;
        if (h < 0) h += 24;
        return h < int(hour_factors.size()) ? hour_factors[h] : 1.0;
    }
};

}  // namespace tj
