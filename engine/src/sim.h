// The microscopic simulation: signals, demand injection, IDM car-following,
// lane transfer, and the alert clock.
#pragma once

#include <deque>
#include <map>
#include <memory>
#include <random>
#include <set>
#include <string>
#include <vector>

#include "network.h"
#include "numerics.h"

namespace tj {

enum class Light { GREEN, AMBER, RED };

inline const char *light_name(Light l) {
    switch (l) {
        case Light::GREEN: return "green";
        case Light::AMBER: return "amber";
        default: return "red";
    }
}

// A signal's instantaneous state: which phase is active and how long is left.
struct SignalState {
    int phase = 0;
    Light light = Light::GREEN;
    double remaining = 0.0;   // seconds left in this light state
    double elapsed = 0.0;     // seconds into the current phase's green
};

struct SimParams {
    double dt = 0.05;             // fixed integration step (PRD section 8)
    double a_max = 1.6;           // m/s^2, comfortable acceleration
    double b_comfort = 2.0;       // m/s^2, comfortable braking
    double T_headway = 1.2;       // s, desired time headway
    double s0 = 2.0;              // m, standstill gap
    double a_lat = 2.0;           // m/s^2, lateral comfort bound
    double k_curve = 1.0;         // curvature gain
    double v_standstill = 0.05;   // m/s threshold use by the alert
    double standstill_hold_s = 3.0;
    double alert_hysteresis_s = 8.0;   // was 2 s: the feed churned faster than it could be read
    double pcu_jam_density = 130.0;  // veh/km/lane at jam
};

// One simulated vehicle.  `link`/`lane` identify the lane it is on; `s` is its
// arc length from the lane start; `v` its speed.  `leader` is the vehicle ahead
// on the same lane, recomputed each step from the ordered queue.
struct Vehicle {
    int id = 0;
    std::string cls;
    size_t link = 0;
    int lane = 0;
    double s = 0.0, v = 0.0, a = 0.0, prev_v = 0.0, prev_t = 0.0;
    double length = 4.3;
    double desired_v = 20.0;   // v0 for this driver (drawn around the class mean)
    double pcu = 1.0;
    int leader = -1;           // vehicle id ahead
    double gap = 1e9;          // bumper-to-bumper gap to that leader
    bool active = true;        // false once it has left the network
    size_t route_step = 0;     // index into the demand row's route
    int demand_row = -1;
    double enter_time = 0.0;
    double delay = 0.0;        // accumulated (1 - v/v0) dt, the standard delay measure
    double stopped_for = 0.0;
};

struct Alert {
    std::string kind;       // overspeed / standstill / density
    std::string severity;   // info / warn / critical
    std::string message;
    double t = 0.0;         // exact simulated instant of the crossing (PRD section 11)
    int vehicle_id = -1;
    std::string link, lane_label;
    double threshold = 0.0, value = 0.0;
    int iterations = 0, bisections = 0;
    bool converged = false;
    std::string method = "safeguarded_newton";
};

// Detector reading accumulated over a reporting window (PRD section 6/10): the
// interpolation and the heatmap both consume these.
struct DetectorReading {
    std::string link, detector;
    double s_m = 0.0;
    int count = 0;           // vehicles that crossed since the window opened
    double occupancy = 0.0;  // fraction of the window time that a vehicle covered it
    double speed_kmph = 0.0; // mean speed of vehicles passing the point
    double density_vpk = 0.0;  // per-lane density implied by the occupancy
};

struct LaneQueue {
    std::vector<int> order;  // vehicle ids, head first
    void clear() { order.clear(); }
};

class Simulation {
public:
    Simulation();
    ~Simulation();

    bool load_network(const std::string &path);
    const Network &net() const { return net_; }
    Network &net_mut() { return net_; }

    void reset(unsigned seed = 12345);
    void step();                     // advance one dt
    void advance(double sim_seconds); // advance by wall-clock-equivalent time

    // -- control surface (the stdio protocol in the PRD) --
    void set_speed_multiplier(double k) { speed_k_ = k; }
    double speed_multiplier() const { return speed_k_; }
    void set_integrator(numerics::Integrator k) { integrator_ = k; }
    numerics::Integrator integrator() const { return integrator_; }
    void set_paused(bool p) { paused_ = p; }
    bool paused() const { return paused_; }
    void set_demand_mode(const std::string &mode);
    const std::string &demand_mode() const { return demand_mode_; }
    void set_demand_multiplier(double k) { demand_k_ = k; }
    double demand_multiplier() const { return demand_k_; }
    void set_approach_scale(const std::string &approach, double k);
    void set_hour(double h);
    double hour() const { return hour_; }
    void set_signal_plan(const std::string &signal_id, const Value &plan);
    void set_speed_limit(const std::string &prefix, double kmph);

