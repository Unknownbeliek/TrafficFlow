// Trackflow engine entry point.
//
// Two front ends share one binary:
//   * a numbered CLI menu (the ES-251 "menu-driven program" requirement), and
//   * a line-oriented JSON stdio protocol the Node bridge speaks.
//
//   ./trackflow_engine                      -> interactive menu
//   ./trackflow_engine --site kalindi_kunj  -> menu with a site preloaded
//   ./trackflow_engine --stdio              -> bridge mode
//   ./trackflow_engine --verify             -> regenerate verification/*.csv
//   ./trackflow_engine --run 600            -> headless, prints a summary
#include <chrono>
#include <cstdio>
#include <cstring>
#include <iostream>
#include <sstream>
#include <string>
#include <thread>
#include <vector>

#include "json.h"
#include "numerics.h"
#include "sim.h"
#include "verify.h"

namespace {
std::string g_data_dir = "site-data";
std::string g_site = "kalindi_kunj";

std::string network_path(const std::string &site) {
    return g_data_dir + "/" + site + "/network.json";
}

std::string read_line() {
    std::string line;
    std::getline(std::cin, line);
    return line;
}

void print_help() {
    std::printf(
        "\nTrackflow engine — menu\n"
        "  1  load a site\n"
        "  2  set demand (mode / multiplier / hour)\n"
        "  3  run headless for N simulated seconds\n"
        "  4  run the verification suite  (writes verification/*.csv)\n"
        "  5  export a trace of the current run\n"
        "  6  switch integrator (euler / rk2 / rk4)\n"
        "  7  set a signal plan override\n"
        "  8  interpolate detector gaps on a link (Newton divided differences)\n"
        "  9  show site summary\n"
        "  0  quit\n");
}

int menu_mode(const std::string &site) {
    tj::Simulation sim;
    if (!sim.load_network(network_path(site))) {
        std::printf("cannot load %s\n", network_path(site).c_str());
    } else {
        std::printf("loaded %s (%zu links, %zu vehicles injected at t=0)\n",
                    sim.net().site_name.c_str(), sim.net().links.size(),
                    sim.active_vehicles());
    }
    print_help();
    for (;;) {
        std::printf("\ntrackflow> ");
        std::fflush(stdout);
        std::string cmd = read_line();
        if (cmd.empty() && std::cin.eof()) break;
        if (cmd == "0" || cmd == "q" || cmd == "quit") break;
        if (cmd == "1") {
            std::printf("site id (%s): ", site.c_str());
            std::string s = read_line();
            if (!s.empty()) {
                if (sim.load_network(network_path(s)))
                    std::printf("loaded %s\n", sim.net().site_name.c_str());
                else
                    std::printf("no such site: %s\n", network_path(s).c_str());
            }
        } else if (cmd == "2") {
            std::printf("mode [surveyed/manual/scripted]: ");
            std::string m = read_line();
            if (!m.empty()) sim.set_demand_mode(m);
            std::printf("multiplier (1.0): ");
            std::string k = read_line();
            if (!k.empty()) sim.set_demand_multiplier(std::atof(k.c_str()));
            std::printf("hour (9): ");
            std::string h = read_line();
            if (!h.empty()) sim.set_hour(std::atof(h.c_str()));
            std::printf("demand now: mode=%s x%.2f at %.1f h\n", sim.demand_mode().c_str(),
                        sim.demand_multiplier(), sim.hour());
        } else if (cmd == "3") {
            std::printf("simulated seconds (300): ");
            std::string sec = read_line();
            double T = sec.empty() ? 300.0 : std::atof(sec.c_str());
            auto t0 = std::chrono::steady_clock::now();
            sim.advance(T);
            auto t1 = std::chrono::steady_clock::now();
            double wall = std::chrono::duration<double>(t1 - t0).count();
            std::printf("ran %.0f s sim in %.2f s wall (%.1fx real time)\n", T, wall, T / wall);
            std::printf("active %zu  departed %ld  arrived %ld  mean delay %.2f s\n",
                        sim.active_vehicles(), sim.departed(), sim.arrived(), sim.mean_delay());
        } else if (cmd == "4") {
            break;  // handled by main
        } else if (cmd == "5") {
            std::printf("exporting trace to trackflow_trace.jsonl\n");
            sim.record_start();
            sim.advance(5.0);
            sim.record_stop();
            FILE *f = std::fopen("trackflow_trace.jsonl", "w");
            if (f) {
                for (const auto &line : sim.trace()) std::fprintf(f, "%s\n", line.c_str());
                std::fclose(f);
                std::printf("wrote %zu frames\n", sim.trace().size());
            }
        } else if (cmd == "6") {
            std::printf("integrator [euler/rk2/rk4]: ");
            std::string k = read_line();
            if (k == "euler") sim.set_integrator(tj::numerics::Integrator::EULER);
            else if (k == "rk2") sim.set_integrator(tj::numerics::Integrator::RK2);
            else sim.set_integrator(tj::numerics::Integrator::RK4);
            std::printf("integrator = %s\n", tj::numerics::integrator_name(sim.integrator()));
        } else if (cmd == "7") {
            std::printf("signal id: ");
            std::string sid = read_line();
            std::printf("JSON plan ({\"phases\":[{\"name\":\"main\",\"green\":40,\"amber\":4,\"all_red\":3}]}): ");
            std::string js = read_line();
            if (!sid.empty() && !js.empty()) {
                tj::Value v = tj::parse(js);
                sim.set_signal_plan(sid, v);
                std::printf("plan applied to %s\n", sid.c_str());
            }
        } else if (cmd == "8") {
            std::printf("link id: ");
            std::string lid = read_line();
            auto prof = sim.interpolate_link(lid);
            if (!prof.ok) {
                std::printf("not enough detectors: %s\n", prof.note.c_str());
            } else {
                std::printf("%zu samples, rms residual %.3f, %zu extrapolated span(s)\n",
                            prof.points, prof.rms_residual, prof.extrapolated_spans.size());
                for (auto &c : prof.curve)
                    std::printf("  s=%7.1f m  v=%6.1f km/h\n", c.first, c.second);
            }
        } else if (cmd == "9") {
            const auto &n = sim.net();
            std::printf("%s (%s)\n", n.site_name.c_str(), n.site_id.c_str());
            std::printf("  %zu lane-level links, %zu nodes, %zu turns, %zu movements\n",
                        n.links.size(), n.nodes.size(), n.turns.size(), n.demand.size());
            std::printf("  %zu signal controllers, %zu approaches, %zu scenarios\n",
                        n.signals.size(), n.approaches.size(), n.scenarios.size());
            std::printf("  %s\n", n.summary.c_str());
        } else {
            print_help();
        }
    }
    return 0;
}

int stdio_mode(const std::string &site) {
    tj::Simulation sim;
    sim.load_network(network_path(site));

    auto emit = [](const std::string &s) {
        std::fputs(s.c_str(), stdout);
        std::fputc('\n', stdout);
        std::fflush(stdout);
    };

    // announce the loaded site so the client can draw immediately
    {
        std::ostringstream os;
        os << "{\"type\":\"site\"," << sim.site_json().substr(1);
        emit(os.str());
    }
    emit(sim.snapshot_json());

    for (;;) {
        std::string line = read_line();
        if (line.empty()) {
            if (std::cin.eof()) break;
            continue;
        }
        tj::Value cmd = tj::parse(line);
        const std::string op = cmd.str("cmd");
        if (op == "load_site") {
            std::string s = cmd.str("site", site);
            if (sim.load_network(network_path(s))) {
                std::ostringstream os;
                os << "{\"type\":\"site\"," << sim.site_json().substr(1);
                emit(os.str());
                emit(sim.snapshot_json());
            } else {
                emit("{\"type\":\"error\",\"message\":\"cannot load " + s + "\"}");
            }
        } else if (op == "set_demand_mode") {
            sim.set_demand_mode(cmd.str("mode", "surveyed"));
            emit(sim.snapshot_json());
        } else if (op == "set_demand_multiplier") {
            sim.set_demand_multiplier(cmd.num("value", 1.0));
            emit(sim.snapshot_json());
        } else if (op == "set_approach_scale") {
            sim.set_approach_scale(cmd.str("approach"), cmd.num("value", 1.0));
            emit(sim.snapshot_json());
        } else if (op == "set_hour") {
            sim.set_hour(cmd.num("value", 9.0));
            emit(sim.snapshot_json());
        } else if (op == "set_signal_plan") {
            sim.set_signal_plan(cmd.str("signal"), cmd["plan"]);
            emit(sim.snapshot_json());
        } else if (op == "set_speed_multiplier") {
            sim.set_speed_multiplier(cmd.num("value", 1.0));
            emit(sim.snapshot_json());
        } else if (op == "set_speed_limit") {
            sim.set_speed_limit(cmd.str("prefix"), cmd.num("kmph", 40.0));
            emit(sim.snapshot_json());
        } else if (op == "set_integrator") {
            const std::string k = cmd.str("value", "rk4");
            if (k == "euler") sim.set_integrator(tj::numerics::Integrator::EULER);
            else if (k == "rk2") sim.set_integrator(tj::numerics::Integrator::RK2);
            else sim.set_integrator(tj::numerics::Integrator::RK4);
            emit(sim.snapshot_json());
        } else if (op == "pause") {
            sim.set_paused(true);
            emit(sim.snapshot_json());
        } else if (op == "resume") {
            sim.set_paused(false);
            emit(sim.snapshot_json());
        } else if (op == "reset") {
            unsigned seed = unsigned(cmd.num("seed", 12345.0));
            sim.reset(seed);
            emit(sim.snapshot_json());
        } else if (op == "step") {
            int n = int(cmd.num("steps", 1.0));
            for (int i = 0; i < n; ++i) sim.step();
            emit(sim.snapshot_json());
        } else if (op == "tick") {
            // one animation frame: advance by wall-clock-real-equivalent time
            double frame_s = cmd.num("seconds", 0.1);
            if (!sim.paused()) sim.advance(frame_s);
            emit(sim.snapshot_json());
        } else if (op == "run") {
            double T = cmd.num("seconds", 60.0);
            sim.advance(T);
            emit(sim.snapshot_json());
        } else if (op == "detector_window") {
            auto w = sim.take_detector_window();
            std::ostringstream os;
            os << "{\"type\":\"detectors\",\"t\":" << sim.t() << ",\"readings\":[";
            bool first = true;
            for (const auto &r : w) {
                if (!first) os << ",";
                first = false;
                os << "{\"link\":\"" << r.link << "\",\"detector\":\"" << r.detector
                   << "\",\"s_m\":" << r.s_m << ",\"count\":" << r.count
                   << ",\"occupancy\":" << r.occupancy << "}";
            }
            os << "]}";
            emit(os.str());
        } else if (op == "interpolate") {
            auto p = sim.interpolate_link(cmd.str("link"));
            std::ostringstream os;
            os << "{\"type\":\"interpolation\",\"link\":\"" << cmd.str("link")
               << "\",\"ok\":" << (p.ok ? "true" : "false")
               << ",\"points\":" << p.points
               << ",\"rms_residual\":" << p.rms_residual
               << ",\"note\":\"" << p.note << "\",\"samples\":[";
            bool first = true;
            for (auto &s : p.samples) {
                if (!first) os << ",";
                first = false;
                os << "[" << s.first << "," << s.second << "]";
            }
            os << "],\"curve\":[";
            first = true;
            for (auto &s : p.curve) {
                if (!first) os << ",";
                first = false;
                os << "[" << s.first << "," << s.second << "]";
            }
            os << "]}";
            emit(os.str());
        } else if (op == "record_start") {
            sim.record_start();
            emit("{\"type\":\"ack\",\"op\":\"record_start\"}");
        } else if (op == "record_stop") {
            sim.record_stop();
            std::ostringstream os;
            os << "{\"type\":\"trace\",\"frames\":" << sim.recorded_frames() << ",\"data\":[";
            bool first = true;
            for (const auto &f : sim.trace()) {
                if (!first) os << ",";
                first = false;
                os << f;
            }
            os << "]}";
            emit(os.str());
        } else if (op == "scenario") {
            const std::string sid = cmd.str("id");
            for (const auto &sc : sim.net().scenarios) {
                if (sc.id != sid) continue;
                if (sc.hour >= 0.0) sim.set_hour(sc.hour);
                for (auto &kv : sc.multipliers) sim.set_approach_scale(kv.first, kv.second);
                for (auto &kv : sc.demand_scale) sim.set_approach_scale(kv.first, kv.second);
                for (auto &kv : sc.speed_limits) sim.set_speed_limit(kv.first, kv.second);
                if (sc.has_signal_override) {
                    for (auto it = sc.signal_override.o.begin();
                         it != sc.signal_override.o.end(); ++it) {
                        sim.set_signal_plan(it->first, it->second);
                    }
                }
            }
            emit(sim.snapshot_json());
        } else if (op == "quit") {
            break;
        } else {
            emit("{\"type\":\"error\",\"message\":\"unknown command\"}");
        }
    }
    return 0;
}

}  // namespace

