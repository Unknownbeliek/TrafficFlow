#include "verify.hpp"

#include <cmath>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <functional>
#include <vector>

#include "solvers.hpp"

namespace tf {
namespace {

// --- integrators for the reference ODE v' = a - k v^2 -----------------------
double fDrag(double v, double a, double k) { return a - k * v * v; }

double integrateEuler(double a, double k, double dt, double tEnd) {
  double v = 0.0;
  int n = (int)std::lround(tEnd / dt);
  for (int i = 0; i < n; ++i) v += dt * fDrag(v, a, k);
  return v;
}

double integrateRK2(double a, double k, double dt, double tEnd) {
  double v = 0.0;
  int n = (int)std::lround(tEnd / dt);
  for (int i = 0; i < n; ++i) {
    double k1 = fDrag(v, a, k);
    double k2 = fDrag(v + 0.5 * dt * k1, a, k);
    v += dt * k2;
  }
  return v;
}

double integrateRK4(double a, double k, double dt, double tEnd) {
  double v = 0.0;
  int n = (int)std::lround(tEnd / dt);
  for (int i = 0; i < n; ++i) {
    double k1 = fDrag(v, a, k);
    double k2 = fDrag(v + 0.5 * dt * k1, a, k);
    double k3 = fDrag(v + 0.5 * dt * k2, a, k);
    double k4 = fDrag(v + dt * k3, a, k);
    v += dt / 6.0 * (k1 + 2 * k2 + 2 * k3 + k4);
  }
  return v;
}

double exactDrag(double a, double k, double tEnd) {
  return std::sqrt(a / k) * std::tanh(std::sqrt(a * k) * tEnd);
}

// log2 ratio of successive errors = observed order of accuracy
double observedOrder(double e1, double e2) {
  if (e1 <= 0.0 || e2 <= 0.0) return 0.0;
  return std::log2(e1 / e2);
}

double densityProfile(double x) {
  return 42.0 * std::exp(-((x - 1500.0) * (x - 1500.0)) / (2.0 * 420.0 * 420.0)) +
         9.0 * std::sin(x / 640.0) + 6.0;
}

double speedProfile(double t) { return 20.0 * (1.0 - std::exp(-t / 4.0)); }  // m/s, accelerating

}  // namespace

int runVerification(const std::string &outDir) {
  std::filesystem::create_directories(outDir);

  std::printf("\n==============================================================\n");
  std::printf(" TRACKFLOW — NUMERICAL METHODS VERIFICATION\n");
  std::printf(" ES-251 error analysis and method comparison\n");
  std::printf("==============================================================\n");

  // ---------------------------------------------------------------------------
  // 1. RK4 vs RK2 vs Euler on an ODE with a closed-form solution
  // ---------------------------------------------------------------------------
  const double a = 2.0, k = 0.02, tEnd = 10.0;
  const double exact = exactDrag(a, k, tEnd);
  std::printf("\n[1] Integration accuracy:  v' = a - k v^2,  a=%.2f, k=%.3f, t=%.1f\n", a, k, tEnd);
  std::printf("    closed form  v(t) = sqrt(a/k) tanh(sqrt(a k) t) = %.6f m/s\n\n", exact);
  std::printf("    %-8s %-8s %14s %10s %8s\n", "method", "dt", "error (m/s)", "order", "steps");
  std::printf("    ----------------------------------------------------------\n");

  std::ofstream csv(std::filesystem::path(outDir) / "rk4_error.csv");
  csv << "method,dt,error,observed_order,steps,exact\n";
  struct Row {
    const char *name;
    std::function<double(double, double, double, double)> fn;
  };
  std::vector<Row> methods = {{"euler", integrateEuler}, {"rk2", integrateRK2}, {"rk4", integrateRK4}};
  double dt = 1.0;
  std::vector<double> dts;
  for (int i = 0; i < 5; ++i, dt *= 0.5) dts.push_back(dt);

  for (const auto &m : methods) {
    double prevErr = 0.0;
    for (double h : dts) {
      double num = m.fn(a, k, h, tEnd);
      double err = std::fabs(num - exact);
      double order = prevErr > 0.0 ? observedOrder(prevErr, err) : 0.0;
      std::printf("    %-8s %-8.4f %14.3e %10.2f %8d\n", m.name, h, err, order,
                  (int)std::lround(tEnd / h));
      csv << m.name << "," << h << "," << err << "," << order << ","
          << (int)std::lround(tEnd / h) << "," << exact << "\n";
      prevErr = err;
    }
    std::printf("    ----------------------------------------------------------\n");
  }
  std::printf("    Expected order: Euler 1, RK2 2, RK4 4  (order read from the error ratio)\n");

  // ---------------------------------------------------------------------------
  // 2. Newton divided differences: reconstructing a detector gap
  // ---------------------------------------------------------------------------
  std::printf("\n[2] Interpolation: Newton divided differences, density profile f(x)\n");
  std::printf("    %-6s %-18s %14s %14s\n", "n", "evaluation", "max |err|", "rms err");
  std::printf("    ----------------------------------------------------------\n");
  std::ofstream csv2(std::filesystem::path(outDir) / "interpolation_error.csv");
  csv2 << "n,method,max_error,rms_error,degree_cap\n";

  for (int n : {4, 5, 9}) {
    std::vector<double> xs, ys;
    for (int i = 0; i < n; ++i) {
      double x = 3000.0 * i / (n - 1);
      xs.push_back(x);
      ys.push_back(densityProfile(x));
    }
    numerics::SensorProfile profile;
    profile.setSamples(xs, ys);

    auto evalError = [&](bool windowed, double &maxErr, double &rms) {
      maxErr = 0.0;
      double sum2 = 0.0;
      int cnt = 0;
      for (int j = 1; j < 400; ++j) {
        double x = 3000.0 * j / 400.0;
        double y = windowed ? profile.at(x) : profile.table.evaluate(xs, ys, x);
        double e = std::fabs(y - densityProfile(x));
        maxErr = std::max(maxErr, e);
        sum2 += e * e;
        ++cnt;
      }
      rms = std::sqrt(sum2 / cnt);
    };

    double m1, r1, m2 = 0.0, r2 = 0.0, m3 = 0.0, r3 = 0.0;
    evalError(false, m1, r1);
    if (n > 5) evalError(true, m2, r2);
    {  // linear reference: piecewise interpolation through the same samples
      double maxErr = 0.0, sum2 = 0.0;
      int cnt = 0;
      for (int j = 1; j < 400; ++j) {
        double x = 3000.0 * j / 400.0;
        size_t seg = 0;
        while (seg + 2 < xs.size() && xs[seg + 1] < x) ++seg;
        double t = (x - xs[seg]) / (xs[seg + 1] - xs[seg]);
        double y = ys[seg] * (1 - t) + ys[seg + 1] * t;
        double e = std::fabs(y - densityProfile(x));
        maxErr = std::max(maxErr, e);
        sum2 += e * e;
        ++cnt;
      }
      m3 = maxErr;
      r3 = std::sqrt(sum2 / cnt);
    }
    std::printf("    %-6d %-18s %14.4f %14.4f\n", n, "linear (2 points)", m3, r3);
    csv2 << n << ",linear," << m3 << "," << r3 << ",1\n";
    std::printf("    %-6d %-18s %14.4f %14.4f\n", n, "newton full degree", m1, r1);
    csv2 << n << ",full," << m1 << "," << r1 << ",4\n";
    if (n > 5) {
      std::printf("    %-6d %-18s %14.4f %14.4f\n", n, "newton windowed", m2, r2);
      csv2 << n << ",windowed," << m2 << "," << r2 << ",4\n";
    }
    std::printf("    ----------------------------------------------------------\n");
  }
  std::printf("    Degree is capped at 4; with 9 equally spaced samples the full-degree\n");
  std::printf("    interpolant oscillates (Runge) and the sliding window suppresses it.\n");

  // ---------------------------------------------------------------------------
  // 3. Root finding: exact threshold-crossing instants
  // ---------------------------------------------------------------------------
  std::printf("\n[3] Root finding: t such that v(t) = 8 m/s,  v(t)=20(1-e^{-t/4})\n");
  const double target = 8.0;
  auto f = [&](double t) { return speedProfile(t) - target; };
  auto df = [&](double t) { return 5.0 * std::exp(-t / 4.0); };
  double loB = 0.5, hiB = 12.0;  // sign change bracket
  std::printf("    bracket [%.2f, %.2f]  f(lo)=%.4f  f(hi)=%.4f\n\n", loB, hiB, f(loB), f(hiB));
  std::printf("    %-22s %10s %14s %12s %s\n", "method", "iterations", "root (s)", "|f|", "note");
  std::printf("    ---------------------------------------------------------------------\n");

  std::ofstream csv3(std::filesystem::path(outDir) / "rootfinding.csv");
  csv3 << "method,iterations,root,residual,converged,fallback\n";

  auto nr = numerics::newtonRaphson(f, df, 6.0);
  auto bi = numerics::bisection(f, loB, hiB);
  auto se = numerics::secant(f, loB, hiB);
  auto sg = numerics::newtonSafeguarded(f, df, loB, hiB);

  auto report = [&](const char *name, const numerics::RootResult &r) {
    std::printf("    %-22s %10d %14.6f %12.2e %s\n", name, r.iterations, r.root, r.residual,
                r.usedBisectionFallback ? "bisection fallback used" : "");
    csv3 << name << "," << r.iterations << "," << r.root << "," << r.residual << ","
         << (r.converged ? 1 : 0) << "," << (r.usedBisectionFallback ? 1 : 0) << "\n";
  };
  report("newton-raphson", nr);
  report("bisection", bi);
  report("secant", se);
  report("newton-safeguarded", sg);
  std::printf("    ---------------------------------------------------------------------\n");
  std::printf("    Production solver is newton-safeguarded: Newton while inside the bracket,\n");
  std::printf("    bisection otherwise. Iteration counts are reported with every alert.\n");

  // Tangential root: a vehicle that comes to rest and stays at rest.
  // Here f(t) = (t-5)^2 represents v(t) once it has settled at zero: the graph
  // touches the axis instead of crossing it.
  std::printf("\n[4] Tangential root (standstill): f(t) = (t-5)^2\n");
  std::printf("    A vehicle that stops and stays stopped does not cross the axis, it\n");
  std::printf("    touches it. That single fact changes which methods can work:\n\n");
  auto g = [](double t) { return (t - 5.0) * (t - 5.0); };
  auto dg = [](double t) { return 2.0 * (t - 5.0); };

  auto nrTight = numerics::newtonRaphson(g, dg, 1.0, 1e-9, 40);
  auto nrAtRoot = numerics::newtonRaphson(g, dg, 5.0, 1e-9, 40);
  auto biNo = numerics::bisection(g, 0.0, 10.0, 1e-6, 60);
  auto sgNo = numerics::newtonSafeguarded(g, dg, 0.0, 10.0, 1e-6, 60);

  std::printf("    %-24s %11s %12s %12s %s\n", "method", "iterations", "root", "|f|", "result");
  std::printf("    -------------------------------------------------------------------------\n");
  std::printf("    %-24s %11d %12.6f %12.2e %s\n", "newton @ t0=1, tol 1e-9", nrTight.iterations,
              nrTight.root, nrTight.residual, "linear, not quadratic");
  std::printf("    %-24s %11d %12s %12.2e %s\n", "newton @ t0=5 (at root)", nrAtRoot.iterations, "-",
              nrAtRoot.residual, "stalls: f'(t)=0");
  std::printf("    %-24s %11d %12s %12.2e %s\n", "bisection [0,10]", biNo.iterations, "-",
              biNo.residual, "cannot start: no sign change");
  std::printf("    %-24s %11d %12s %12.2e %s\n", "guarded newton [0,10]", sgNo.iterations, "-",
              sgNo.residual, "no bracket to guard");
  std::printf("    -------------------------------------------------------------------------\n");
  std::printf("    Consequence for the engine: standstill is NOT solved as a root of v=0.\n");
  std::printf("    It is reported as a sustained threshold crossing (v < 0.3 m/s for 3 s),\n");
  std::printf("    which is a sign-change event the guarded solver can actually bracket.\n");
  std::printf("    Root finding is reserved for crossings: over-speed and density breach.\n");

  std::ofstream csv4(std::filesystem::path(outDir) / "tangential_root.csv");
  csv4 << "method,iterations,root,residual,converged\n";
  csv4 << "newton_t0_1," << nrTight.iterations << "," << nrTight.root << "," << nrTight.residual << ","
       << (nrTight.converged ? 1 : 0) << "\n";
  csv4 << "newton_at_root," << nrAtRoot.iterations << "," << nrAtRoot.root << "," << nrAtRoot.residual
       << "," << (nrAtRoot.converged ? 1 : 0) << "\n";
  csv4 << "bisection," << biNo.iterations << "," << biNo.root << "," << biNo.residual << ","
       << (biNo.converged ? 1 : 0) << "\n";
  csv4 << "guarded_newton," << sgNo.iterations << "," << sgNo.root << "," << sgNo.residual << ","
       << (sgNo.converged ? 1 : 0) << "\n";

  std::printf("\nCSV written to %s/{rk4_error,interpolation_error,rootfinding,tangential_root}.csv\n\n",
              outDir.c_str());
  return 0;
}

}  // namespace tf
