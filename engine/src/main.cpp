// Trackflow engine entry point.
//
// Two modes:
//   menu                 - the menu-driven program the lab asks for
//   serve <site.json>    - NDJSON command/stream mode used by the Node bridge
//
// The engine owns simulated time. The bridge asks it to advance by wall-clock
// seconds and receives a snapshot; it never tells the engine what time it is.
#include <algorithm>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>

#include "json.hpp"
#include "sim.hpp"
#include "verify.hpp"

namespace fs = std::filesystem;
using namespace tf;

namespace {

std::vector<std::string> listSites() {
  std::vector<std::string> out;
  for (const char *dir : {"sites", "../sites", "../../sites"}) {
    if (!fs::exists(dir)) continue;
    for (const auto &e : fs::directory_iterator(dir)) {
      if (!e.is_directory()) continue;
      fs::path p = e.path() / "network.json";
      if (fs::exists(p)) out.push_back(p.string());
    }
    if (!out.empty()) break;
  }
  std::sort(out.begin(), out.end());
  return out;
}

std::string readFile(const std::string &path) {
  std::ifstream in(path);
  std::string s((std::istreambuf_iterator<char>(in)), std::istreambuf_iterator<char>());
  return s;
}

int runHeadless(const std::string &sitePath, double seconds, bool trace) {
  Sim sim;
  if (!sim.load(sitePath)) return 1;
  sim.setSeed(20261112u);
  std::printf("engine: %s loaded (%zu links, %zu demand entries)\n", sim.site().name.c_str(),
              sim.site().links.size(), sim.site().demand.size());

  std::ofstream traceOut;
  if (trace) {
    traceOut.open("reports/trace.jsonl");
    fs::create_directories("reports");
  }

  double t = 0.0;
  const double frame = 0.1;
  while (t < seconds) {
    sim.advance(frame);
    t += frame;
    if (trace) traceOut << sim.snapshot() << "\n";
    if ((int)t % 30 == 0 && std::fabs(t - std::round(t)) < 1e-9) {
      std::string s = sim.summaryJson();
      std::printf("  %s\n", s.c_str());
    }
  }
  std::printf("engine: final %s\n", sim.summaryJson().c_str());
  return 0;
}

int runServe(const std::string &sitePath) {
  Sim sim;
  if (!sim.load(sitePath)) {
    std::printf("{\"ready\":false,\"error\":\"cannot load site\"}\n");
    std::fflush(stdout);
    return 1;
  }
  sim.setSeed(20261112u);
  std::printf("{\"ready\":true,\"site\":\"%s\",\"links\":%zu}\n", sim.site().id.c_str(),
              sim.site().links.size());
  std::fflush(stdout);

  std::string line;
  while (std::getline(std::cin, line)) {
    if (line.empty()) continue;
    json::Value cmd;
    try {
      cmd = json::parse(line);
    } catch (...) {
      std::printf("{\"ok\":false,\"error\":\"bad json\"}\n");
      std::fflush(stdout);
      continue;
    }
    const std::string op = cmd["cmd"].asStr();
    if (op == "advance") {
      sim.advance(cmd["dt"].asNum(0.1));
      std::printf("%s\n", sim.snapshot().c_str());
    } else if (op == "set_demand_mode") {
      sim.setDemandMode(cmd["mode"].asStr("surveyed"));
      std::printf("{\"ok\":true}\n");
    } else if (op == "set_multiplier") {
      sim.setMultiplier(cmd["id"].asStr(), cmd["value"].asNum(1.0));
      std::printf("{\"ok\":true}\n");
    } else if (op == "set_speed") {
      sim.setSpeed(cmd["value"].asNum(1.0));
      std::printf("{\"ok\":true}\n");
    } else if (op == "pause") {
      sim.setPaused(true);
      std::printf("{\"ok\":true}\n");
    } else if (op == "resume") {
      sim.setPaused(false);
      std::printf("{\"ok\":true}\n");
    } else if (op == "set_cycle") {
      sim.setSignalCycle(cmd["value"].asNum(120.0));
      std::printf("{\"ok\":true}\n");
    } else if (op == "reset") {
      sim.reset();
      std::printf("{\"ok\":true}\n");
    } else if (op == "snapshot") {
      std::printf("%s\n", sim.snapshot().c_str());
    } else if (op == "summary") {
      std::printf("%s\n", sim.summaryJson().c_str());
    } else if (op == "quit") {
      break;
    } else {
      std::printf("{\"ok\":false,\"error\":\"unknown cmd\"}\n");
    }
    std::fflush(stdout);
  }
  return 0;
}

int menu() {
  std::printf("\n==============================================\n");
  std::printf("  TRACKFLOW — Traffic Flow & Vehicle Dynamics\n");
  std::printf("  Computational Methods Lab (ES-251)\n");
  std::printf("==============================================\n");
  for (;;) {
    auto sites = listSites();
    std::printf("\n  1) List sites (%zu found)\n", sites.size());
    std::printf("  2) Run a site headless\n");
    std::printf("  3) Stream snapshots (NDJSON) for the web app\n");
    std::printf("  4) Verification suite (RK4 / interpolation / root finding)\n");
    std::printf("  5) Export a scenario trace to reports/trace.jsonl\n");
    std::printf("  6) Print the active site definition\n");
    std::printf("  0) Exit\n");
    std::printf("  select> ");
    std::fflush(stdout);

    std::string choice;
    if (!std::getline(std::cin, choice)) break;
    if (choice == "0") break;

    auto pickSite = [&]() -> std::string {
      if (sites.empty()) {
        std::printf("  no sites found under sites/*/network.json\n");
        return "";
      }
      for (size_t i = 0; i < sites.size(); ++i) std::printf("   %zu) %s\n", i + 1, sites[i].c_str());
      std::printf("  site> ");
      std::fflush(stdout);
      std::string s;
      if (!std::getline(std::cin, s)) return "";
      int idx = std::atoi(s.c_str());
      if (idx < 1 || idx > (int)sites.size()) return "";
      return sites[idx - 1];
    };

    if (choice == "1") {
      for (const auto &s : sites) std::printf("  %s\n", s.c_str());
    } else if (choice == "2" || choice == "5") {
      std::string site = pickSite();
      if (site.empty()) continue;
      std::printf("  duration in simulated seconds> ");
      std::fflush(stdout);
      std::string d;
      std::getline(std::cin, d);
      double secs = std::atof(d.c_str());
      if (secs <= 0) secs = 120.0;
      runHeadless(site, secs, choice == "5");
    } else if (choice == "3") {
      std::string site = pickSite();
      if (site.empty()) continue;
      std::printf("  streaming; pipe JSON commands on stdin, Ctrl-D to stop\n");
      return runServe(site);
    } else if (choice == "4") {
      runVerification("reports");
    } else if (choice == "6") {
      std::string site = pickSite();
      if (site.empty()) continue;
      std::printf("%s\n", readFile(site).c_str());
    } else {
      std::printf("  unknown option\n");
    }
  }
  return 0;
}

}  // namespace

int main(int argc, char **argv) {
  std::string mode = argc > 1 ? argv[1] : "menu";
  if (mode == "serve" && argc > 2) return runServe(argv[2]);
  if (mode == "verify") return runVerification(argc > 2 ? argv[2] : "reports");
  if (mode == "run" && argc > 2) {
    double secs = argc > 3 ? std::atof(argv[3]) : 120.0;
    return runHeadless(argv[2], secs, argc > 4);
  }
  if (mode == "list") {
    for (const auto &s : listSites()) std::printf("%s\n", s.c_str());
    return 0;
  }
  if (mode == "--help" || mode == "-h") {
    std::printf("usage: trackflow [menu | list | verify [outdir] | run <site.json> <secs> | serve <site.json>]\n");
    return 0;
  }
  return menu();
}