    // -- state --
    double t() const { return t_; }
    long step_count() const { return steps_; }
    const std::vector<Vehicle> &vehicles() const { return veh_; }
    const std::map<std::string, SignalState> &signal_states() const { return sig_state_; }
    const std::deque<Alert> &alerts() const { return alerts_; }
    size_t active_vehicles() const;
    long departed() const { return departed_; }
    long arrived() const { return arrived_; }
    double mean_delay() const;
    double state_hash() const;   // for the determinism acceptance check (A10)

    // Detector window: read the last complete window and start a new one.
    std::vector<DetectorReading> take_detector_window();
    // Reconstruct a smooth speed profile along a link from its detector
    // readings using Newton divided differences (PRD section 10).
    struct InterpolatedProfile {
        bool ok = false;
        size_t points = 0;
        std::vector<std::pair<double, double>> samples;  // (s_m, speed_kmph)
        std::vector<std::pair<double, double>> curve;    // dense, for the heatmap
        std::vector<std::pair<double, double>> extrapolated_spans;
        std::vector<std::pair<double, double>> low_confidence_spans;
        double rms_residual = 0.0;
        std::string note;
    };
    InterpolatedProfile interpolate_link(const std::string &link_id) const;

    // Snapshot for the bridge: everything the client needs for one frame.
    std::string snapshot_json() const;
    std::string site_json() const;

    SimParams &params() { return p_; }
    const SimParams &params() const { return p_; }

    void record_start();
    void record_stop();
    bool recording() const { return recording_; }
    size_t recorded_frames() const { return trace_.size(); }
    const std::vector<std::string> &trace() const { return trace_; }

private:
    void reset_state();
    void update_signals();
    void inject();
    void ensure_turn_index();
    void compact();
    void build_queues();
    // last line of defence against same-lane body overlap: after integration
    // and after every lane change, clamp each follower so its bumper never
    // passes the tail of the car ahead.  IDM plus the transfer admission test
    // handle this in the smooth case; this catches the discrete-time corners
    // (a vehicle injected at s=0 while another still sits near the entry, a
    // transfer that lands on an occupied lane, a step that overshoots).
    void enforce_lane_separation();
    void integrate(double dt);
    void transfer();
    void detect_alerts();
    void accumulate_detectors(double dt);
    double accel_for(const Vehicle &v, double s, double speed, double t, double *a_curve_out,
                     double *a_signal_out) const;
    double leader_gap(const Vehicle &v) const;
    bool green_for(size_t link_idx, const Vehicle &v) const;
    void arrive(Vehicle &v);
    std::string lane_label(const Vehicle &v) const;

    Network net_;
    SimParams p_;
    numerics::Integrator integrator_ = numerics::Integrator::RK4;

    double t_ = 0.0;
    // sub-step residual: `advance()` is called once per animation frame with an
    // arbitrary wall-clock interval, so whole steps alone would make playback
    // run at a rounded rate (a 0.16 s frame becoming 0.20 s is a 25% error) and
    // move in visible jumps.  Carrying the remainder keeps the rate exact.
    double step_credit_ = 0.0;
    long steps_ = 0;
    double speed_k_ = 1.0;
    bool paused_ = false;
    double demand_k_ = 1.0;
    double hour_ = 8.0;
    std::string demand_mode_ = "surveyed";

    std::vector<Vehicle> veh_;
    std::map<int, size_t> index_of_;   // vehicle id -> slot in veh_
    size_t active_count_ = 0;
    long next_id_ = 1;
    long departed_ = 0, arrived_ = 0;

    std::map<std::string, SignalState> sig_state_;
    std::map<size_t, std::vector<LaneQueue>> queues_;  // per link, per lane
    std::map<size_t, std::vector<std::vector<int>>> lane_order_;
    struct TurnCand { size_t to; double weight; std::string to_id; };
    std::map<std::string, std::vector<TurnCand>> turn_index_;

    std::mt19937 rng_;
    unsigned seed_ = 12345;

    std::deque<Alert> alerts_;
    std::map<std::string, double> last_alert_t_;   // debounce keyed by kind+vehicle
    std::map<std::string, bool> alert_armed_;

    // detector accumulation
    std::vector<DetectorReading> det_window_;
    std::map<std::string, std::map<std::string, int>> det_counts_;
    std::map<std::string, std::map<std::string, double>> det_occ_;
    std::map<std::string, std::map<std::string, double>> det_speed_sum_;
    std::map<std::string, std::map<std::string, int>> det_speed_n_;
    int detector_window_steps_ = 20;   // 1 s at dt = 0.05
    std::map<std::string, std::map<std::string, DetectorReading>> det_last_window_;

    bool recording_ = false;
    std::vector<std::string> trace_;
};

}  // namespace tj
