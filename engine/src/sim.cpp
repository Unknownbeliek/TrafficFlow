#include "sim.hpp"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <sstream>

#include "json.hpp"

namespace tf {

using json::num;

namespace {
constexpr double kMaxLinks = 512;
constexpr double kAlertWindow = 0.5;  // seconds of history kept per vehicle

char losFromDensity(double k) {
  if (k < 8.0) return 'A';
  if (k < 14.0) return 'B';
  if (k < 21.0) return 'C';
  if (k < 28.0) return 'D';
  if (k < 40.0) return 'E';
  return 'F';
}
}  // namespace

bool Sim::load(const std::string &sitePath) {
  if (!site_.load(sitePath)) return false;
  reset();
  return true;
}

void Sim::reset() {
  vehicles_.clear();
  nextId_ = 1;
  spawned_ = exited_ = 0;
  simTime_ = 0.0;
  accumulator_ = 0.0;
  bucketIndex_ = 0;
  bucketTimer_ = 0.0;
  pendingEvents_.clear();
  const int nl = std::min<int>((int)site_.links.size(), (int)kMaxLinks);
  for (int i = 0; i < nl; ++i) {
    laneCount_[i] = site_.links[i].lanes;
    for (int l = 0; l < 8; ++l) laneQ_[i][l].clear();
    exitBucket_[i].assign(60, 0);
  }
  for (auto &d : site_.demand) d.multiplier = 1.0;
}

void Sim::setSeed(unsigned seed) { rng_.seed(seed); }
void Sim::setDemandMode(const std::string &mode) { demandMode_ = mode; }

void Sim::setMultiplier(const std::string &demandId, double m) {
  for (auto &d : site_.demand)
    if (d.id == demandId) d.multiplier = std::max(0.0, std::min(4.0, m));
}

void Sim::setSignalCycle(double cycleSeconds) {
  if (site_.plans.empty()) return;
  PhasePlan &plan = site_.plans.front();
  double total = plan.totalDuration();
  if (total <= 0.0) return;
  double scale = std::max(15.0, cycleSeconds) / total;
  for (auto &p : plan.phases) p.duration *= scale;   // keep phase proportions
  plan.cycle = 0.0;
  for (auto &p : plan.phases) plan.cycle += p.duration;
}

void Sim::setSpeed(double multiplier) { speedMul_ = std::max(0.1, std::min(10.0, multiplier)); }

void Sim::signalState(const std::string &group, char &state, double &remaining) const {
  state = 'G';
  remaining = 0.0;
  if (group.empty() || site_.plans.empty()) return;
  const PhasePlan &plan = site_.plans.front();
  double cycle = 0.0;
  for (const auto &p : plan.phases) cycle += p.duration;
  if (cycle <= 0.0) return;
  double t = std::fmod(simTime_ + plan.offset, cycle);
  if (t < 0) t += cycle;
  double acc = 0.0;
  for (const auto &p : plan.phases) {
    if (t < acc + p.duration) {
      auto it = p.states.find(group);
      state = it == p.states.end() ? 'G' : it->second;
      remaining = acc + p.duration - t;
      return;
    }
    acc += p.duration;
  }
}

bool Sim::mayCross(const Link &link, double v, double distanceToEnd) const {
  if (link.signalGroup.empty()) return true;
  char st;
  double rem;
  signalState(link.signalGroup, st, rem);
  if (st == 'G') return true;
  if (st == 'A') {
    // Amber: proceed only if stopping comfortably is no longer possible.
    double stopping = (v * v) / (2.0 * 2.2);
    return distanceToEnd < stopping * 1.15;
  }
  return false;
}

double Sim::accel(const Vehicle &veh, double s, double v, double gap, double leaderV,
                  double curveLimit, double stopGap) const {
  const double aMax = veh.aMax, b = veh.bComf;
  double g = std::max(0.4, gap);
  double dv = v - leaderV;
  double sStar = veh.s0 + std::max(0.0, v * veh.T + v * dv / (2.0 * std::sqrt(aMax * b)));
  double freeTerm = 1.0 - std::pow(std::max(0.0, v) / std::max(1.0, veh.v0), 4.0);
  double a = aMax * (freeTerm - (sStar / g) * (sStar / g));

  // Curvature: continuous braking pull toward the local curve speed limit,
  // which is where cloverleaf loops and the CP rings get their behaviour.
  if (v > curveLimit) a -= 1.6 * (v - curveLimit);

  // A red signal is just a stationary obstacle at the stop line.
  if (stopGap < 1e8) {
    double gg = std::max(0.4, stopGap);
    double sStarStop = veh.s0 + v * veh.T;
    a -= b * (sStarStop / gg) * (sStarStop / gg);
  }
  (void)s;
  if (a < -9.0) a = -9.0;
  if (a > 3.0) a = 3.0;
  return a;
}

void Sim::step(double dt) {
  simTime_ += dt;
  bucketTimer_ += dt;
  if (bucketTimer_ >= 1.0) {
    bucketTimer_ -= 1.0;
    bucketIndex_ = (bucketIndex_ + 1) % 60;
    for (int i = 0; i < (int)site_.links.size() && i < (int)kMaxLinks; ++i)
      if (!exitBucket_[i].empty()) exitBucket_[i][bucketIndex_] = 0;
  }

  spawn(dt);

  const int nl = std::min<int>((int)site_.links.size(), (int)kMaxLinks);
  for (int li = 0; li < nl; ++li) {
    const Link &link = site_.links[li];
    for (int lane = 0; lane < std::min(link.lanes, 8); ++lane) {
      auto &q = laneQ_[li][lane];
      for (size_t i = 0; i < q.size(); ++i) {
        Vehicle &veh = vehicles_[q[i]];
        double distEnd = link.lengthM - veh.s;
        bool cross = mayCross(link, veh.v, distEnd);

        // The leader of a lane sees open road at the link end unless the
        // signal (or a blocked exit) turns that end into a stationary obstacle.
        double gap = 1e9;
        double leaderV = 0.0;
        if (i > 0) {
          const Vehicle &lead = vehicles_[q[i - 1]];
          gap = lead.s - veh.s - lead.len;
          leaderV = lead.v;
        }
        double stopGap = 1e9;
        if (!cross) {
          gap = std::min(gap, distEnd);
          leaderV = 0.0;
          stopGap = distEnd;
        }

        // RK4 on (s, v) with the leader frozen across the step (standard
        // practice: leader motion within one 50 ms step is second-order small).
        const double s0 = veh.s, v0 = veh.v;
        auto deriv = [&](double s, double v) {
          double g = gap + (s0 - s);
          double cl = link.curveSpeedLimit(s);
          double a = accel(veh, s, v, g, leaderV, cl, stopGap < 1e8 ? stopGap + (s0 - s) : 1e9);
          return std::pair<double, double>(v, a);
        };
        auto k1 = deriv(s0, v0);
        auto k2 = deriv(s0 + 0.5 * dt * k1.first, v0 + 0.5 * dt * k1.second);
        auto k3 = deriv(s0 + 0.5 * dt * k2.first, v0 + 0.5 * dt * k2.second);
        auto k4 = deriv(s0 + dt * k3.first, v0 + dt * k3.second);

        double sNew = s0 + dt / 6.0 * (k1.first + 2 * k2.first + 2 * k3.first + k4.first);
        double vNew = v0 + dt / 6.0 * (k1.second + 2 * k2.second + 2 * k3.second + k4.second);

        // Physical guards: no negative speed, no penetration of the leader and
        // no overrun past the stop line when the signal is red.
        if (vNew < 0.0) { vNew = 0.0; sNew = s0; }
        if (vNew > veh.vmax) vNew = veh.vmax;
        double maxS = (i > 0) ? vehicles_[q[i - 1]].s - vehicles_[q[i - 1]].len - 0.3 : link.lengthM;
        if (!cross && distEnd < gap) maxS = std::min(maxS, link.lengthM);
        if (sNew > maxS) { sNew = std::max(s0, maxS); if (sNew < s0 + 1e-6 && vNew > 0.0) vNew = 0.0; }

        veh.a = (vNew - v0) / dt;
        veh.s = sNew;
        veh.v = vNew;

        // alert history (last three samples, used by the root finder)
        for (int h = 0; h < 2; ++h) { veh.histT[h] = veh.histT[h + 1]; veh.histV[h] = veh.histV[h + 1]; }
        veh.histT[2] = simTime_;
        veh.histV[2] = veh.v;
        if (veh.histN < 3) ++veh.histN;
      }
    }
  }

  transferEndOfLink();
  updateAlerts();
}

void Sim::spawn(double dt) {
  for (auto &d : site_.demand) {
    if (d.vehPerHour <= 0.0) continue;
    int li = site_.findLink(d.linkId);
    if (li < 0 || li >= (int)kMaxLinks) continue;
    double mult = (demandMode_ == "manual") ? d.multiplier : 1.0;
    double rate = d.vehPerHour * mult / 3600.0;
    if (rate <= 0.0) continue;
    std::poisson_distribution<int> poisson(rate * dt);
    int n = poisson(rng_);
    if (n > 8) n = 8;
    const Link &link = site_.links[li];

    // class mix (normalised, falls back to all-car)
    double total = 0.0;
    for (auto &kv : d.classMix) total += kv.second;
    for (int k = 0; k < n; ++k) {
      int cls = VCLASS_CAR;
      if (total > 0.0) {
        std::uniform_real_distribution<double> u(0.0, total);
        double r = u(rng_), acc = 0.0;
        for (auto &kv : d.classMix) {
          acc += kv.second;
          int c = classFromKey(kv.first);
          if (c >= 0 && r <= acc) { cls = c; break; }
        }
      }
      const ClassSpec &spec = kClasses[cls];

      // lane with room at the entry
      int bestLane = -1;
      size_t bestSize = SIZE_MAX;
      for (int l = 0; l < std::min(link.lanes, 8); ++l) {
        auto &q = laneQ_[li][l];
        double backS = q.empty() ? 1e9 : vehicles_[q.back()].s;
        if (backS < spec.length + 5.0) continue;
        if (q.size() < bestSize) { bestSize = q.size(); bestLane = l; }
      }
      if (bestLane < 0) continue;  // blocked at the entry: demand exceeds capacity

      Vehicle veh;
      veh.id = nextId_++;
      veh.cls = cls;
      veh.link = li;
      veh.lane = bestLane;
      veh.s = 0.0;
      veh.len = spec.length;
      veh.width = spec.width;
      veh.vmax = spec.vmaxKph / 3.6;
      veh.aMax = spec.aMax;
      veh.bComf = spec.bComf;
      veh.T = 1.1 + 0.3 * std::uniform_real_distribution<double>(0, 1)(rng_);
      veh.s0 = 1.6 + 0.6 * std::uniform_real_distribution<double>(0, 1)(rng_);
      std::uniform_real_distribution<double> u(0.9, 1.10);
      veh.v0 = std::min(veh.vmax, link.speedLimitMs() * u(rng_));
      veh.v = std::min(veh.v0, 6.0);
      laneQ_[li][bestLane].push_back((int)vehicles_.size());
      vehicles_.push_back(veh);
      ++spawned_;
    }
  }
}

void Sim::transferEndOfLink() {
  const int nl = std::min<int>((int)site_.links.size(), (int)kMaxLinks);
  for (int li = 0; li < nl; ++li) {
    const Link &link = site_.links[li];
    for (int lane = 0; lane < std::min(link.lanes, 8); ++lane) {
      auto &q = laneQ_[li][lane];
      while (!q.empty()) {
        int vi = q.front();
        Vehicle &veh = vehicles_[vi];
        if (veh.s < link.lengthM) break;

        int target = -1;
        if (!link.turns.empty()) {
          double total = 0.0;
          for (auto &t : link.turns) total += t.weight;
          std::uniform_real_distribution<double> u(0.0, total);
          double r = u(rng_), acc = 0.0;
          for (auto &t : link.turns) {
            acc += t.weight;
            if (r <= acc) { target = site_.findLink(t.link); break; }
          }
        }
        if (target < 0) {  // leaves the network
          veh.active = false;
          if (!exitBucket_[li].empty()) exitBucket_[li][bucketIndex_]++;
          q.pop_front();
          ++exited_;
          continue;
        }

        const Link &dest = site_.links[target];
        int bestLane = -1;
        size_t bestSize = SIZE_MAX;
        for (int l = 0; l < std::min(dest.lanes, 8); ++l) {
          auto &dq = laneQ_[target][l];
          double backS = dq.empty() ? 1e9 : vehicles_[dq.back()].s;
          if (backS < veh.len + 5.0) continue;
          if (dq.size() < bestSize) { bestSize = dq.size(); bestLane = l; }
        }
        if (bestLane < 0) {  // queue behind the stop line until there is room
          veh.s = link.lengthM - 0.2;
          veh.v = 0.0;
          break;
        }
        veh.link = target;
        veh.s -= link.lengthM;
        veh.lane = bestLane;
        q.pop_front();
        laneQ_[target][bestLane].push_back(vi);
      }
    }
  }
}

// ---------------------------------------------------------------------------
// Alerts: Newton-Raphson on a divided-difference interpolant of the sampled
// speed (or density) history. The interpolant is quadratic because three
// samples are kept, which is the smallest degree that gives a non-trivial
// derivative and therefore a meaningful Newton iteration count.
// ---------------------------------------------------------------------------
namespace {
struct AlertSolve {
  double time = 0.0;
  double value = 0.0;
  int iterations = 0;
  bool fallback = false;
  bool ok = false;
};

AlertSolve solveCrossing(const double t[3], const double y[3], double threshold, double lo, double hi) {
  AlertSolve out;
  double d01 = (y[1] - y[0]) / (t[1] - t[0]);
  double d12 = (y[2] - y[1]) / (t[2] - t[1]);
  double d012 = (d12 - d01) / (t[2] - t[0]);
  auto f = [&](double x) {
    return y[0] + (x - t[0]) * d01 + (x - t[0]) * (x - t[1]) * d012 - threshold;
  };
  auto df = [&](double x) { return d01 + (2.0 * x - t[0] - t[1]) * d012; };
  numerics::RootResult r = numerics::newtonSafeguarded(f, df, lo, hi, 1e-4, 12);
  out.time = r.root;
  out.iterations = r.iterations;
  out.fallback = r.usedBisectionFallback;
  out.value = f(r.root) + threshold;
  out.ok = r.converged;
  return out;
}
}  // namespace

void Sim::updateAlerts() {
  for (auto &veh : vehicles_) {
    if (!veh.active || veh.histN < 3) continue;
    const Link &link = site_.links[veh.link];

    // 1) over-speed: root of v(t) - limit
    double limit = link.speedLimitMs();
    if (!veh.firedOverspeed && veh.v > limit && veh.histV[0] <= limit) {
      AlertSolve s = solveCrossing(veh.histT, veh.histV, limit, veh.histT[0], veh.histT[2]);
      if (s.ok) {
        Event ev;
        ev.type = "overspeed";
        ev.vehicle = veh.id;
        ev.link = link.id;
        ev.time = s.time;
        ev.value = limit * 3.6;
        ev.iterations = s.iterations;
        ev.fallback = s.fallback;
        pendingEvents_.push_back(ev);
        veh.firedOverspeed = true;
      }
    }

    // 2) standstill: sustained speed below 0.3 m/s for 3 s
    if (veh.v < 0.3) {
      if (veh.slowSince < 0.0) veh.slowSince = simTime_;
      if (!veh.firedStandstill && simTime_ - veh.slowSince >= 3.0) {
        AlertSolve s = solveCrossing(veh.histT, veh.histV, 0.3, veh.histT[0], veh.histT[2]);
        Event ev;
        ev.type = "standstill";
        ev.vehicle = veh.id;
        ev.link = link.id;
        ev.time = s.ok ? s.time : simTime_;
        ev.iterations = s.iterations;
        ev.fallback = s.fallback;
        pendingEvents_.push_back(ev);
        veh.firedStandstill = true;
      }
    } else {
      veh.slowSince = -1.0;
      if (veh.v > 3.0) veh.firedStandstill = false;
    }
    if (veh.v < limit * 0.85) veh.firedOverspeed = false;
  }
  if (pendingEvents_.size() > 40) pendingEvents_.erase(pendingEvents_.begin(), pendingEvents_.end() - 40);
}

void Sim::advance(double wallSeconds) {
  if (paused_) return;
  accumulator_ += wallSeconds * speedMul_;
  int guard = 0;
  while (accumulator_ >= dt_ && guard < 4000) {
    step(dt_);
    accumulator_ -= dt_;
    ++guard;
  }
}

struct LinkStats {
  int count = 0;
  int queue = 0;
  double meanV = 0.0;
  double density = 0.0;  // veh/km/lane
  char los = 'A';
  int throughput = 0;    // veh/h over the trailing 60 s
};

std::string Sim::snapshot() {
  std::ostringstream os;

  // Per-link aggregates, computed once and reused for links and approaches.
  std::vector<LinkStats> ls(site_.links.size());
  for (size_t li = 0; li < site_.links.size(); ++li) {
    const Link &link = site_.links[li];
    double sumV = 0.0;
    for (int lane = 0; lane < std::min(link.lanes, 8); ++lane) {
      for (int vi : laneQ_[li][lane]) {
        const Vehicle &v = vehicles_[vi];
        if (!v.active) continue;
        ls[li].count++;
        sumV += v.v;
        if (v.v < 1.5) ls[li].queue++;
      }
    }
    if (ls[li].count > 0) ls[li].meanV = sumV / ls[li].count;
    double km = std::max(0.05, link.lengthM / 1000.0);
    ls[li].density = ls[li].count / (km * std::max(1, link.lanes));
    ls[li].los = losFromDensity(ls[li].density);
    int sum = 0;
    for (int b : exitBucket_[li]) sum += b;
    ls[li].throughput = sum;  // vehicles in the last 60 s == veh/h
  }

  os << "{\"t\":" << num(simTime_, 2) << ",\"speed\":" << num(speedMul_, 2)
     << ",\"paused\":" << (paused_ ? "true" : "false") << ",\"mode\":\"" << demandMode_ << "\""
     << ",\"site\":\"" << site_.id << "\"";

  os << ",\"signals\":[";
  for (size_t i = 0; i < site_.groups.size(); ++i) {
    char st;
    double rem;
    signalState(site_.groups[i], st, rem);
    if (i) os << ",";
    os << "[\"" << site_.groups[i] << "\",\"" << st << "\"," << num(rem, 1) << "]";
  }
  os << "]";

  os << ",\"vehicles\":[";
  bool first = true;
  double sumV = 0.0;
  int active = 0;
  for (const auto &v : vehicles_) {
    if (!v.active) continue;
    ++active;
    sumV += v.v;
    if (!first) os << ",";
    first = false;
    os << "[" << v.id << "," << v.cls << "," << v.link << "," << v.lane << "," << num(v.s, 1) << ","
       << num(v.v, 2) << "," << num(v.a, 2) << "]";
  }
  os << "]";

  os << ",\"links\":[";
  for (size_t li = 0; li < site_.links.size(); ++li) {
    if (li) os << ",";
    os << "{\"id\":\"" << site_.links[li].id << "\",\"n\":" << ls[li].count << ",\"q\":"
       << ls[li].queue << ",\"v\":" << num(ls[li].meanV * 3.6, 1) << ",\"k\":"
       << num(ls[li].density, 1) << ",\"los\":\"" << ls[li].los << "\",\"thr\":" << ls[li].throughput
       << "}";
  }
  os << "]";

  os << ",\"approaches\":[";
  for (size_t i = 0; i < site_.demand.size(); ++i) {
    const auto &d = site_.demand[i];
    int li = site_.findLink(d.linkId);
    if (li < 0) continue;
    if (i) os << ",";
    os << "{\"id\":\"" << d.id << "\",\"name\":\"" << d.name << "\",\"link\":\"" << d.linkId
       << "\",\"demand\":" << num(d.vehPerHour, 0) << ",\"mult\":" << num(d.multiplier, 2)
       << ",\"queue\":" << ls[li].queue << ",\"n\":" << ls[li].count << ",\"vk\":" << num(ls[li].meanV * 3.6, 1)
       << ",\"k\":" << num(ls[li].density, 1) << ",\"los\":\"" << ls[li].los << "\",\"thr\":"
       << ls[li].throughput << "}";
  }
  os << "]";

  os << ",\"events\":[";
  for (size_t i = 0; i < pendingEvents_.size(); ++i) {
    const Event &e = pendingEvents_[i];
    if (i) os << ",";
    os << "{\"type\":\"" << e.type << "\",\"veh\":" << e.vehicle << ",\"link\":\"" << e.link
       << "\",\"t\":" << num(e.time, 2) << ",\"value\":" << num(e.value, 1) << ",\"iter\":" << e.iterations
       << ",\"fallback\":" << (e.fallback ? "true" : "false") << ",\"method\":\"" << e.method << "\"}";
  }
  os << "]";

  os << ",\"totals\":{\"active\":" << active << ",\"spawned\":" << spawned_ << ",\"exited\":" << exited_
     << ",\"meanV\":" << num(active ? sumV / active * 3.6 : 0.0, 1) << "}}";

  pendingEvents_.clear();
  return os.str();
}

std::string Sim::summaryJson() const {
  std::ostringstream os;
  int active = 0;
  double sumV = 0.0, sumA = 0.0;
  for (const auto &v : vehicles_) {
    if (!v.active) continue;
    ++active;
    sumV += v.v;
    sumA += v.a;
  }
  os << "{\"site\":\"" << site_.id << "\",\"t\":" << num(simTime_, 1) << ",\"active\":" << active
     << ",\"spawned\":" << spawned_ << ",\"exited\":" << exited_
     << ",\"meanV\":" << num(active ? sumV / active * 3.6 : 0.0, 1)
     << ",\"meanA\":" << num(active ? sumA / active : 0.0, 2) << "}";
  return os.str();
}

}  // namespace tf
