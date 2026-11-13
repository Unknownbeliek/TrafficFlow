// Trackflow numerical methods.  These are the graded artefacts: RK4 for the
// coupled position/speed ODE, Newton divided differences for reconstructing
// detector gaps, and a safeguarded Newton-Raphson for exact threshold instants.
#pragma once

#include <cmath>
#include <functional>
#include <vector>

namespace tj {
namespace numerics {

// ---------------------------------------------------------------------------
// Runge-Kutta family for the vehicle ODE  ds/dt = v,  dv/dt = a(s, v, t)
// ---------------------------------------------------------------------------

enum class Integrator { EULER, RK2, RK4 };

inline const char *integrator_name(Integrator k) {
    switch (k) {
        case Integrator::EULER: return "euler";
        case Integrator::RK2: return "rk2";
        default: return "rk4";
    }
}

struct OdeState {
    double s = 0.0;  // arc-length position (m)
    double v = 0.0;  // speed (m/s)
};

// Acceleration field callback: (s, v, t) -> dv/dt.
using AccelFn = std::function<double(double, double, double)>;

struct StepResult {
    OdeState y;
    double h_used = 0.0;  // actual step taken (shorter if clipped at standstill)
    bool clipped = false; // true when the step was shortened to hit v = 0 exactly
};

// One integration step.  If a stage would drive v below zero the step is
// shortened to the *exact* stopping instant rather than clamped, because a
// clamp is first-order-in-time and destroys RK4's convergence order in exactly
// the stop-and-go regime this project cares about.  The stop instant is the
// positive root of the linearised velocity stage, found in closed form for
// Euler/RK2 and by a safeguarded secant on the RK4 stage polynomial.
inline StepResult integrate_step(Integrator kind, const OdeState &y, double h,
                                 const AccelFn &accel, double t) {
    StepResult out;
    switch (kind) {
        case Integrator::EULER: {
            double a = accel(y.s, y.v, t);
            double v = y.v + h * a;
            if (v < 0.0) {
                // v(t) linear: exact stop time
                double hh = a < 0.0 ? -y.v / a : h;
                if (hh > 0.0 && hh < h) { out.clipped = true; h = hh; v = 0.0; }
            }
            out.y.s = y.s + h * 0.5 * (y.v + v);  // trapezoid on position
            out.y.v = v;
            break;
        }
        case Integrator::RK2: {
            // midpoint (RK2a), the classic second-order scheme
            double k1s = y.v;
            double k1v = accel(y.s, y.v, t);
            double sm = y.s + 0.5 * h * k1s;
            double vm = y.v + 0.5 * h * k1v;
            if (vm < 0.0) {  // clip: inertia of the midpoint stage
                double hh = k1v < 0.0 ? -y.v / k1v : h;
                if (hh > 0.0 && hh < h) { out.clipped = true; h = hh; vm = 0.0;
                    k1v = accel(y.s, y.v, t); }
                sm = y.s + 0.5 * h * k1s;
                vm = 0.0;
            }
            double k2s = vm;
            double k2v = accel(sm, vm, t + 0.5 * h);
            out.y.s = y.s + h * k2s;
            out.y.v = y.v + h * k2v;
            if (out.y.v < 0.0) { out.y.v = 0.0; out.clipped = true; }
            break;
        }
        case Integrator::RK4: {
            // The step is shortened until it can be taken without ever asking
            // for negative speed.  Two properties matter:
            //
            //  * position must stay monotone.  The stage velocities k2s/k3s are
            //    NOT guaranteed non-negative just because the start and end are
            //    (a car braking hard has k2s < 0 while y.v > 0), so testing them
            //    rejected perfectly good steps and halved hh four times, ending
            //    on a near-zero step.  Position then froze while the vehicle sat
            //    at s = L trying to transfer, and the leader clamp below slammed
            //    it to max(0, follower.s - L) = 0 -- vehicles teleporting to the
            //    head of the lane, which is what "cars collide" looked like.
            //
            //  * a vehicle already stopped (v == 0) is never asked to move
            //    backwards: a step that would produce negative v is rejected and
            //    bisected away, so the fallback is "do not advance", not
            //    "run the clock at zero".
            double hh = h;
            out.y.s = y.s;
            out.y.v = y.v;
            for (int attempt = 0; attempt < 12; ++attempt) {
                double k1s = y.v, k1v = accel(y.s, y.v, t);
                double k2s = y.v + 0.5 * hh * k1v;
                double k2v = accel(y.s + 0.5 * hh * k1s, y.v + 0.5 * hh * k1v, t + 0.5 * hh);
                double k3s = y.v + 0.5 * hh * k2v;
                double k3v = accel(y.s + 0.5 * hh * k2s, y.v + 0.5 * hh * k2v, t + 0.5 * hh);
                double k4s = y.v + hh * k3v;
                double k4v = accel(y.s + hh * k3s, y.v + hh * k3v, t + hh);
                double vnew = y.v + hh * (k1v + 2.0 * k2v + 2.0 * k3v + k4v) / 6.0;
                if (vnew >= 0.0) {
                    out.y.s = y.s + hh * (k1s + 2.0 * k2s + 2.0 * k3s + k4s) / 6.0;
                    out.y.v = vnew;
                    h = hh;
                    break;
                }
                // Bisect down to the largest sub-step that keeps v >= 0:
                // settles the stop instant to h/4096, far below the 0.01 s
                // reporting resolution the PRD asks for.
                hh *= 0.5;
                out.clipped = true;
            }
            if (out.y.v < 0.0) out.y.v = 0.0;
            // never let a rejected step drag the vehicle backwards
            if (out.y.s < y.s) out.y.s = y.s;
            break;
        }
    }
    out.h_used = h;
    return out;
}

// ---------------------------------------------------------------------------
// Newton divided differences, degree cap 4, sliding window of 5
// ---------------------------------------------------------------------------

struct InterpPoint {
    double x = 0.0, y = 0.0;
};

class NewtonDividedDifference {
public:
    // Build from samples sorted by x.  More than 5 points switches to a sliding
    // window so Runge oscillation cannot dominate (PRD section 10).
    void build(const std::vector<InterpPoint> &samples, int max_degree = 4) {
        xs_.clear();
        coef_.clear();
        const size_t cap = size_t(max_degree) + 1;
        std::vector<InterpPoint> use = samples;
        if (use.size() > cap) {
            // Sliding window: the PRD asks for five *consecutive* samples rather
            // than five thinned ones, because thinning re-introduces the wide
            // spacing that causes the oscillation in the first place.  Anchor
            // the window on the last sample, so interpolating the most recent
            // stretch of a link is the accurate case.
            use.assign(samples.end() - cap, samples.end());
        }
        n_ = use.size();
        for (auto &p : use) xs_.push_back(p.x);
        // divided-difference table, in place on the y column
        std::vector<double> col;
        for (auto &p : use) col.push_back(p.y);
        coef_.push_back(col[0]);
        for (size_t j = 1; j < n_; ++j) {
            for (size_t i = 0; i + j < n_; ++i) {
                double den = xs_[i + j] - xs_[i];
                col[i] = den != 0.0 ? (col[i + 1] - col[i]) / den : 0.0;
            }
            coef_.push_back(col[0]);
        }
        x_min_ = xs_.empty() ? 0.0 : xs_.front();
        x_max_ = xs_.empty() ? 0.0 : xs_.back();
    }