int main(int argc, char **argv) {
    bool stdio = false, verify = false;
    double headless = -1.0;
    for (int i = 1; i < argc; ++i) {
        std::string a = argv[i];
        if (a == "--stdio") stdio = true;
        else if (a == "--verify") verify = true;
        else if (a == "--site" && i + 1 < argc) g_site = argv[++i];
        else if (a == "--data" && i + 1 < argc) g_data_dir = argv[++i];
        else if (a == "--run" && i + 1 < argc) headless = std::atof(argv[++i]);
        else if (a == "--help" || a == "-h") { print_help(); return 0; }
    }

    if (verify) return tj::verify::run(network_path(g_site));
    if (headless > 0.0) {
        tj::Simulation sim;
        if (!sim.load_network(network_path(g_site))) {
            std::fprintf(stderr, "cannot load %s\n", network_path(g_site).c_str());
            return 1;
        }
        auto t0 = std::chrono::steady_clock::now();
        sim.advance(headless);
        auto t1 = std::chrono::steady_clock::now();
        double wall = std::chrono::duration<double>(t1 - t0).count();
        std::printf("site        %s\n", sim.net().site_name.c_str());
        std::printf("sim time    %.1f s in %.2f s wall (%.1fx)\n", sim.t(), wall, sim.t() / wall);
        std::printf("active      %zu\n", sim.active_vehicles());
        std::printf("departed    %ld\n", sim.departed());
        std::printf("arrived     %ld\n", sim.arrived());
        std::printf("mean delay  %.2f s\n", sim.mean_delay());
        std::printf("alerts      %zu\n", sim.alerts().size());
        size_t shown = 0;
        for (auto it = sim.alerts().rbegin(); it != sim.alerts().rend() && shown < 5; ++it, ++shown)
            std::printf("  [%s] t=%.3f  %s\n", it->severity.c_str(), it->t, it->message.c_str());
        std::printf("state hash  %.9f\n", sim.state_hash());
        return 0;
    }
    if (stdio) return stdio_mode(g_site);
    return menu_mode(g_site);
}
