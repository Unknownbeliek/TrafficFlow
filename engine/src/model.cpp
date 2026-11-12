#include "model.hpp"

#include <algorithm>
#include <cstdio>
#include <fstream>
#include <sstream>
#include <stdexcept>

#include "json.hpp"

namespace tf {

const ClassSpec kClasses[VCLASS_COUNT] = {
    {"car", "Car", 4.3, 1.8, 80.0, 1.60, 2.00, 1.0},
    {"taxi", "Taxi", 4.4, 1.8, 75.0, 1.70, 2.00, 1.0},
    {"2w", "Two-wheeler", 1.9, 0.7, 60.0, 2.20, 2.50, 0.5},
    {"auto", "Auto-rickshaw", 2.6, 1.4, 45.0, 1.30, 2.20, 1.2},
    {"lcv", "LCV", 5.5, 2.1, 55.0, 1.20, 1.80, 1.5},
    {"truck", "Truck", 9.0, 2.5, 40.0, 0.85, 1.50, 3.0},
    {"bus", "Bus", 12.0, 2.5, 45.0, 0.95, 1.50, 3.0},
};

int classFromKey(const std::string &key) {
  for (int i = 0; i < VCLASS_COUNT; ++i)
    if (key == kClasses[i].key) return i;
  return -1;
}

double Link::curvatureAt(double sM) const {
  if (curvature.empty()) return 0.0;
  double idx = std::max(0.0, std::min<double>(sM, (double)curvature.size() - 1.0));
  int i = (int)idx;
  int j = std::min(i + 1, (int)curvature.size() - 1);
  double f = idx - i;
  return curvature[i] * (1.0 - f) + curvature[j] * f;
}

double Link::curveSpeedLimit(double sM, double aLat) const {
  double k = curvatureAt(sM);
  if (k < 1e-4) return speedLimitMs();
  double v = std::sqrt(aLat / k);
  return std::min(v, speedLimitMs());
}

namespace {
double dist(const Vec2 &a, const Vec2 &b) { return std::hypot(b.x - a.x, b.y - a.y); }
}  // namespace

namespace {

void buildGeometry(Link &link, double metresPerPixel) {
  link.cumPx.assign(link.pts.size(), 0.0);
  for (size_t i = 1; i < link.pts.size(); ++i)
    link.cumPx[i] = link.cumPx[i - 1] + dist(link.pts[i - 1], link.pts[i]);
  link.lengthPx = link.cumPx.empty() ? 0.0 : link.cumPx.back();
  link.lengthM = link.lengthPx * metresPerPixel;
  if (link.lengthM < 1e-6) link.lengthM = 1.0;

  // Curvature sampled once per metre, so the dynamics can ask for k(s)
  // cheaply at any position and the frontend can draw the same limit.
  int n = std::max(1, (int)std::lround(link.lengthM));
  link.curvature.assign(n + 1, 0.0);
  if (link.pts.size() < 3) return;

  // Walk the polyline, computing heading change per metre.
  std::vector<double> heading(link.pts.size(), 0.0);
  for (size_t i = 1; i < link.pts.size(); ++i)
    heading[i] = std::atan2(link.pts[i].y - link.pts[i - 1].y, link.pts[i].x - link.pts[i - 1].x);

  for (size_t i = 0; i + 1 < heading.size(); ++i) {
    double dh = heading[i + 1] - heading[i];
    while (dh > M_PI) dh -= 2 * M_PI;
    while (dh < -M_PI) dh += 2 * M_PI;
    double ds = std::max(1e-6, (link.cumPx[i + 1] - link.cumPx[i]) * metresPerPixel);
    double k = std::fabs(dh) / ds;
    int s0 = (int)std::lround(link.cumPx[i] * metresPerPixel);
    int s1 = (int)std::lround(link.cumPx[i + 1] * metresPerPixel);
    for (int s = s0; s <= s1 && s < (int)link.curvature.size(); ++s)
      link.curvature[s] = std::max(link.curvature[s], k);
  }
  // Light smoothing keeps RK4 from seeing a spike at every vertex.
  for (size_t i = 1; i + 1 < link.curvature.size(); ++i)
    link.curvature[i] = 0.25 * link.curvature[i - 1] + 0.5 * link.curvature[i] + 0.25 * link.curvature[i + 1];
}

}  // namespace

bool Site::load(const std::string &path) {
  std::ifstream in(path);
  if (!in) {
    std::fprintf(stderr, "engine: cannot open site file %s\n", path.c_str());
    return false;
  }
  std::stringstream ss;
  ss << in.rdbuf();
  try {
    json::Value root = json::parse(ss.str());
    id = root["id"].asStr(path);
    name = root["name"].asStr(id);
    kind = root["kind"].asStr();
    image = root["image"].asStr();
    metresPerPixel = root["metres_per_pixel"].asNum(1.0);
    const auto &isz = root["image_size"].items();
    if (isz.size() >= 2) {
      imageW = (int)isz[0].asNum(1920);
      imageH = (int)isz[1].asNum(1080);
    }
    for (const auto &n : root["notes"].items()) notes.push_back(n.asStr());

    for (const auto &g : root["signal_groups"].items()) groups.push_back(g.asStr());

    for (const auto &pl : root["signal_plans"].items()) {
      PhasePlan plan;
      plan.id = pl["id"].asStr("default");
      plan.cycle = pl["cycle"].asNum(120.0);
      plan.offset = pl["offset"].asNum(0.0);
      for (const auto &ph : pl["phases"].items()) {
        Phase p;
        p.name = ph["name"].asStr();
        p.duration = ph["duration"].asNum(10.0);
        // "states" is either an object {group: "G"} or a compact string "GGR"
        // mapping onto the declared group order.
        if (ph["states"].isObj()) {
          for (const auto &kv : *ph["states"].obj) p.states[kv.first] = kv.second.asStr("R")[0];
        } else if (ph["states"].isStr()) {
          std::string s = ph["states"].asStr();
          for (size_t i = 0; i < groups.size() && i < s.size(); ++i) p.states[groups[i]] = s[i];
        }
        plan.phases.push_back(p);
      }
      if (!plan.phases.empty()) plans.push_back(plan);
    }
    if (plans.empty()) {
      // Unsignalised site: one endless green phase keeps the code path uniform.
      PhasePlan plan;
      plan.id = "none";
      plan.cycle = 1e9;
      Phase p;
      p.name = "free";
      p.duration = 1e9;
      for (const auto &g : groups) p.states[g] = 'G';
      plan.phases.push_back(p);
      plans.push_back(plan);
    }

    for (const auto &ln : root["links"].items()) {
      Link link;
      link.id = ln["id"].asStr();
      link.name = ln["name"].asStr(link.id);
      link.lanes = std::max(1, ln["lanes"].asInt(1));
      link.laneWidthM = ln["lane_width_m"].asNum(3.4);
      link.speedLimitKph = ln["speed_limit_kmh"].asNum(50.0);
      link.saturationPcu = ln["saturation_pcu_h"].asNum(1800.0);
      link.signalGroup = ln["signal_group"].asStr();
      for (const auto &pt : ln["points"].items()) {
        const auto &arr = pt.items();
        if (arr.size() >= 2) link.pts.push_back({arr[0].asNum(), arr[1].asNum()});
      }
      for (const auto &t : ln["turns"].items()) {
        Turn turn;
        turn.link = t["link"].asStr();
        turn.weight = t["weight"].asNum(1.0);
        link.turns.push_back(turn);
      }
      if (link.pts.size() < 2) continue;
      buildGeometry(link, metresPerPixel);
      linkIndex[link.id] = (int)links.size();
      links.push_back(std::move(link));
    }

    for (const auto &d : root["demand"].items()) {
      DemandEntry e;
      e.id = d["id"].asStr();
      e.name = d["name"].asStr(e.id);
      e.linkId = d["link"].asStr();
      e.vehPerHour = d["veh_per_hour"].asNum(0.0);
      if (d["class_mix"].isObj())
        for (const auto &kv : *d["class_mix"].obj) e.classMix[kv.first] = kv.second.asNum(0.0);
      demand.push_back(e);
    }

    // Resolve turn destinations to indices; drop links that do not exist.
    for (auto &link : links) {
      std::vector<Turn> valid;
      for (auto &t : link.turns)
        if (linkIndex.count(t.link)) valid.push_back(t);
      link.turns = valid;
    }
    return !links.empty();
  } catch (const std::exception &e) {
    std::fprintf(stderr, "engine: bad site file %s: %s\n", path.c_str(), e.what());
    return false;
  }
}

int Site::findLink(const std::string &id) const {
  auto it = linkIndex.find(id);
  return it == linkIndex.end() ? -1 : it->second;
}

}  // namespace tf