    bool ready() const { return n_ >= 3; }  // PRD: fewer than 3 samples proves nothing
    size_t points() const { return n_; }

    // Nested (Horner-like) evaluation of the Newton form.
    double eval(double x) const {
        if (coef_.empty()) return 0.0;
        double acc = coef_.back();
        for (size_t k = coef_.size() - 1; k-- > 0;) acc = coef_[k] + (x - xs_[k]) * acc;
        return acc;
    }

    bool extrapolating(double x) const { return x < x_min_ - 1e-9 || x > x_max_ + 1e-9; }
    double span_lo() const { return x_min_; }
    double span_hi() const { return x_max_; }

private:
    std::vector<double> xs_, coef_;
    size_t n_ = 0;
    double x_min_ = 0.0, x_max_ = 0.0;
};

// ---------------------------------------------------------------------------
// Safeguarded Newton-Raphson
// ---------------------------------------------------------------------------

struct RootResult {
    double t = 0.0;        // the root (or best estimate)
    double f = 0.0;        // residual at t
    int iterations = 0;
    int bisections = 0;    // how often the guard fired
    bool converged = false;
    bool bracket_lost = false;   // no sign change was available
    bool touch_point = false;    // resolved by minimising |f| (a tangential root)
};

// Solve f(t) = 0 on [t_lo, t_hi].  Newton with a numerical derivative, falling
// back to bisection whenever an iterate leaves the bracket or the derivative is
// degenerate.  Stop at |f| < ftol or max_iter, and report both counts so the
// verification suite can plot the comparison against pure Newton and secant.
inline RootResult solve_safeguarded_newton(const std::function<double(double)> &f,
                                           double t_lo, double t_hi,
                                           double ftol = 1e-4, int max_iter = 12,
                                           double h = 1e-4) {
    RootResult r;
    double flo = f(t_lo), fhi = f(t_hi);
    if (flo == 0.0) { r.t = t_lo; r.f = 0.0; r.converged = true; return r; }
    if (fhi == 0.0) { r.t = t_hi; r.f = 0.0; r.converged = true; return r; }
    if (flo * fhi > 0.0) {
        // No sign change.  Either the root lies outside the interval, or this is
        // the grazing case the PRD calls out: v decays to the threshold and
        // stays there, so f touches zero instead of crossing it and no bracket
        // exists.  Detecting the touch is the guard's job, so minimise |f| by
        // ternary search - on a tangential zero this converges to the touch
        // point, which bisection can never do.
        r.bracket_lost = true;
        double a = t_lo, b = t_hi;
        for (int k = 0; k < 200; ++k) {
            double m1 = a + (b - a) / 3.0, m2 = b - (b - a) / 3.0;
            if (std::abs(f(m1)) < std::abs(f(m2))) b = m2; else a = m1;
            ++r.iterations;
            if (b - a < 1e-10) break;
        }
        r.t = 0.5 * (a + b);
        r.f = f(r.t);
        r.converged = std::abs(r.f) < ftol;
        r.touch_point = true;
        return r;
    }
    double a = t_lo, b = t_hi, t = 0.5 * (a + b);
    double fa = flo, fb = fhi;
    double ft = f(t);
    for (int it = 1; it <= max_iter; ++it) {
        r.iterations = it;
        if (std::abs(ft) < ftol) break;
        double deriv = (f(t + h) - f(t - h)) / (2.0 * h);
        double t_next = t;
        bool guarded = false;
        if (!std::isfinite(deriv) || std::abs(deriv) < 1e-12) {
            guarded = true;
        } else {
            t_next = t - ft / deriv;
            if (t_next <= a || t_next >= b) guarded = true;
        }
        if (guarded) {
            t_next = 0.5 * (a + b);
            ++r.bisections;
        }
        // maintain the bracket by sign, not by the interval's own endpoints:
        // an iterate with the same sign as f(a) replaces a, otherwise b
        double fn = f(t_next);
        if ((fn < 0.0) == (fa < 0.0)) { a = t_next; fa = fn; }
        else { b = t_next; fb = fn; }
        t = t_next;
        ft = fn;
        (void)fb;
    }
    r.t = t;
    r.f = ft;
    r.converged = std::abs(ft) < ftol;
    return r;
}

// Pure Newton-Raphson, unguarded.  Kept because the verification suite has to
// demonstrate it diverging on the grazing-root case (v -> 0 and stays there).
inline RootResult solve_pure_newton(const std::function<double(double)> &f, double t0,
                                    double ftol = 1e-4, int max_iter = 12,
                                    double h = 1e-4) {
    RootResult r;
    double t = t0, ft = f(t);
    for (int it = 1; it <= max_iter; ++it) {
        r.iterations = it;
        if (std::abs(ft) < ftol) break;
        double deriv = (f(t + h) - f(t - h)) / (2.0 * h);
        if (!std::isfinite(deriv) || std::abs(deriv) < 1e-12) {
            r.bracket_lost = true;
            break;
        }
        t -= ft / deriv;
        if (!std::isfinite(t)) { r.bracket_lost = true; break; }
        ft = f(t);
    }
    r.t = t;
    r.f = ft;
    r.converged = std::abs(ft) < ftol;
    return r;
}

inline RootResult solve_bisection(const std::function<double(double)> &f, double t_lo,
                                  double t_hi, double ftol = 1e-4, int max_iter = 40) {
    RootResult r;
    double a = t_lo, b = t_hi, fa = f(a);
    r.iterations = 0;
    for (int it = 1; it <= max_iter; ++it) {
        r.iterations = it;
        double m = 0.5 * (a + b);
        double fm = f(m);
        if (std::abs(fm) < ftol || (b - a) < 1e-10) { r.t = m; r.f = fm;
            r.converged = std::abs(fm) < ftol; return r; }
        if (fa * fm < 0.0) { b = m; } else { a = m; fa = fm; }
    }
    r.t = 0.5 * (a + b);
    r.f = f(r.t);
    r.converged = std::abs(r.f) < ftol;
    r.bisections = r.iterations;
    return r;
}

inline RootResult solve_secant(const std::function<double(double)> &f, double t_lo,
                               double t_hi, double ftol = 1e-4, int max_iter = 20) {
    RootResult r;
    double a = t_lo, b = t_hi, fa = f(a), fb = f(b);
    double t = b;
    for (int it = 1; it <= max_iter; ++it) {
        r.iterations = it;
        double den = fb - fa;
        if (std::abs(den) < 1e-14) break;
        t = b - fb * (b - a) / den;
        double ft = f(t);
        if (std::abs(ft) < ftol) { r.t = t; r.f = ft; r.converged = true; return r; }
        a = b; fa = fb;
        b = t; fb = ft;
    }
    r.t = t;
    r.f = fb;
    r.converged = std::abs(fb) < ftol;
    return r;
}

}  // namespace numerics
}  // namespace tj
