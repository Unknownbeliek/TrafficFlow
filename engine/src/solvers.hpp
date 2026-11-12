// Numerical methods for Trackflow (ES-251 core).
//
//   1. Newton divided differences  - reconstruct missing detector readings
//   2. Safeguarded Newton-Raphson  - exact threshold-crossing instants
//      (with bisection and secant kept alongside for the comparison the lab
//       report requires)
//
// The integration scheme (RK4) lives in sim.hpp because it is coupled to the
// vehicle state; the verification suite in verify.cpp exercises both.
#pragma once
#include <cmath>
#include <functional>
#include <limits>
#include <stdexcept>
#include <vector>

namespace tf {
namespace numerics {

// ---------------------------------------------------------------------------
// 1. Newton divided differences
// ---------------------------------------------------------------------------
struct DividedDifferenceTable {
  std::vector<double> x, y;
  std::vector<std::vector<double>> coef;  // coef[j][i] = f[x_i .. x_{i+j}]
  int degreeCap = 4;                      // >5 equally spaced points: cap degree

  void build(const std::vector<double> &xs, const std::vector<double> &ys) {
    if (xs.size() != ys.size() || xs.size() < 2)
      throw std::runtime_error("divided difference: need >= 2 samples");
    x = xs;
    y = ys;
    const int n = (int)x.size();
    coef.assign(n, std::vector<double>(n, 0.0));
    for (int i = 0; i < n; ++i) coef[0][i] = y[i];
    for (int j = 1; j < n; ++j)
      for (int i = 0; i + j < n; ++i)
        coef[j][i] = (coef[j - 1][i + 1] - coef[j - 1][i]) / (x[i + j] - x[i]);
  }

  // Nested (Horner-like) evaluation of the Newton form.
  double evaluate(const std::vector<double> &xs, const std::vector<double> &ys, double t) const {
    DividedDifferenceTable tmp;
    tmp.build(xs, ys);
    const int n = (int)tmp.x.size();
    const int deg = std::min(n - 1, degreeCap);
    double result = tmp.coef[deg][0];
    for (int k = deg - 1; k >= 0; --k) result = tmp.coef[k][0] + (t - tmp.x[k]) * result;
    return result;
  }

  // Sliding window of the degreeCap+1 nearest nodes, used when more points are
  // available than the degree cap allows. This is the Runge-oscillation guard.
  double evaluateWindowed(double t) const {
    const int n = (int)x.size();
    const int w = std::min(n, degreeCap + 1);
    // locate the window containing t
    int lo = 0;
    while (lo + w < n && x[lo + w - 1] < t) ++lo;
    std::vector<double> xs(x.begin() + lo, x.begin() + lo + w);
    std::vector<double> ys(y.begin() + lo, y.begin() + lo + w);
    DividedDifferenceTable tmp;
    tmp.build(xs, ys);
    const int deg = w - 1;
    double result = tmp.coef[deg][0];
    for (int k = deg - 1; k >= 0; --k) result = tmp.coef[k][0] + (t - xs[k]) * result;
    return result;
  }

  bool extrapolating(double t) const { return t < x.front() || t > x.back(); }
};

// Convenience wrapper: samples given as (position, value) pairs.
struct SensorProfile {
  DividedDifferenceTable table;
  std::vector<double> xs, ys;
  double minSpanFraction = 0.30;  // flag spans wider than this as low confidence

