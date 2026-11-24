// Trackflow geometry: polylines with arc-length parameterisation.
//
// The renderer and the engine sample the same polylines, so this has to be a
// faithful arc-length parameterisation of the primitives the network compiler
// emits (lines, circular arcs, and cubic Béziers). Positions are metres in the
// local screen frame: x east, y south, bearings clockwise from east.
#pragma once

#define _USE_MATH_DEFINES
#include <cmath>
#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif
#include <algorithm>
#include <string>
#include <vector>

namespace tj {

struct Vec2 {
    double x = 0.0, y = 0.0;
    Vec2() = default;
    Vec2(double x_, double y_) : x(x_), y(y_) {}
    Vec2 operator+(const Vec2 &o) const { return {x + o.x, y + o.y}; }
    Vec2 operator-(const Vec2 &o) const { return {x - o.x, y - o.y}; }
    Vec2 operator*(double k) const { return {x * k, y * k}; }
};

inline double norm(const Vec2 &v) { return std::sqrt(v.x * v.x + v.y * v.y); }
inline Vec2 unit(const Vec2 &v) {
    double n = norm(v);
    return n > 1e-12 ? Vec2(v.x / n, v.y / n) : Vec2(1.0, 0.0);
}
inline double dist(const Vec2 &a, const Vec2 &b) { return norm(b - a); }
inline double dot(const Vec2 &a, const Vec2 &b) { return a.x * b.x + a.y * b.y; }
inline double cross(const Vec2 &a, const Vec2 &b) { return a.x * b.y - a.y * b.x; }
inline double angle_of(const Vec2 &v) { return std::atan2(v.y, v.x); }

// Perpendicular unit vector pointing to the RIGHT of the direction of travel
// (frame: x east, y south; dir=(1,0) -> normal=(0,1) south).
inline Vec2 right_normal(const Vec2 &dir) {
    Vec2 u = unit(dir);
    return Vec2(-u.y, u.x);
}

// Geometric primitive: straight line, circular arc, or cubic Bézier curve.
struct Prim {
    enum Kind { LINE, ARC, BEZIER } kind = LINE;
    Vec2 a, b;                  // LINE endpoints / BEZIER start (a) and end (b)
    Vec2 c;                     // ARC centre
    double r = 0.0;             // ARC radius
    double a0 = 0.0, a1 = 0.0;  // ARC start/end angle (degrees)
    Vec2 p1, p2;                // BEZIER control points P1, P2
};

// Polyline: composite curve with cumulative arc-length breakpoints for O(log n) sampling.
class Polyline {
public:
    void add(const Prim &p) {
        prims_.push_back(p);
        double len = prim_length(p);
        total_ += len;
        cum_.push_back(total_);
    }
    bool empty() const { return prims_.empty(); }
    double length() const { return total_; }

    // Point and unit tangent at arc length s (clamped to ends).
    void sample(double s, Vec2 *pos, Vec2 *dir) const {
        if (prims_.empty()) {
            if (pos) *pos = Vec2();
            if (dir) *dir = Vec2(1.0, 0.0);
            return;
        }
        if (s <= 0.0) { start(pos, dir); return; }
        if (s >= total_) { end(pos, dir); return; }
        size_t i = 0;
        while (i < cum_.size() && cum_[i] < s) ++i;
        if (i >= prims_.size()) i = prims_.size() - 1;
        double base = i == 0 ? 0.0 : cum_[i - 1];
        sample_prim(prims_[i], s - base, pos, dir);
    }

    // Point on a specific lane at arc length s.
    // lane 0 is leftmost, lanes-1 is rightmost.
    Vec2 sample_lane(double s, int lane, int total_lanes, double lane_width, Vec2 *dir_out = nullptr) const {
        Vec2 p, d;
        sample(s, &p, &d);
        if (dir_out) *dir_out = d;
        if (total_lanes <= 0) return p;
        double offset_m = (lane - (total_lanes - 1) * 0.5) * lane_width;
        Vec2 n = right_normal(d);
        return p + n * offset_m;
    }

    Vec2 pos_at(double s) const { Vec2 p, d; sample(s, &p, &d); return p; }
    Vec2 dir_at(double s) const { Vec2 p, d; sample(s, &p, &d); return d; }
    void start(Vec2 *pos, Vec2 *dir) const { sample_prim(prims_.front(), 0.0, pos, dir); }
    void end(Vec2 *pos, Vec2 *dir) const {
        sample_prim(prims_.back(), prim_length(prims_.back()), pos, dir);
    }

