// Trackflow verification suite (PRD section 12).
//
// Everything the report quotes must come from here, never from a screenshot:
//   ./trackflow_engine --verify
// writes verification/*.csv and prints a summary table.
#include <cmath>
#include <cstdio>
#include <fstream>
#include <functional>
#include <sstream>
#include <string>
#include <sys/stat.h>
#include <vector>

#include "json.h"
#include "numerics.h"
#include "sim.h"

namespace tj {
namespace verify {

namespace {

const char *kDir = "verification";

void ensure_dir(const char *path) {
#ifdef _WIN32
    _mkdir(path);
#else
    ::mkdir(path, 0755);
#endif
}

double log10_safe(double x) { return x > 0.0 ? std::log10(x) : -12.0; }

// Least-squares slope of log10(err) against log10(dt).
double fitted_slope(const std::vector<double> &dt, const std::vector<double> &err) {
    std::vector<double> x, y;
    for (size_t i = 0; i < dt.size(); ++i) {
        if (err[i] > 0.0) { x.push_back(std::log10(dt[i])); y.push_back(std::log10(err[i])); }
    }
    if (x.size() < 2) return 0.0;
    double mx = 0, my = 0;
    for (size_t i = 0; i < x.size(); ++i) { mx += x[i]; my += y[i]; }
    mx /= x.size(); my /= y.size();
    double num = 0, den = 0;
    for (size_t i = 0; i < x.size(); ++i) {
        num += (x[i] - mx) * (y[i] - my);
        den += (x[i] - mx) * (x[i] - mx);
    }
    return den > 1e-12 ? num / den : 0.0;
}

// ---------------------------------------------------------------------------
// 1. RK convergence on the drag-only case v' = a - k v^2
//    closed form v(t) = sqrt(a/k) tanh(sqrt(a k) t)
// ---------------------------------------------------------------------------
void convergence() {
    const double a = 2.0, k = 0.02, t_end = 20.0;
    const double exact = std::sqrt(a / k) * std::tanh(std::sqrt(a * k) * t_end);

    std::ofstream csv(std::string(kDir) + "/convergence.csv");
    csv << "integrator,dt,steps,final_v,exact_v,abs_error,log10_dt,log10_error\n";

    struct Row { const char *name; numerics::Integrator kind; };
    const Row rows[] = {{"euler", numerics::Integrator::EULER},
                        {"rk2", numerics::Integrator::RK2},
                        {"rk4", numerics::Integrator::RK4}};
    const std::vector<double> dts = {1.0, 0.5, 0.25, 0.125, 0.0625};

    std::printf("\n== 1. RK convergence: v' = a - k v^2, exact v(%.0f s) = %.9f\n",
                t_end, exact);
    std::printf("   %-7s %8s %10s %14s %14s\n", "method", "dt", "steps", "|error|", "fitted slope");
    for (const Row &r : rows) {
        std::vector<double> errs;
        for (double dt : dts) {
            numerics::OdeState y{0.0, 0.0};
            auto f = [&](double, double v, double) { return a - k * v * v; };
            int n = int(std::llround(t_end / dt));
            double tt = 0.0;
            for (int i = 0; i < n; ++i) {
                auto res = numerics::integrate_step(r.kind, y, dt, f, tt);
                y = res.y;
                tt += res.h_used;
                if (tt >= t_end) break;
            }
            double err = std::abs(y.v - exact);
            errs.push_back(err);
            char line[256];
            std::snprintf(line, sizeof(line), "%s,%.6g,%d,%.9f,%.9f,%.6e,%.6f,%.6f\n",
                          r.name, dt, n, y.v, exact, err, std::log10(dt), log10_safe(err));
            csv << line;
        }
        double slope = fitted_slope(dts, errs);
        std::printf("   %-7s %8s %10s %14.3e %14.3f\n", r.name, "1→1/16", "-", errs.back(), slope);
        char line[160];
        std::snprintf(line, sizeof(line), "%s,,,,,,,slope=%.4f\n", r.name, slope);
        csv << line;
    }
}

// ---------------------------------------------------------------------------
// 2. Newton divided differences on a known density curve
// ---------------------------------------------------------------------------
void interpolation() {
    // k(x) = 40 + 28 sin(pi x / 600) + 9 cos(2 pi x / 300): a plausible density
    // shape along a 600 m link, exact and smooth so residuals are meaningful.
    auto exact = [](double x) {
        // density along a 600 m link: a smooth half-period with a mild
        // shoulder, which is the shape a detector chain actually sees
        return 40.0 + 26.0 * std::sin(M_PI * x / 600.0) + 4.0 * std::sin(2.0 * M_PI * x / 600.0);
    };
    std::ofstream csv(std::string(kDir) + "/interpolation.csv");
    csv << "n_points,window_points,degree,max_error_in_span,rms_in_span,"
           "span_covered_pct,extrapolation_error,note\n";
    std::printf("\n== 2. Newton divided differences on a known density curve\n");
    std::printf("   %-8s %6s %6s %12s %12s %11s\n", "points", "window", "deg", "max err",
                "rms err", "span");
    for (int n : {4, 5, 6, 9}) {
        std::vector<numerics::InterpPoint> pts;
        for (int i = 0; i < n; ++i) {
            double x = 600.0 * i / (n - 1);
            pts.push_back(numerics::InterpPoint{x, exact(x)});
        }
        numerics::NewtonDividedDifference ndd;
        ndd.build(pts, 4);
        // errors are measured inside the fitted span: outside it the value is
        // an extrapolation and is flagged (and dashed in the UI) rather than
        // counted as interpolation error.
        double lo = ndd.span_lo(), hi = ndd.span_hi();
        double mx = 0, s2 = 0;
        int cnt = 0;
        for (int i = 0; i <= 400; ++i) {
            double x = lo + (hi - lo) * i / 400.0;
            double e = std::abs(ndd.eval(x) - exact(x));
            mx = std::max(mx, e);
            s2 += e * e;
            ++cnt;
        }
        double rms = std::sqrt(s2 / cnt);
        double extr = std::abs(ndd.eval(660.0) - exact(660.0));
        const char *note = n > 5 ? "sliding window of 5 consecutive samples" : "";
        char line[256];
        std::snprintf(line, sizeof(line), "%d,%zu,%d,%.6e,%.6e,%.1f,%.6e,%s\n", n, ndd.points(),
                      int(ndd.points()) - 1, mx, rms, 100.0 * (hi - lo) / 600.0, extr, note);
        csv << line;
        std::printf("   %-8d %6zu %6d %12.3e %12.3e %10.0f%%\n", n, ndd.points(),
                    int(ndd.points()) - 1, mx, rms, 100.0 * (hi - lo) / 600.0);
    }
    // report the raw degree-8 fit for contrast (demonstrates Runge oscillation)
    {
        std::vector<numerics::InterpPoint> pts;
        for (int i = 0; i < 9; ++i) {
            double x = 600.0 * i / 8;
            pts.push_back(numerics::InterpPoint{x, exact(x)});
        }
        numerics::NewtonDividedDifference full;
        full.build(pts, 8);
        double mx = 0;
        for (int i = 0; i <= 400; ++i) {
            double x = 600.0 * i / 400.0;
            mx = std::max(mx, std::abs(full.eval(x) - exact(x)));
        }
        csv << "9,9,8," << mx << ",,,,\"degree 8 uncapped (reference only)\n";
        std::printf("   %-8s %6s %6s %12.3e %12s %11s  (uncapped, reference)\n", "9", "9", "8",
                    mx, "-", "100%");
    }
}

// ---------------------------------------------------------------------------
// 3. Root finding: safeguarded Newton vs pure Newton, bisection and secant
// ---------------------------------------------------------------------------
void rootfinding() {
    // (a) a benign root: f(t) = 1.2 t - 7.1 on [0, 10], root 5.9167
    // (b) the grazing case the PRD calls out: a vehicle decays to v = 0 and
    //     stays there, so the threshold function touches rather than crosses
    //     zero.  f(t) = (t - 5)^2 on [0, 10] has a double root at 5.
    struct Case { const char *name; std::function<double(double)> f; double lo, hi, truth; };
    const std::vector<Case> cases = {
        {"linear crossing (overspeed)", [](double t) { return 1.2 * t - 7.1; }, 0.0, 10.0, 7.1 / 1.2},
        // v(t) decays onto the threshold and stays there, so f touches zero
        // without changing sign: f(t) = (t-5)^2/4 on [4.5, 5.5]
        {"grazing root (v→0 standstill)",
         [](double t) { return (t - 5.0) * (t - 5.0) / 4.0; }, 4.5, 5.9, 5.0},
        {"steep crossing (gap-events)", [](double t) { return std::exp(0.7 * t) - 30.0; }, 0.0, 10.0,
         std::log(30.0) / 0.7},
    };

    std::ofstream csv(std::string(kDir) + "/rootfinding.csv");
    csv << "case,method,iterations,bisections,final_abs_f,estimate,truth,abs_error,converged,trace\n";
    std::printf("\n== 3. Root finding on the alert threshold functions\n");
    std::printf("   %-32s %-12s %5s %5s %12s %12s\n", "case", "method", "iter", "bis", "|f|", "|error|");
    for (const Case &c : cases) {
        struct M { const char *name; numerics::RootResult r; };
        std::vector<M> ms;
        ms.push_back({"newton", numerics::solve_pure_newton(c.f, 0.5 * (c.lo + c.hi))});
        ms.push_back({"bisection", numerics::solve_bisection(c.f, c.lo, c.hi)});
        ms.push_back({"secant", numerics::solve_secant(c.f, c.lo, c.hi)});
        ms.push_back({"safeguarded", numerics::solve_safeguarded_newton(c.f, c.lo, c.hi)});
        for (const M &m : ms) {
            double err = std::abs(m.r.t - c.truth);
            char line[512];
            std::snprintf(line, sizeof(line),
                          "\"%s\",%s,%d,%d,%.6e,%.9f,%.9f,%.6e,%s,\"%s\"\n",
                          c.name, m.name, m.r.iterations, m.r.bisections, std::abs(m.r.f),
                          m.r.t, c.truth, err, m.r.converged ? "true" : "false",
                          m.r.touch_point ? "tangential: |f| minimised" :
                          (m.r.bracket_lost ? "bracket lost" : ""));
            csv << line;
            std::printf("   %-32s %-12s %5d %5d %12.3e %12.3e%s\n", c.name, m.name,
                        m.r.iterations, m.r.bisections, std::abs(m.r.f), err,
                        m.r.converged ? "" : "  (not converged)");
        }
    }
}

// ---------------------------------------------------------------------------
// 4. Integrator comparison on a live scenario (the traffic-engineering version)
// ---------------------------------------------------------------------------
void scenario_comparison(const std::string &network_path) {
    std::ofstream csv(std::string(kDir) + "/scenario_comparison.csv");
    csv << "integrator,dt,sim_seconds,active_vehicles,arrived,mean_delay_s,total_delay_s\n";
    std::printf("\n== 4. Scenario comparison: same site, same seed, three integrators\n");
    std::printf("   %-8s %6s %8s %8s %14s %14s\n", "method", "dt", "active", "arrived",
                "mean delay", "total delay");
    for (double dt : {0.05, 0.5}) {
        for (auto kind : {numerics::Integrator::EULER, numerics::Integrator::RK2,
                          numerics::Integrator::RK4}) {
            Simulation sim;
            if (!sim.load_network(network_path)) {
                std::printf("   cannot load %s\n", network_path.c_str());
                return;
            }
            sim.params().dt = dt;
            sim.set_integrator(kind);
            sim.set_hour(9.0);
            sim.advance(360.0);  // six simulated minutes
            double total = sim.mean_delay() * double(sim.active_vehicles());
            std::printf("   %-8s %6.2f %8zu %8ld %14.2f %14.0f\n",
                        numerics::integrator_name(kind), dt, sim.active_vehicles(),
                        sim.arrived(), sim.mean_delay(), total);
            char line[256];
            std::snprintf(line, sizeof(line), "%s,%.3f,%.1f,%zu,%ld,%.4f,%.2f\n",
                          numerics::integrator_name(kind), dt, sim.t(),
                          sim.active_vehicles(), sim.arrived(), sim.mean_delay(), total);
            csv << line;
        }
    }
}

}  // namespace

int run(const std::string &network_path) {
    ensure_dir(kDir);
    std::printf("Trackflow verification suite — writing %s/*.csv\n", kDir);
    convergence();
    interpolation();
    rootfinding();
    if (!network_path.empty()) scenario_comparison(network_path);
    std::printf("\nDone. Every number above is reproducible with "
                "`./trackflow_engine --verify`.\n");
    return 0;
}

}  // namespace verify
}  // namespace tj