  void setSamples(const std::vector<double> &pos, const std::vector<double> &val) {
    xs = pos;
    ys = val;
    table.degreeCap = 4;
    table.build(xs, ys);
  }
  double at(double t) const { return table.evaluateWindowed(t); }
  bool extrapolating(double t) const { return table.extrapolating(t); }
};

// ---------------------------------------------------------------------------
// 2. Root finding
// ---------------------------------------------------------------------------
struct RootResult {
  double root = 0.0;
  int iterations = 0;
  double residual = 0.0;
  bool converged = false;
  bool usedBisectionFallback = false;
};

using Fn = std::function<double(double)>;

// Plain Newton-Raphson, kept for the failure demonstration in the report.
inline RootResult newtonRaphson(Fn f, Fn df, double t0, double tol = 1e-4, int maxIter = 40) {
  RootResult r;
  double t = t0;
  for (int i = 0; i < maxIter; ++i) {
    double ft = f(t);
    double d = df(t);
    r.iterations = i + 1;
    r.residual = std::fabs(ft);
    if (std::fabs(ft) < tol) { r.converged = true; break; }
    if (!std::isfinite(d) || std::fabs(d) < 1e-12) break;  // stalls on a tangent root
    double next = t - ft / d;
    if (!std::isfinite(next)) break;
    if (std::fabs(next - t) < 1e-12) break;
    t = next;
  }
  r.root = t;
  return r;
}

inline RootResult bisection(Fn f, double lo, double hi, double tol = 1e-4, int maxIter = 60) {
  RootResult r;
  double flo = f(lo), fhi = f(hi);
  if (flo == 0.0) { r.root = lo; r.converged = true; return r; }
  if (fhi == 0.0) { r.root = hi; r.converged = true; return r; }
  if (flo * fhi > 0) return r;  // no bracket
  double mid = lo;
  for (int i = 0; i < maxIter; ++i) {
    mid = 0.5 * (lo + hi);
    double fm = f(mid);
    r.iterations = i + 1;
    r.residual = std::fabs(fm);
    if (std::fabs(fm) < tol || (hi - lo) < 1e-9) { r.converged = true; break; }
    if (flo * fm < 0) { hi = mid; fhi = fm; } else { lo = mid; flo = fm; }
  }
  r.root = mid;
  return r;
}

inline RootResult secant(Fn f, double a, double b, double tol = 1e-4, int maxIter = 60) {
  RootResult r;
  double fa = f(a), fb = f(b);
  for (int i = 0; i < maxIter; ++i) {
    if (std::fabs(fb) < 1e-12) { r.root = b; r.converged = true; break; }
    double denom = (fb - fa);
    if (std::fabs(denom) < 1e-14) break;
    double c = b - fb * (b - a) / denom;
    r.iterations = i + 1;
    a = b; fa = fb;
    b = c; fb = f(b);
    r.residual = std::fabs(fb);
    if (std::fabs(fb) < tol) { r.converged = true; break; }
  }
  r.root = b;
  return r;
}

// Safeguarded Newton-Raphson: Newton step while it stays inside the bracket and
// the derivative is usable, bisection otherwise. This is the production solver
// used for every alert, because traffic functions of time are only piecewise
// smooth and a standstill produces a tangential (zero-derivative) root.
inline RootResult newtonSafeguarded(Fn f, Fn df, double lo, double hi, double tol = 1e-4,
                                    int maxIter = 12) {
  RootResult r;
  double flo = f(lo), fhi = f(hi);
  if (std::fabs(flo) < tol) { r.root = lo; r.converged = true; r.residual = std::fabs(flo); return r; }
  if (std::fabs(fhi) < tol) { r.root = hi; r.converged = true; r.residual = std::fabs(fhi); return r; }
  if (flo * fhi > 0) {
    // No sign change: fall back to the closer endpoint (event may be a tangency).
    r.root = std::fabs(flo) < std::fabs(fhi) ? lo : hi;
    r.residual = std::min(std::fabs(flo), std::fabs(fhi));
    r.converged = r.residual < tol;
    return r;
  }
  // Start from the endpoint with the smaller |f|: for smooth traffic
  // functions this is already close to the crossing, so Newton gets to do the
  // work and bisection stays a safety net rather than the main method.
  double t = std::fabs(flo) < std::fabs(fhi) ? lo : hi;
  for (int i = 0; i < maxIter; ++i) {
    double ft = f(t);
    r.iterations = i + 1;
    r.residual = std::fabs(ft);
    if (std::fabs(ft) < tol) { r.converged = true; break; }
    if (flo * ft < 0) { hi = t; fhi = ft; } else { lo = t; flo = ft; }
    double d = df(t);
    double candidate = std::numeric_limits<double>::quiet_NaN();
    if (std::isfinite(d) && std::fabs(d) > 1e-12) candidate = t - ft / d;
    bool inside = std::isfinite(candidate) && candidate > lo && candidate < hi;
    if (!inside) {
      candidate = 0.5 * (lo + hi);
      r.usedBisectionFallback = true;
    }
    t = candidate;
  }
  r.root = t;
  return r;
}

}  // namespace numerics
}  // namespace tf
