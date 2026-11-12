// Trackflow geometry: polylines with arc-length parameterisation.
//
// The renderer and the engine sample the same polylines, so this has to be a
// faithful arc-length parameterisation of the primitives the network compiler
// emits (lines and circular arcs).  Positions are metres in the local screen
// frame: x east, y south, bearings clockwise from east.
#pragma once

#include <cmath>
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

// One geometric primitive from network.json: either a straight segment or a
// circular arc.  `a0`/`a1` are degrees, `c` is the arc centre.
struct Prim {
    enum Kind { LINE, ARC } kind = LINE;
    Vec2 a, b;          // LINE endpoints
    Vec2 c;             // ARC centre
    double r = 0.0;     // ARC radius
    double a0 = 0.0, a1 = 0.0;  // ARC start/end angle (degrees)
};

// A lane centreline: primitives plus cumulative arc-length breakpoints so that
// sampling is O(log n) rather than a walk from the start.
class Polyline {
public:
    void add(const Prim &p) {
        prims_.push_back(p);
        double len = prim_length(p);
        cum_.push_back(len);
        total_ += len;
    }
    bool empty() const { return prims_.empty(); }
    double length() const { return total_; }

    // Point and unit tangent at arc length s (clamped to the ends).
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
        double base = i == 0 ? 0.0 : cum_[i - 1];
        sample_prim(prims_[i], s - base, pos, dir);
    }
    Vec2 pos_at(double s) const { Vec2 p, d; sample(s, &p, &d); return p; }
    Vec2 dir_at(double s) const { Vec2 p, d; sample(s, &p, &d); return d; }
    void start(Vec2 *pos, Vec2 *dir) const { sample_prim(prims_.front(), 0.0, pos, dir); }
    void end(Vec2 *pos, Vec2 *dir) const {
        sample_prim(prims_.back(), prim_length(prims_.back()), pos, dir);
    }

    // Curvature 1/R at arc length s (0 on straights).  Sign follows the
    // primitive's sweep direction, which is what a_curve needs.
    double curvature(double s) const {
        if (prims_.empty()) return 0.0;
        size_t i = 0;
        while (i < cum_.size() && cum_[i] < s) ++i;
        if (i >= prims_.size()) i = prims_.size() - 1;
        const Prim &p = prims_[i];
        if (p.kind != Prim::ARC || p.r < 1e-6) return 0.0;
        double sweep = p.a1 - p.a0;
        return (sweep >= 0.0 ? 1.0 : -1.0) / p.r;
    }

    const std::vector<Prim> &prims() const { return prims_; }

private:
    static double prim_length(const Prim &p) {
        if (p.kind == Prim::LINE) return dist(p.a, p.b);
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
