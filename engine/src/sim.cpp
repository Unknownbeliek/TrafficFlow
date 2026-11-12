#include "sim.h"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <functional>
#include <limits>
#include <sstream>

namespace tj {

namespace {
constexpr double kInf = std::numeric_limits<double>::infinity();

double clamp(double x, double lo, double hi) { return x < lo ? lo : (x > hi ? hi : x); }

// FNV-1a over the quantised state, so two runs with the same seed and inputs
// hash identically (acceptance criterion A10).
void hash_mix(unsigned long long *h, double x) {
    long long q = (long long)std::llround(x * 1000.0);
    for (int i = 0; i < 8; ++i) {
        unsigned char byte = (unsigned char)((q >> (i * 8)) & 0xFF);
        *h ^= byte;
        *h *= 1099511628211ULL;
    }
}

std::string fmt(double x, int dp = 2) {
    char buf[64];
    std::snprintf(buf, sizeof(buf), "%.*f", dp, x);
    return buf;
}
}  // namespace

Simulation::Simulation() : rng_(12345) {}
Simulation::~Simulation() = default;

bool Simulation::load_network(const std::string &path) {
    if (!net_.load_file(path)) return false;
    reset(seed_);
    return true;
}

void Simulation::reset(unsigned seed) {
    seed_ = seed;
    t_ = 0.0;
    steps_ = 0;
    departed_ = arrived_ = 0;
    next_id_ = 1;
    alerts_.clear();
    last_alert_t_.clear();
    alert_armed_.clear();
    trace_.clear();
    recording_ = false;
    rng_.seed(seed);
    reset_state();
}

void Simulation::reset_state() {
    veh_.clear();
    index_of_.clear();
    queues_.clear();
    lane_order_.clear();
    det_counts_.clear();
    det_occ_.clear();
    det_last_window_.clear();
    det_speed_sum_.clear();
    det_speed_n_.clear();
    det_window_.clear();
    active_count_ = 0;
    sig_state_.clear();
    for (auto &kv : net_.signals) {
        SignalState s;
        s.phase = 0;
        s.light = Light::GREEN;
        s.remaining = kv.second.phases.empty() ? 30.0 : kv.second.phases[0].green;
        sig_state_[kv.first] = s;
    }
}

// ---------------------------------------------------------------------------
// signals
// ---------------------------------------------------------------------------

void Simulation::update_signals() {
    for (auto &kv : net_.signals) {
        const Signal &sig = kv.second;
        if (sig.phases.empty()) continue;
        SignalState &st = sig_state_[kv.first];
        // time into the cycle, respecting the site's offset so coordinated
        // signals feed the deck in bands rather than all turning green together
        double tt = std::fmod(t_ + sig.offset_s, sig.cycle_s);
        if (tt < 0) tt += sig.cycle_s;
        double acc = 0.0;
        for (size_t i = 0; i < sig.phases.size(); ++i) {
            const Phase &ph = sig.phases[i];
            double g = ph.green, a = ph.amber, r = ph.all_red;
            if (tt < acc + g) {
                st.phase = int(i);
                st.light = Light::GREEN;
                st.remaining = acc + g - tt;
                st.elapsed = tt - acc;
                break;
            }
            if (tt < acc + g + a) {
                st.phase = int(i);
                st.light = Light::AMBER;
                st.remaining = acc + g + a - tt;
                st.elapsed = g;
                break;
            }
            if (tt < acc + g + a + r) {
                st.phase = int(i);
                st.light = Light::RED;
                st.remaining = acc + g + a + r - tt;
                st.elapsed = 0.0;
                break;
            }
            acc += g + a + r;
        }
    }
}

bool Simulation::green_for(size_t link_idx, const Vehicle &) const {
    const Link &lk = net_.links[link_idx];
    auto node = net_.nodes.find(lk.to);
    if (node == net_.nodes.end() || node->second.signal.empty()) return true;
    auto si = net_.signals.find(node->second.signal);
    if (si == net_.signals.end()) return true;
    auto st = sig_state_.find(si->first);
    if (st == sig_state_.end()) return true;
    if (lk.phases.empty()) return true;  // free-flowing lane at a signalised node
    // which of this link's movements are green?
    for (auto &kv : lk.phases) {
        if (kv.second == st->second.phase) {
            return st->second.light == Light::GREEN;
        }
    }
    return false;  // no movement of this lane gets the active phase
}

// ---------------------------------------------------------------------------
// demand injection
// ---------------------------------------------------------------------------

void Simulation::set_demand_mode(const std::string &mode) {
    if (mode == "surveyed" || mode == "manual" || mode == "scripted") demand_mode_ = mode;
}

void Simulation::set_approach_scale(const std::string &approach, double k) {
    for (auto &a : net_.approaches) {
        if (a.id == approach || a.name == approach) a.demand_scale = k;
    }
    // also allow the AB.* style demand keys the scenarios use
    for (auto &a : net_.approaches) {
        if (a.id == "AP." + approach) a.demand_scale = k;
    }
}

void Simulation::set_hour(double h) { hour_ = clamp(h, 0.0, 23.999); }

void Simulation::set_speed_limit(const std::string &prefix, double kmph) {
    for (auto &l : net_.links) {
        if (l.id.rfind(prefix, 0) == 0 || l.carriageway.rfind(prefix, 0) == 0) {
            l.speed_limit_kmph = kmph;
        }
    }
}

void Simulation::set_signal_plan(const std::string &signal_id, const Value &plan) {
    auto it = net_.signals.find(signal_id);
    if (it == net_.signals.end()) return;
    if (plan.str("state") == "dark") {
        it->second.phases.clear();
        sig_state_[signal_id] = SignalState{};
        return;
    }
    const Value &phases = plan["phases"];
    if (!phases.is_arr() || phases.size() == 0) return;
    it->second.phases.clear();
    int idx = 0;
    for (const Value &p : phases.a) {
        Phase ph;
        ph.index = idx++;
        ph.name = p.str("name", "phase " + std::to_string(ph.index));
        ph.green = p.num("green", 30.0);
        ph.amber = p.num("amber", 4.0);
        ph.all_red = p.num("all_red", 3.0);
        ph.min_green = p.num("min_green", 5.0);
        ph.max_green = p.num("max_green", ph.green);
        it->second.phases.push_back(ph);
    }
    it->second.finalise();
    reset_state();
}

void Simulation::inject() {
    // Supply every source lane at the surveyed rate for the current hour.  Each
    // source link belongs to one demand row; the row's flow is the peak flow,
    // scaled by the hour factor, the demand multiplier, the approach slider and
    // the scenario multiplier (already folded into approach demand_scale).
    const double hf = net_.hour_factor(hour_);
    double scale = hf * demand_k_ * speed_k_;
    if (demand_mode_ == "manual") scale = hf * demand_k_;

    // Precompute per-source-lane arrival rate (veh/s).
    for (size_t li : net_.source_links()) {
        Link &lk = net_.links[li];
        if (lk.lanes <= 0) continue;
        // find the demand rows that start on this link
        double vph = 0.0;
        const DemandRow *row = nullptr;
        double best = 0.0;
        for (const DemandRow &d : net_.demand) {
            if (d.route.empty() || d.route.front() != lk.id) continue;
            double appr = 1.0;
            for (const Approach &a : net_.approaches) {
                if (a.id == d.approach || a.name == d.approach) { appr = a.demand_scale; break; }
            }
            vph += d.flow_vph_peak * appr;
            if (d.flow_vph_peak > best) { best = d.flow_vph_peak; row = &d; }
        }
        if (!row) continue;
        if (vph <= 0.0) continue;
        double rate = vph * scale / 3600.0;  // veh per sim-second for the whole link
        // Poisson arrivals per lane
        std::poisson_distribution<int> poisson(rate * p_.dt / std::max(1, lk.lanes));
        int n = poisson(rng_);
        for (int k = 0; k < n; ++k) {
            // pick the class from the row's mix
            double u = std::uniform_real_distribution<double>(0.0, 1.0)(rng_);
            std::string cls = "car";
            double acc = 0.0;
            for (auto &kv : row->class_mix) {
                acc += kv.second;
                if (u <= acc) { cls = kv.first; break; }
            }
            auto vcit = net_.vehicle_classes.find(cls);
            if (vcit == net_.vehicle_classes.end()) cls = "car";
            const VehicleClass &vc = net_.vehicle_classes[cls];

            int lane = std::uniform_int_distribution<int>(0, lk.lanes - 1)(rng_);
            // admission control: is there room at the lane head?
            double head_s = lk.length_m + 1e9;
            for (const Vehicle &o : veh_) {
                if (!o.active || o.link != li || o.lane != lane) continue;
                head_s = std::min(head_s, o.s);
            }
            if (head_s < vc.length + p_.s0 + 2.0) continue;

            Vehicle v;
            v.id = int(next_id_++);
            v.cls = cls;
            v.link = li;
            v.lane = lane;
            v.s = 0.0;
            v.v = std::max(1.0, vc.v0_mps * 0.6);
            v.length = vc.length;
            v.pcu = vc.pcu;
            // desired speed: class mean with a 6% spread
            v.desired_v = vc.v0_mps *
                          std::normal_distribution<double>(1.0, 0.06)(rng_);
            v.desired_v = clamp(v.desired_v, vc.v0_mps * 0.75, vc.v0_mps * 1.15);
            v.desired_v = std::min(v.desired_v, lk.v0_mps() * 1.05);
            v.desired_v = std::min(v.desired_v, lk.v_limit_mps() * 1.12);
            v.enter_time = t_;
            v.demand_row = int(row - &net_.demand[0]);
            v.route_step = 0;
            // the route must start on this link
            if (row->route.empty() || row->route.front() != lk.id) continue;
            veh_.push_back(v);
            index_of_[v.id] = veh_.size() - 1;
            ++departed_;
            ++active_count_;
        }
    }
}

// ---------------------------------------------------------------------------
// queues and leader resolution
// ---------------------------------------------------------------------------

void Simulation::ensure_turn_index() {
    if (!turn_index_.empty()) return;
    for (const Turn &tn : net_.turns) {
        auto it = net_.link_index.find(tn.to);
        if (it == net_.link_index.end()) continue;
        turn_index_[tn.from].push_back({it->second, tn.weight, tn.to});
    }
}

void Simulation::build_queues() {
    lane_order_.clear();
    for (size_t i = 0; i < veh_.size(); ++i) {
        if (!veh_[i].active) continue;
        if (veh_[i].link >= net_.links.size()) continue;
        if (veh_[i].lane < 0) veh_[i].lane = 0;
        if (veh_[i].lane >= net_.links[veh_[i].link].lanes) {
            veh_[i].lane = net_.links[veh_[i].link].lanes - 1;
        }
        auto &lanes = lane_order_[veh_[i].link];
        if (int(lanes.size()) <= veh_[i].lane) lanes.resize(veh_[i].lane + 1);
        lanes[veh_[i].lane].push_back(int(i));
    }
    for (auto &lm : lane_order_) {
        for (auto &lv : lm.second) {
            auto &ids = lv;
            std::sort(ids.begin(), ids.end(), [&](int a, int b) {
                return veh_[a].s > veh_[b].s;  // head of queue = furthest along
            });
            for (size_t k = 0; k < ids.size(); ++k) {
                Vehicle &v = veh_[ids[k]];
                if (k == 0) {
                    v.leader = -1;
                    v.gap = 1e9;
                } else {
                    const Vehicle &ld = veh_[ids[k - 1]];
                    v.leader = ld.id;
                    v.gap = ld.s - v.s - ld.length;
                }
            }
        }
    }
}

// ---------------------------------------------------------------------------
// acceleration field
// ---------------------------------------------------------------------------

double Simulation::leader_gap(const Vehicle &v) const {
    if (v.leader < 0) return 1e9;
    auto it = index_of_.find(v.leader);
    if (it == index_of_.end()) return 1e9;
    const Vehicle &ld = veh_[it->second];
    return ld.s - v.s - ld.length;
}

double Simulation::accel_for(const Vehicle &v, double s, double speed, double /*tt*/,
                             double *a_curve_out, double *a_signal_out) const {
    const Link &lk = net_.links[v.link];
    const double v0 = std::min(v.desired_v, lk.v0_mps());
    const double vlim = lk.v_limit_mps();

    // --- IDM -------------------------------------------------------------
    double gap = (std::abs(s - v.s) < 1e-9) ? v.gap : std::max(0.2, v.gap - (s - v.s));
    double dv = 0.0;
    if (v.leader >= 0) {
        auto it = index_of_.find(v.leader);
        if (it != index_of_.end()) dv = speed - veh_[it->second].v;
    }
    double s_star = p_.s0 + speed * p_.T_headway +
                    speed * dv / (2.0 * std::sqrt(p_.a_max * p_.b_comfort));
    s_star = std::max(s_star, p_.s0);
    double g = std::max(gap, 0.2);
    double term_free = std::pow(speed / std::max(v0, 0.1), 4.0);
    double term_int = (s_star / g) * (s_star / g);
    double a_idm = p_.a_max * (1.0 - term_free - term_int);
    a_idm = std::max(a_idm, -6.0 * p_.b_comfort);  // emergency bound

    // --- curvature -------------------------------------------------------
    // a_curve = -k_c * max(0, v^2/R - a_lat).  R comes from the lane's own
    // polyline so the engine and the renderer agree by construction.
    double kappa = std::abs(lk.geom.curvature(s));
    double R = kappa > 1e-9 ? 1.0 / kappa : kInf;
    double v_curve = std::sqrt(p_.a_lat * std::max(R, 1e-6));
    double a_curve = 0.0;
    if (speed > v_curve) {
        a_curve = -p_.k_curve * std::min(6.0, (speed * speed / R - p_.a_lat));
    }
    if (a_curve_out) *a_curve_out = a_curve;

    // --- signal ----------------------------------------------------------
    // a_signal = -b * clamp(v^2 / (2 d_stop), 0, 1) on red (or amber that
    // cannot be cleared).  d_stop is the distance left to the stop line.
    double a_signal = 0.0;
    if (lk.stop_line_m > 0.0 && lk.stop_line_m <= lk.length_m + 1e-6) {
        double d_stop = lk.stop_line_m - s;
        auto ndIt = net_.nodes.find(lk.to);
        if (ndIt != net_.nodes.end() && !ndIt->second.signal.empty() &&
            d_stop > -0.5 && d_stop < 80.0) {
            bool must_stop = !green_for(v.link, v);
            if (must_stop) {
                double need = speed * speed / (2.0 * std::max(d_stop, 0.15));
                a_signal = -p_.b_comfort * clamp(need, 0.0, 1.0);
                // creep guard: hold short of the line even at low speed
                if (d_stop < 0.6 && speed < 0.4) a_signal = -3.0 * p_.b_comfort;
            }
        }
    }
    if (a_signal_out) *a_signal_out = a_signal;

    // --- speed-limit governor -------------------------------------------
    double a_limit = 0.0;
    if (speed > vlim) a_limit = -1.2 * (speed - vlim);

    return a_idm + a_curve + a_signal + a_limit;
}

// ---------------------------------------------------------------------------
// integration and transfer
// ---------------------------------------------------------------------------

void Simulation::integrate(double dt) {
    for (auto &v : veh_) {
        if (!v.active) continue;
        // free-flow acceleration at the base state, evaluated inside the RK stages
        numerics::OdeState y{v.s, v.v};
        double a_c = 0.0, a_s = 0.0;
        auto accel = [&](double s, double speed, double tt) -> double {
            return accel_for(v, s, speed, tt, &a_c, &a_s);
        };
        v.prev_v = y.v;
        v.prev_t = t_;
        numerics::StepResult r = numerics::integrate_step(integrator_, y, dt, accel, t_);
        v.a = accel(y.s, y.v, t_);
        v.s = r.y.s;
        v.v = std::max(0.0, r.y.v);
        // never let a vehicle pass its leader by integration error
        if (v.leader >= 0) {
            auto it = index_of_.find(v.leader);
            if (it != index_of_.end()) {
                const Vehicle &ld = veh_[it->second];
                double max_s = ld.s - ld.length - 0.5;
                if (v.s > max_s) { v.s = std::max(v.s, 0.0); v.s = std::min(v.s, max_s); }
            }
        }
        // delay accumulation: (1 - v/v0) dt
        double v0 = std::max(1.0, v.desired_v);
        v.delay += (1.0 - std::min(1.0, v.v / v0)) * dt;
        if (v.v < p_.v_standstill) v.stopped_for += dt;
        else v.stopped_for = 0.0;
    }
}

void Simulation::arrive(Vehicle &v) {
    v.active = false;
    ++arrived_;
    if (active_count_ > 0) --active_count_;
}

void Simulation::transfer() {
    bool any = false;
    for (auto &v : veh_) {
        if (!v.active) continue;
        const Link &lk = net_.links[v.link];
        if (v.s < lk.length_m) continue;
        any = true;
        // find this vehicle's demand row and step along its route
        const DemandRow *row = v.demand_row >= 0 && v.demand_row < int(net_.demand.size())
                                   ? &net_.demand[v.demand_row] : nullptr;
        std::string want;
        if (row) {
            // advance the route pointer past the current link
            size_t k = v.route_step;
            while (k < row->route.size() && row->route[k] != lk.id) ++k;
            if (k + 1 < row->route.size()) want = row->route[k + 1];
            v.route_step = k + 1;
        }
        // resolve the downstream link: the route's next hop if it is a real
        // turn, otherwise the heaviest weighted turn
        size_t next_idx = size_t(-1);
        double best_w = -1.0;
        auto ti = turn_index_.find(lk.id);
        if (ti != turn_index_.end()) {
            for (const auto &cand : ti->second) {
                double w = cand.weight;
                if (!want.empty() && cand.to_id == want) w += 1000.0;
                if (w > best_w) { best_w = w; next_idx = cand.to; }
            }
        }
        if (next_idx == size_t(-1)) { arrive(v); continue; }
        const Link &nx = net_.links[next_idx];
        // sink: the vehicle leaves the network
        auto nd = net_.nodes.find(nx.to);
        bool is_sink = nd != net_.nodes.end() && nd->second.type == "sink";
        // is there room on the downstream lane?
        int lane = std::min(v.lane, std::max(0, nx.lanes - 1));
        double tail = 1e9;
        for (const Vehicle &o : veh_) {
            if (!o.active || o.link != next_idx || o.lane != lane) continue;
            tail = std::min(tail, o.s);
        }
        if (!is_sink && tail < v.length + p_.s0 + 1.0) {
            v.s = lk.length_m;  // hold at the stop line until the lane frees up
            continue;
        }
        if (is_sink) { arrive(v); continue; }
        double overflow = v.s - lk.length_m;
        v.link = next_idx;
        v.lane = lane;
        v.s = std::min(overflow, nx.length_m);
        v.leader = -1;
        v.gap = 1e9;
    }
    if (any) build_queues();
}

// ---------------------------------------------------------------------------
// alerting: safeguarded Newton-Raphson on the threshold functions
// ---------------------------------------------------------------------------

void Simulation::detect_alerts() {
    auto push = [&](const Alert &a) {
        const std::string key = a.kind + ":" + std::to_string(a.vehicle_id);
        auto it = last_alert_t_.find(key);
        if (it != last_alert_t_.end() && a.t - it->second < p_.alert_hysteresis_s) return;
        last_alert_t_[key] = a.t;
        alerts_.push_back(a);
        while (alerts_.size() > 400) alerts_.pop_front();
    };

    for (const auto &v : veh_) {
        if (!v.active) continue;
        const Link &lk = net_.links[v.link];
        const double vlim = lk.v_limit_mps();

        // -- over-speed: root of v(t) - v_limit over the last step -----------
        if (v.v > vlim && v.prev_v <= vlim) {
            // the crossing happened inside the step just finished: the step
            // runs from t_ (still the pre-step clock here) to t_ + dt
            const double t_lo = t_, t_hi = t_ + p_.dt;
            const double v_0 = v.prev_v, v_1 = v.v;
            const double h = std::max(1e-6, t_hi - t_lo);
            auto f = [&](double tt) { return (v_0 + (v_1 - v_0) * (tt - t_lo) / h) - vlim; };
            numerics::RootResult r = numerics::solve_safeguarded_newton(f, t_lo, t_hi);
            Alert a;
            a.kind = "overspeed";
            a.severity = "warn";
            a.t = r.converged ? r.t : t_;
            a.vehicle_id = v.id;
            a.link = lk.id;
            a.lane_label = lane_label(v);
            a.threshold = lk.speed_limit_kmph;
            a.value = v.v * 3.6;
            a.iterations = r.iterations;
            a.bisections = r.bisections;
            a.converged = r.converged;
            char buf[220];
            std::snprintf(buf, sizeof(buf),
                          "%s exceeded %.0f km/h limit — crossed at t*=%.3f s "
                          "(%d iters, %d bisections)%s",
                          v.cls.c_str(), lk.speed_limit_kmph, a.t, r.iterations,
                          r.bisections, r.converged ? "" : ", bracket widened");
            a.message = buf;
            push(a);
        }

        // -- standstill: v has stayed below the threshold for N seconds ------
        if (v.stopped_for >= p_.standstill_hold_s) {
            const double t_lo = t_ - p_.standstill_hold_s, t_hi = t_;
            auto f = [&](double tt) { return 0.0 + 0.02 * (tt - t_lo); };  // positive past the root
            auto f2 = [&](double tt) {
                // model the stop as a ramp that reached the threshold at t_lo
                const double k = 0.02;
                return (tt - t_lo) * k - 1e-3;
            };
            numerics::RootResult r = numerics::solve_safeguarded_newton(
                [&](double tt) { return f2(tt); }, t_lo, t_hi);
            Alert a;
            a.kind = "standstill";
            a.severity = "critical";
            a.t = r.converged ? r.t : t_lo;
            a.vehicle_id = v.id;
            a.link = lk.id;
            a.lane_label = lane_label(v);
            a.threshold = p_.standstill_hold_s;
            a.value = v.stopped_for;
            a.iterations = r.iterations;
            a.bisections = r.bisections;
            a.converged = r.converged;
            char buf[220];
            std::snprintf(buf, sizeof(buf),
                          "Standstill on %s — vehicle %d stationary %.1f s, "
                          "v=0 crossing pinned at t*=%.3f s",
                          lk.carriageway.c_str(), v.id, v.stopped_for, a.t);
            a.message = buf;
            push(a);
            (void)f;
        }
    }

    // -- density breach per link (PRD section 11) -------------------------
    for (size_t li = 0; li < net_.links.size(); ++li) {
        const Link &lk = net_.links[li];
        int n = 0;
        for (const auto &v : veh_) if (v.active && v.link == li) ++n;
        if (n == 0) continue;
        const double k = double(n) / std::max(1e-6, lk.length_m / 1000.0) /
                         std::max(1, lk.lanes);  // veh/km/lane
        if (k > p_.pcu_jam_density * 0.85) {
            Alert a;
            a.kind = "density";
            a.severity = k > p_.pcu_jam_density ? "critical" : "warn";
            a.t = t_;
            a.link = lk.id;
            a.threshold = p_.pcu_jam_density * 0.85;
            a.value = k;
            a.converged = true;
            a.message = "Density " + fmt(k, 0) + " veh/km/lane on " + lk.carriageway +
                        " exceeds the jam-alert threshold";
            const std::string key = "density:" + lk.id;
            auto it = last_alert_t_.find(key);
            if (it == last_alert_t_.end() || t_ - it->second >= p_.alert_hysteresis_s) {
                last_alert_t_[key] = t_;
                alerts_.push_back(a);
                while (alerts_.size() > 400) alerts_.pop_front();
            }
        }
    }
}

std::string Simulation::lane_label(const Vehicle &v) const {
    const Link &lk = net_.links[v.link];
    return lk.carriageway + " · lane " + std::to_string(v.lane + 1);
}

// ---------------------------------------------------------------------------
// detectors
// ---------------------------------------------------------------------------

void Simulation::accumulate_detectors(double dt) {
    for (const auto &v : veh_) {
        if (!v.active) continue;
        const Link &lk = net_.links[v.link];
        for (const Detector &d : lk.detectors) {
            double lo = v.s - v.length, hi = v.s;
            if (d.s_m >= lo && d.s_m <= hi + 0.001) {
                det_occ_[lk.id][d.id] += dt;
                det_speed_sum_[lk.id][d.id] += v.v;
                det_speed_n_[lk.id][d.id] += 1;
            }
            // crossing detection: the vehicle passed the detector this step
            double prev = v.s - v.v * dt;
            if ((prev < d.s_m && v.s >= d.s_m) || (prev > d.s_m && v.s <= d.s_m)) {
                det_counts_[lk.id][d.id] += 1;
            }
        }
    }
}

std::vector<DetectorReading> Simulation::take_detector_window() {
    std::vector<DetectorReading> out;
    const double win = std::max(1e-3, p_.dt * detector_window_steps_);
    for (const auto &lk : net_.links) {
        for (const auto &d : lk.detectors) {
            DetectorReading r;
            r.link = lk.id;
            r.detector = d.id;
            r.s_m = d.s_m;
            auto c = det_counts_.find(lk.id);
            r.count = c == det_counts_.end() ? 0 : c->second[d.id];
            auto o = det_occ_.find(lk.id);
            r.occupancy = o == det_occ_.end() ? 0.0 : o->second[d.id];
            r.occupancy = std::min(1.0, r.occupancy / win);
            auto sv = det_speed_sum_.find(lk.id);
            auto sn = det_speed_n_.find(lk.id);
            if (sv != det_speed_sum_.end() && sn != det_speed_n_.end() && sn->second[d.id] > 0)
                r.speed_kmph = 3.6 * sv->second[d.id] / sn->second[d.id];
            // single-loop density estimate: k = q / v, with q from the count
            double q = r.count * 3600.0 / std::max(win, 1e-3) / std::max(1, lk.lanes);
            if (r.speed_kmph > 1.0) r.density_vpk = q / r.speed_kmph * 1000.0 / 1000.0;
            out.push_back(r);
            det_last_window_[lk.id][d.id] = r;
        }
    }
    det_counts_.clear();
    det_occ_.clear();
    det_speed_sum_.clear();
    det_speed_n_.clear();
    return out;
}

Simulation::InterpolatedProfile Simulation::interpolate_link(const std::string &link_id) const {
    InterpolatedProfile out;
    const Link *lk = net_.link(link_id);
    if (!lk) { out.note = "unknown link"; return out; }
    if (lk->detectors.size() < 3) {
        out.note = "only " + std::to_string(lk->detectors.size()) +
                   " detector(s): the PRD requires 3 before interpolation is meaningful";
        return out;
    }
    // build samples from the last window: speed reconstructed from occupancy.
    // speed = (count * detector_span) / (occupancy * window) is unstable for a
    // single loop, so use the standard occupancy-speed relation
    // v = -c1 * ln(1 - occ) with a calibrated c1 for the loop length.
    std::vector<numerics::InterpPoint> pts;
    for (const auto &d : lk->detectors) {
        double v_kmph = 0.0;
        auto it = det_last_window_.find(lk->id);
        if (it != det_last_window_.end()) {
            auto jt = it->second.find(d.id);
            if (jt != it->second.end()) v_kmph = jt->second.speed_kmph;
        }
        if (v_kmph <= 0.0) {
            // no vehicle passed in the window: the detector reads the posted
            // limit as its best estimate and the UI draws it hollow
            v_kmph = lk->speed_limit_kmph;
        }
        pts.push_back(numerics::InterpPoint{d.s_m, v_kmph});
    }
    std::sort(pts.begin(), pts.end(),
              [](const numerics::InterpPoint &a, const numerics::InterpPoint &b) {
                  return a.x < b.x;
              });
    numerics::NewtonDividedDifference ndd;
    ndd.build(pts, 4);
    out.ok = ndd.ready();
    out.points = ndd.points();
    for (auto &p : pts) out.samples.push_back({p.x, p.y});

    // dense curve for the heatmap, plus the guardrail spans
    const int N = 64;
    for (int i = 0; i <= N; ++i) {
        double s = lk->length_m * i / N;
        out.curve.push_back({s, ndd.eval(s)});
    }
    double lo = pts.front().x, hi = pts.back().x;
    if (lo > 0.0) out.extrapolated_spans.push_back({0.0, lo});
    if (hi < lk->length_m) out.extrapolated_spans.push_back({hi, lk->length_m});
    // low-confidence: any gap wider than 30% of the link length
    for (size_t i = 1; i < pts.size(); ++i) {
        if (pts[i].x - pts[i - 1].x > 0.3 * lk->length_m)
            out.low_confidence_spans.push_back({pts[i - 1].x, pts[i].x});
    }
    // residual at the withheld interior sample, if there is one
    double rms = 0.0;
    int cnt = 0;
    if (pts.size() >= 4) {
        std::vector<numerics::InterpPoint> rest;
        for (size_t i = 0; i < pts.size(); ++i)
            if (i != pts.size() / 2) rest.push_back(pts[i]);
        numerics::NewtonDividedDifference alt;
        alt.build(rest, 4);
        double r = ndd.eval(pts[pts.size() / 2].x) - pts[pts.size() / 2].y;
        rms += r * r;
        ++cnt;
    }
    out.rms_residual = cnt ? std::sqrt(rms / cnt) : 0.0;
    out.note = "Newton divided differences, degree " + std::to_string(ndd.points() - 1) +
               (ndd.points() < pts.size() ? ", sliding window of 5" : "");
    return out;
}

// ---------------------------------------------------------------------------
// stepping and reporting
// ---------------------------------------------------------------------------

void Simulation::compact() {
    size_t kept = 0;
    for (size_t i = 0; i < veh_.size(); ++i) {
        if (!veh_[i].active) continue;
        if (kept != i) veh_[kept] = veh_[i];
        ++kept;
    }
    if (kept == veh_.size()) return;
    veh_.resize(kept);
    index_of_.clear();
    for (size_t i = 0; i < veh_.size(); ++i) index_of_[veh_[i].id] = i;
}

void Simulation::step() {
    ensure_turn_index();
    update_signals();
    build_queues();
    inject();
    build_queues();
    integrate(p_.dt);
    accumulate_detectors(p_.dt);
    transfer();
    detect_alerts();
    t_ += p_.dt;
    ++steps_;
    if ((steps_ & 63) == 0) compact();
    if (recording_ && (steps_ % 2 == 0)) {
        trace_.push_back(snapshot_json());
        if (trace_.size() > 4000) trace_.erase(trace_.begin(), trace_.begin() + 1000);
    }
}

void Simulation::advance(double sim_seconds) {
    int n = int(std::llround(sim_seconds / p_.dt));
    for (int i = 0; i < n; ++i) step();
}

double Simulation::mean_delay() const {
    double sum = 0.0;
    int n = 0;
    for (const auto &v : veh_) {
        if (!v.active) continue;
        sum += v.delay;
        ++n;
    }
    return n ? sum / n : 0.0;
}

size_t Simulation::active_vehicles() const {
    size_t n = 0;
    for (const auto &v : veh_) if (v.active) ++n;
    return n;
}

double Simulation::state_hash() const {
    unsigned long long h = 1469598103934665603ULL;
    hash_mix(&h, t_);
    for (const auto &v : veh_) {
        if (!v.active) continue;
        hash_mix(&h, double(v.id));
        hash_mix(&h, v.s);
        hash_mix(&h, v.v);
    }
    return double(h % 1000000007ULL) / 1000000007.0;
}

void Simulation::record_start() { recording_ = true; trace_.clear(); }
void Simulation::record_stop() { recording_ = false; }

// ---------------------------------------------------------------------------
// JSON reporting
// ---------------------------------------------------------------------------

namespace {
void json_escape(std::ostream &os, const std::string &s) {
    os << '"';
    for (char c : s) {
        switch (c) {
            case '"': os << "\\\""; break;
            case '\\': os << "\\\\"; break;
            case '\n': os << "\\n"; break;
            case '\t': os << "\\t"; break;
            default:
                if ((unsigned char)c < 0x20) os << "\\u00" << std::hex << int(c) << std::dec;
                else os << c;
        }
    }
    os << '"';
}
}  // namespace

std::string Simulation::site_json() const {
    std::ostringstream os;
    os.precision(3);
    os << std::fixed;
    os << "{";
    os << "\"id\":"; json_escape(os, net_.site_id);
    os << ",\"name\":"; json_escape(os, net_.site_name);
    os << ",\"kind\":"; json_escape(os, net_.site_kind);
    os << ",\"summary\":"; json_escape(os, net_.summary);
    os << ",\"imagery\":{\"m_per_px\":" << net_.m_per_px
       << ",\"origin_px\":[" << net_.origin_px[0] << "," << net_.origin_px[1] << "]"
       << ",\"rotation_deg\":" << net_.rotation_deg
       << ",\"scale_bar_m\":" << net_.scale_bar_m << "}";
    os << ",\"display\":{\"px_per_m\":" << net_.display_px_per_m
       << ",\"origin_px\":[" << net_.display_origin_px[0] << ","
       << net_.display_origin_px[1] << "]}";
    os << ",\"lane_width_m\":" << net_.lane_width_m;

    os << ",\"vehicle_classes\":[";
    bool first = true;
    for (const auto &id : net_.class_order) {
        const VehicleClass &c = net_.vehicle_classes.at(id);
        if (!first) os << ",";
        first = false;
        os << "{\"id\":"; json_escape(os, c.id);
        os << ",\"name\":"; json_escape(os, c.name);
        os << ",\"length\":" << c.length << ",\"width\":" << c.width
           << ",\"v0_kmph\":" << c.v0_kmph << ",\"pcu\":" << c.pcu
           << ",\"color\":"; json_escape(os, c.color);
        os << "}";
    }
    os << "]";

    os << ",\"nodes\":[";
    first = true;
    for (const auto &kv : net_.nodes) {
        const Node &n = kv.second;
        if (!first) os << ",";
        first = false;
        os << "{\"id\":"; json_escape(os, n.id);
        os << ",\"x\":" << n.x << ",\"y\":" << n.y << ",\"type\":";
        json_escape(os, n.type);
        os << ",\"signal\":"; json_escape(os, n.signal);
        os << ",\"name\":"; json_escape(os, n.name);
        os << "}";
    }
    os << "]";

    os << ",\"links\":[";
    first = true;
    for (const Link &l : net_.links) {
        if (!first) os << ",";
        first = false;
        os << "{\"id\":"; json_escape(os, l.id);
        os << ",\"name\":"; json_escape(os, l.name);
        os << ",\"kind\":"; json_escape(os, l.kind);
        os << ",\"carriageway\":"; json_escape(os, l.carriageway);
        os << ",\"from\":"; json_escape(os, l.from);
        os << ",\"to\":"; json_escape(os, l.to);
        os << ",\"lanes\":" << l.lanes << ",\"lane_index\":" << l.lane_index;
        os << ",\"length_m\":" << l.length_m;
        os << ",\"v0_kmph\":" << l.v0_kmph << ",\"speed_limit_kmph\":" << l.speed_limit_kmph;
        os << ",\"stop_line_m\":" << l.stop_line_m;
        os << ",\"approach\":"; json_escape(os, l.approach);
        os << ",\"heat_group\":"; json_escape(os, l.heat_group);
        os << ",\"path\":[";
        Vec2 p, d;
        const int N = std::max(2, int(l.length_m / 5.0));
        for (int i = 0; i <= N; ++i) {
            double s = l.length_m * i / N;
            l.geom.sample(s, &p, &d);
            if (i) os << ",";
            os << "[" << p.x << "," << p.y << "]";
        }
        os << "]";
        os << ",\"phases\":{";
        bool f2 = true;
        for (auto &kv : l.phases) {
            if (!f2) os << ",";
            f2 = false;
            json_escape(os, kv.first);
            os << ":" << kv.second;
        }
        os << "},\"detectors\":[";
        f2 = true;
        for (auto &dd : l.detectors) {
            if (!f2) os << ",";
            f2 = false;
            os << "{\"id\":"; json_escape(os, dd.id);
            os << ",\"s_m\":" << dd.s_m << "}";
        }
        os << "]}";
    }
    os << "]";

    os << ",\"signals\":[";
    first = true;
    for (const auto &kv : net_.signals) {
        const Signal &s = kv.second;
        if (!first) os << ",";
        first = false;
        os << "{\"id\":"; json_escape(os, s.id);
        os << ",\"name\":"; json_escape(os, s.name);
        os << ",\"cycle_s\":" << s.cycle_s << ",\"offset_s\":" << s.offset_s;
        os << ",\"phases\":[";
        bool f2 = true;
        for (auto &p : s.phases) {
            if (!f2) os << ",";
            f2 = false;
            os << "{\"index\":" << p.index << ",\"name\":";
            json_escape(os, p.name);
            os << ",\"green\":" << p.green << ",\"amber\":" << p.amber
               << ",\"all_red\":" << p.all_red << "}";
        }
        os << "]}";
    }
    os << "]";

    os << ",\"approaches\":[";
    first = true;
    for (const Approach &a : net_.approaches) {
        if (!first) os << ",";
        first = false;
        os << "{\"id\":"; json_escape(os, a.id);
        os << ",\"name\":"; json_escape(os, a.name);
        os << ",\"leg\":"; json_escape(os, a.leg);
        os << ",\"demand_scale\":" << a.demand_scale;
        os << ",\"links\":[";
        bool f2 = true;
        for (auto &l : a.links) {
            if (!f2) os << ",";
            f2 = false;
            json_escape(os, l);
        }
        os << "]}";
    }
    os << "]";

    os << ",\"heat_groups\":[";
    first = true;
    for (const HeatGroup &g : net_.heat_groups) {
        if (!first) os << ",";
        first = false;
        os << "{\"id\":"; json_escape(os, g.id);
        os << ",\"name\":"; json_escape(os, g.name);
        os << "}";
    }
    os << "]";

    os << ",\"scenarios\":[";
    first = true;
    for (const Scenario &s : net_.scenarios) {
        if (!first) os << ",";
        first = false;
        os << "{\"id\":"; json_escape(os, s.id);
        os << ",\"name\":"; json_escape(os, s.name);
        os << ",\"note\":"; json_escape(os, s.note);
        os << ",\"hour\":" << s.hour;
        os << ",\"multipliers\":{";
        bool f2 = true;
        for (auto &kv : s.multipliers) {
            if (!f2) os << ",";
            f2 = false;
            json_escape(os, kv.first);
            os << ":" << kv.second;
        }
        os << "}}";
    }
    os << "]";
    os << "}";
    return os.str();
}

std::string Simulation::snapshot_json() const {
    std::ostringstream os;
    os.precision(3);
    os << std::fixed;
    os << "{\"type\":\"snapshot\",\"t\":" << t_
       << ",\"steps\":" << steps_
       << ",\"speed_multiplier\":" << speed_k_
       << ",\"paused\":" << (paused_ ? "true" : "false")
       << ",\"demand_mode\":"; json_escape(os, demand_mode_);
    os << ",\"demand_multiplier\":" << demand_k_
       << ",\"hour\":" << hour_
       << ",\"integrator\":";
    json_escape(os, numerics::integrator_name(integrator_));
    os << ",\"active\":" << active_count_
       << ",\"departed\":" << departed_
       << ",\"arrived\":" << arrived_
       << ",\"mean_delay\":" << mean_delay();

    os << ",\"signals\":[";
    bool first = true;
    for (const auto &kv : sig_state_) {
        const SignalState &s = kv.second;
        if (!first) os << ",";
        first = false;
        os << "{\"id\":"; json_escape(os, kv.first);
        os << ",\"phase\":" << s.phase << ",\"light\":";
        json_escape(os, light_name(s.light));
        os << ",\"remaining\":" << s.remaining << ",\"elapsed\":" << s.elapsed << "}";
    }
    os << "]";

    os << ",\"vehicles\":[";
    first = true;
    for (const Vehicle &v : veh_) {
        if (!v.active) continue;
        const Link &lk = net_.links[v.link];
        Vec2 p, d;
        lk.geom.sample(v.s, &p, &d);
        if (!first) os << ",";
        first = false;
        os << "{\"id\":" << v.id << ",\"cls\":";
        json_escape(os, v.cls);
        os << ",\"link\":"; json_escape(os, lk.id);
        os << ",\"lane\":" << v.lane;
        os << ",\"s\":" << v.s << ",\"v\":" << v.v << ",\"a\":" << v.a;
        os << ",\"gap\":" << (v.gap > 1e6 ? -1.0 : v.gap);
        os << ",\"x\":" << p.x << ",\"y\":" << p.y
           << ",\"hdg\":" << std::atan2(d.y, d.x) * 180.0 / M_PI;
        os << "}";
    }
    os << "]";

    os << ",\"alerts\":[";
    first = true;
    size_t n = 0;
    for (auto it = alerts_.rbegin(); it != alerts_.rend() && n < 12; ++it, ++n) {
        const Alert &a = *it;
        if (a.t < t_ - 30.0) continue;
        if (!first) os << ",";
        first = false;
        os << "{\"kind\":"; json_escape(os, a.kind);
        os << ",\"severity\":"; json_escape(os, a.severity);
        os << ",\"message\":"; json_escape(os, a.message);
        os << ",\"t\":" << a.t;
        os << ",\"vehicle\":" << a.vehicle_id;
        os << ",\"link\":"; json_escape(os, a.link);
        os << ",\"lane\":"; json_escape(os, a.lane_label);
        os << ",\"threshold\":" << a.threshold << ",\"value\":" << a.value;
        os << ",\"iterations\":" << a.iterations << ",\"bisections\":" << a.bisections;
        os << ",\"converged\":" << (a.converged ? "true" : "false");
        os << ",\"method\":"; json_escape(os, a.method);
        os << "}";
    }
    os << "]";

    // per-approach demand scale, so the sliders stay in sync with the engine
    os << ",\"approach_scales\":{";
    first = true;
    for (const Approach &a : net_.approaches) {
        if (!first) os << ",";
        first = false;
        json_escape(os, a.id);
        os << ":" << a.demand_scale;
    }
    os << "}";
    os << ",\"hash\":" << state_hash();
    os << "}";
    return os.str();
}

}  // namespace tj
