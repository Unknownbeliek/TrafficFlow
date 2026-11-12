// Microscopic simulation core.
//
// Vehicles advance along 1-D lane coordinates with RK4 integration of the
// Intelligent Driver Model, curve-limited speed from the traced geometry, and
// signal gating at link ends. Alerts are produced by root-finding on a
// Newton-divided-difference interpolant of v(t), so an event is reported at
// the instant the threshold was crossed rather than at the next frame.
#pragma once
#include <deque>
#include <random>
#include <string>
#include <vector>

#include "model.hpp"
#include "solvers.hpp"

namespace tf {

struct Vehicle {
  int id = -1;
  int cls = VCLASS_CAR;
  int link = 0;
  int lane = 0;
  double s = 0.0;      // metres along the link
  double v = 0.0;      // m/s
  double a = 0.0;      // last computed acceleration
  double v0 = 12.0;    // desired speed
  double len = 4.3, width = 1.8, vmax = 22.0, aMax = 1.6, bComf = 2.0;
  double T = 1.2, s0 = 2.0;
  bool active = true;

  // alert bookkeeping
  bool firedOverspeed = false;
  bool firedStandstill = false;
  double slowSince = -1.0;
  double histT[3] = {0., 0., 0.};
  double histV[3] = {0., 0., 0.};
  int histN = 0;
};

struct Event {
  std::string type;  // "overspeed" | "standstill" | "density"
  int vehicle = -1;
  std::string link;
  double time = 0.0;
  double value = 0.0;
  int iterations = 0;
  bool fallback = false;
  std::string method = "newton-safeguarded";
};

struct ApproachStats {
  std::string id, name, link;
  int queue = 0;
  int count = 0;
  double meanSpeedKph = 0.0;
  double density = 0.0;   // veh/km/lane
  char los = 'A';
  int throughput = 0;     // vehicles leaving this link in the last 60 s
};

class Sim {
 public:
  bool load(const std::string &sitePath);
  void reset();

  void setSeed(unsigned seed);
  void setDemandMode(const std::string &mode);          // "surveyed" | "manual"
  void setMultiplier(const std::string &demandId, double m);
  void setSignalCycle(double cycleSeconds);
  void setSpeed(double multiplier);
  void setPaused(bool paused) { paused_ = paused; }

  void advance(double wallSeconds);
  std::string snapshot();          // consume-and-clear the event queue
  std::string summaryJson() const;

  double time() const { return simTime_; }
  const Site &site() const { return site_; }
  const std::vector<Vehicle> &vehicles() const { return vehicles_; }

  // Signal state used by both the dynamics and the UI.
  void signalState(const std::string &group, char &state, double &remaining) const;

 private:
  void step(double dt);
  void spawn(double dt);
  void transferEndOfLink();
  void updateAlerts();

  double accel(const Vehicle &veh, double s, double v, double gap, double leaderV, double curveLimit,
               double stopDistance) const;
  bool mayCross(const Link &link, double v, double distanceToEnd) const;

  Site site_;
  std::vector<Vehicle> vehicles_;
  std::deque<int> laneQ_[512][8];  // [link][lane] ordered front (largest s) -> back
  int laneCount_[512] = {0};

  std::mt19937 rng_{12345};
  double simTime_ = 0.0;
  double dt_ = 0.05;
  double speedMul_ = 1.0;
  double accumulator_ = 0.0;
  bool paused_ = false;
  std::string demandMode_ = "surveyed";

  int nextId_ = 1;
  long spawned_ = 0, exited_ = 0;
  std::vector<Event> pendingEvents_;

  // throughput ring buffer per link (one bucket per second, 60 s)
  std::vector<int> exitBucket_[512];
  int bucketIndex_ = 0;
  double bucketTimer_ = 0.0;
};

}  // namespace tf
