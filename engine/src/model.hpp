// Network model: sites, links, signal plans and demand.
//
// A site is a self-contained interchange: traced lane centrelines in image
// pixel coordinates, a metre-per-pixel calibration, a signal plan and a
// demand profile. Nothing here knows about rendering; the same JSON is served
// to the browser so geometry cannot drift between engine and drawing.
#pragma once
#include <cmath>
#include <map>
#include <string>
#include <vector>

namespace tf {

struct Vec2 {
  double x = 0.0, y = 0.0;
};

struct Phase {
  std::string name;
  double duration = 10.0;
  // signal group -> 'G' (green) | 'A' (amber) | 'R' (red)
  std::map<std::string, char> states;
};

struct PhasePlan {
  std::string id = "default";
  double cycle = 120.0;
  double offset = 0.0;
  std::vector<Phase> phases;
  double totalDuration() const {
    double t = 0.0;
    for (const auto &p : phases) t += p.duration;
    return t;
  }
};

struct Turn {
  std::string link;   // destination link id
  double weight = 1.0;
};

struct Link {
  std::string id, name;
  std::vector<Vec2> pts;         // traced centreline, image pixels

  // Derived geometry
  std::vector<double> cumPx;     // cumulative pixel distance at each vertex
  double lengthPx = 0.0;
  double lengthM = 0.0;
  std::vector<double> curvature; // |dtheta/ds| per metre, sampled every 1 m

  int lanes = 1;
  double laneWidthM = 3.4;
  double speedLimitKph = 50.0;
  double saturationPcu = 1800.0;
  std::string signalGroup;       // empty -> unsignalised link end
  std::vector<Turn> turns;       // empty -> vehicles exit the network here

  double speedLimitMs() const { return speedLimitKph / 3.6; }
  double curvatureAt(double sM) const;
  // Curve-limited speed: v = sqrt(a_lat / kappa), capped at the posted limit.
  double curveSpeedLimit(double sM, double aLat = 2.0) const;
};

struct DemandEntry {
  std::string id, name, linkId;
  double vehPerHour = 0.0;
  std::map<std::string, double> classMix;
  double multiplier = 1.0;  // live slider (Manual mode)
};

struct Site {
  std::string id, name, kind;
  std::string image;        // path relative to the repository root
  std::vector<std::string> notes;
  int imageW = 1920, imageH = 1080;
  double metresPerPixel = 1.0;

  std::vector<Link> links;
  std::map<std::string, int> linkIndex;

  std::vector<std::string> groups;      // declared signal groups
  std::vector<PhasePlan> plans;
  std::vector<DemandEntry> demand;

  bool load(const std::string &path);
  int findLink(const std::string &id) const;
  const PhasePlan &plan() const { return plans.front(); }
};

// Vehicle class definitions (working defaults from the PRD, PCU per IRC).
enum VehicleClass { VCLASS_CAR = 0, VCLASS_TAXI, VCLASS_2W, VCLASS_AUTO, VCLASS_LCV, VCLASS_TRUCK, VCLASS_BUS, VCLASS_COUNT };

struct ClassSpec {
  const char *key;
  const char *label;
  double length;    // m
  double width;     // m
  double vmaxKph;   // physical cap
  double aMax;      // m/s^2
  double bComf;     // comfortable deceleration, m/s^2
  double pcu;
};

extern const ClassSpec kClasses[VCLASS_COUNT];
int classFromKey(const std::string &key);

}  // namespace tf