    // Curvature 1/R at arc length s.
    double curvature(double s) const {
        if (prims_.empty()) return 0.0;
        size_t i = 0;
        while (i < cum_.size() && cum_[i] < s) ++i;
        if (i >= prims_.size()) i = prims_.size() - 1;
        const Prim &p = prims_[i];
        if (p.kind == Prim::ARC) {
            if (p.r < 1e-6) return 0.0;
            double sweep = p.a1 - p.a0;
            return (sweep >= 0.0 ? 1.0 : -1.0) / p.r;
        } else if (p.kind == Prim::BEZIER) {
            double base = i == 0 ? 0.0 : cum_[i - 1];
            double seg_s = std::max(0.0, s - base);
            double t = bezier_t_at_s(p, seg_s);
            Vec2 d1 = bezier_deriv(p, t);
            Vec2 d2 = bezier_second_deriv(p, t);
            double spd = norm(d1);
            if (spd < 1e-6) return 0.0;
            return (d1.x * d2.y - d1.y * d2.x) / (spd * spd * spd);
        }
        return 0.0;
    }

    const std::vector<Prim> &prims() const { return prims_; }

private:
    // --- Bézier helper math ---
    static Vec2 bezier_eval(const Prim &p, double t) {
        double u = 1.0 - t;
        double tt = t * t, uu = u * u;
        double uuu = uu * u, ttt = tt * t;
        return p.a * uuu + p.p1 * (3.0 * uu * t) + p.p2 * (3.0 * u * tt) + p.b * ttt;
    }

    static Vec2 bezier_deriv(const Prim &p, double t) {
        double u = 1.0 - t;
        return (p.p1 - p.a) * (3.0 * u * u) + (p.p2 - p.p1) * (6.0 * u * t) + (p.b - p.p2) * (3.0 * t * t);
    }

    static Vec2 bezier_second_deriv(const Prim &p, double t) {
        double u = 1.0 - t;
        return (p.p2 - p.p1 * 2.0 + p.a) * (6.0 * u) + (p.b - p.p2 * 2.0 + p.p1) * (6.0 * t);
    }

    // Arc length of a Bézier from 0 to t via 16-step Simpson quadrature
    static double bezier_arc_length(const Prim &p, double t_end) {
        if (t_end <= 0.0) return 0.0;
        t_end = std::min(1.0, t_end);
        constexpr int N = 16;
        double h = t_end / N;
        double sum = norm(bezier_deriv(p, 0.0)) + norm(bezier_deriv(p, t_end));
        for (int i = 1; i < N; ++i) {
            double t = i * h;
            double w = (i % 2 == 0) ? 2.0 : 4.0;
            sum += w * norm(bezier_deriv(p, t));
        }
        return sum * (h / 3.0);
    }

    // Invert s -> t for Bézier using Newton-Raphson with bisection fallback
    static double bezier_t_at_s(const Prim &p, double target_s) {
        double total_len = bezier_arc_length(p, 1.0);
        if (target_s <= 0.0 || total_len < 1e-9) return 0.0;
        if (target_s >= total_len) return 1.0;

        double t = target_s / total_len; // Initial linear estimate
        double t_low = 0.0, t_high = 1.0;

        for (int iter = 0; iter < 8; ++iter) {
            double cur_s = bezier_arc_length(p, t);
            double diff = cur_s - target_s;
            if (std::abs(diff) < 1e-4) break;

            if (diff > 0.0) t_high = t;
            else t_low = t;

            double spd = norm(bezier_deriv(p, t));
            if (spd > 1e-6) {
                double step = diff / spd;
                t -= step;
                if (t <= t_low || t >= t_high) {
                    t = 0.5 * (t_low + t_high); // Bisection fallback
                }
            } else {
                t = 0.5 * (t_low + t_high);
            }
        }
        return t < 0.0 ? 0.0 : (t > 1.0 ? 1.0 : t);
    }

    static double prim_length(const Prim &p) {
        if (p.kind == Prim::LINE) return dist(p.a, p.b);
        if (p.kind == Prim::BEZIER) return bezier_arc_length(p, 1.0);
        return std::abs(p.a1 - p.a0) * M_PI / 180.0 * p.r;
    }

    static void sample_prim(const Prim &p, double s, Vec2 *pos, Vec2 *dir) {
        if (p.kind == Prim::LINE) {
            Vec2 d = unit(p.b - p.a);
            double L = dist(p.a, p.b);
            if (pos) *pos = p.a + d * std::min(std::max(s, 0.0), L);
            if (dir) *dir = d;
            return;
        }
        if (p.kind == Prim::BEZIER) {
            double t = bezier_t_at_s(p, s);
            if (pos) *pos = bezier_eval(p, t);
            if (dir) *dir = unit(bezier_deriv(p, t));
            return;
        }
        double sweep = p.a1 - p.a0;
        double total = std::abs(sweep) * M_PI / 180.0 * p.r;
        double frac = total > 1e-9 ? std::min(std::max(s, 0.0), total) / total : 0.0;
        double ang = (p.a0 + sweep * frac) * M_PI / 180.0;
        if (pos) *pos = Vec2(p.c.x + p.r * std::cos(ang), p.c.y + p.r * std::sin(ang));
        if (dir) {
            double sign = sweep >= 0.0 ? 1.0 : -1.0;
            *dir = Vec2(-std::sin(ang) * sign, std::cos(ang) * sign);
        }
    }

    std::vector<Prim> prims_;
    std::vector<double> cum_;
    double total_ = 0.0;
};

}  // namespace tj
