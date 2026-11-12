# Algorithms and flowcharts

Required by the ES-251 submission structure (item 5). Each method has the flowchart a
reviewer can follow without reading the source, plus the file it lives in.

---

## 1. Main simulation loop (RK4 + signals + IDM)

`engine/src/sim.cpp :: Sim::advance` → `Sim::step`

```
        ┌───────────────────────────┐
        │  advance(wallSeconds)     │
        └─────────────┬─────────────┘
                      │  sim_time += wallSeconds × speed_multiplier
                      ▼
        ┌───────────────────────────┐
        │  accumulator ≥ dt (0.05 s)│──no──► return (idle frame)
        └─────────────┬─────────────┘
                      │ yes
                      ▼
   ┌──────────────────────────────────────┐
   │ 1. advance simulation clock          │
   │ 2. spawn Poisson arrivals per approach│
   └──────────────┬───────────────────────┘
                  ▼
   for each link → for each lane → for each vehicle (front to back):
   ┌──────────────────────────────────────────────────────────────┐
   │ gap, leader speed  = leader in lane (or ∞ at the link end)   │
   │ mayCross(signal)   = G  or  (A and cannot stop comfortably)  │
   │ if !mayCross: the stop line becomes a stationary obstacle    │
   │                                                              │
   │ RK4 on (s, v):                                               │
   │   k1 = f(s, v)              f = ( v , a_IDM + a_curve + a_stopline ) │
   │   k2 = f(s + h k1/2, v + h k1/2)                             │
   │   k3 = f(s + h k2/2, v + h k2/2)                             │
   │   k4 = f(s + h k3,   v + h k3)                               │
   │   s,v ← s,v + h/6 (k1 + 2k2 + 2k3 + k4)                      │
   │                                                              │
   │ guards: v ≥ 0, v ≤ v_max, s ≤ leader − length − 0.3 m        │
   └──────────────┬───────────────────────────────────────────────┘
                  ▼
   ┌──────────────────────────────────────┐
   │ transfers at link ends (turn weights)│
   │ alert checks (root finding)          │
   └──────────────┬───────────────────────┘
                  ▼
              loop while accumulator ≥ dt
```

Why the leader is frozen for one step: over 50 ms the leader moves centimetres, so treating
it as fixed during the four RK4 stages changes the result by less than the integration error
and keeps the ODE continuous — which is what preserves the fourth-order behaviour.

---

## 2. Newton divided differences (detector gap reconstruction)

`engine/src/solvers.hpp :: DividedDifferenceTable`

```
   samples (x_i, y_i), i = 0..n-1
            │
            ▼
   ┌────────────────────────────────────────┐
   │ build table:                           │
   │   f[x_i] = y_i                         │
   │   f[x_i..x_{i+j}] =                    │
   │     (f[x_{i+1}..x_{i+j}] − f[x_i..x_{i+j-1}]) / (x_{i+j} − x_i) │
   └───────────────┬────────────────────────┘
                   ▼
        n ≤ 5 ? ──yes──► full degree (n−1), Horner evaluation
                   │
                   no
                   ▼
   sliding window of 5 nearest nodes around the query point
   (degree cap 4 → Runge oscillation cannot dominate)
                   │
                   ▼
   ┌────────────────────────────────────────┐
   │ flag if query is outside [x_0, x_n−1]  │ → drawn dashed as extrapolation
   │ report residual at withheld samples    │ → validation, not decoration
   └────────────────────────────────────────┘
```

Minimum of **three** checkpoints: with two the method is linear interpolation and proves
nothing.

---

## 3. Safeguarded Newton–Raphson (threshold crossing)

`engine/src/solvers.hpp :: newtonSafeguarded`, called from `Sim::updateAlerts`

```
   given f(t), f'(t), bracket [lo, hi] with f(lo)·f(hi) < 0
            │
            ▼
   t ← endpoint with the smaller |f|
            │
            ▼
   ┌─────────────────────────┐
   │ |f(t)| < tol ?          │──yes──► converged (report iterations)
   └───────────┬─────────────┘
               │ no
               ▼
   shrink bracket using sign of f(t)
               │
               ▼
   candidate = t − f(t)/f'(t)
               │
        inside bracket and f' usable ? ──no──► candidate = (lo+hi)/2   (fallback = true)
               │ yes
               ▼
            t ← candidate ; iterations++ ; repeat (max 12)
```

In the engine the function is not the raw speed but a **divided-difference interpolant**
through the last three integration samples, so the reported crossing time sits between
steps rather than on one.

---

## 4. Alert pipeline

```
 every step: push (t, v) into the vehicle's 3-sample history
            │
            ├─ v crosses the posted limit   → root of v(t) − v_limit   → "overspeed"
            ├─ v < 0.3 m/s sustained 3 s    → root of v(t) − 0.3       → "standstill"
            └─ link density > threshold     → root of k(t) − k_thresh  → "density"
                        │
                        ▼
        RootResult { time, iterations, residual, fallback }
                        │
                        ▼
        snapshot.events[] → dashboard alert log + radar pulse
        (timestamp to 0.01 s of simulated time, 2 s hysteresis, one alert per event)
```

A standstill root is **tangential**, so `v = 0` has no sign change. That is why the engine
solves the *sustained 0.3 m/s crossing* instead — a genuine sign change the guarded solver
can bracket. `engine/trackflow verify` prints the failure experiment that motivates this.

---

## 5. 1-D → 2-D mapping (frontend, not numerics but worth documenting)

`web/src/lib/geometry.js`

```
network.json link.points (image pixels)
        │
        ▼
cumulative pixel length per vertex          (built once at load)
        │
        ▼
s_metres / length_m  →  fraction  →  target pixel distance
        │
        ▼
segment search → linear interpolation → (x, y) + heading
        │
        ▼
lane offset along the normal: (lane − (lanes−1)/2) × lane_width_m / metres_per_pixel
        │
        ▼
<g transform="translate(x,y) rotate(heading)"> <rect length=len/mpp /> </g>
```

`getPointAtLength` is used nowhere in the animation loop: it is a layout query and would
dominate the frame budget at a few hundred vehicles.
