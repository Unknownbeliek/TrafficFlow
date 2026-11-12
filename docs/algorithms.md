# Trackflow — algorithms

Four algorithms carry the numerical content of this project: the RK4 integration
loop, Newton divided differences, the safeguarded Newton-Raphson root finder, and
the motion-matrix traffic assignment that mirrors SIAS. Each section below gives
the pseudocode, a flowchart, the reference test case and the measured result. All
numbers are reproducible with one command:

```bash
cd engine && make && ./trackflow_engine --verify --data ../site-data
```

---

## 1. RK4 integration of the vehicle ODE

### 1.1 The equation

Each vehicle integrates a coupled pair

```
ds/dt = v
dv/dt = a_total(s, v, t)
```

where the acceleration field is the sum of four terms (PRD §8):

```
a_total = a_IDM + a_curve + a_signal + a_limit

a_IDM    = a_max · [ 1 − (v/v0)^4 − (s*/g)² ]
s*       = s0 + v·T + v·Δv / (2·√(a_max·b))
a_curve  = −k_c · max(0, v²/R − a_lat)
a_signal = −b · clamp(v² / (2·d_stop), 0, 1)          (on red, or amber that cannot clear)
a_limit  = −1.2 · (v − v_limit)                        (speed-limit governor)
```

`R` is read from the lane's own polyline at the current arc length, so the
engine and the renderer cannot disagree about a curve.

### 1.2 The integration loop

```
for each step:
    update_signals()                    # discrete: takes effect only at step boundaries
    build_queues()                      # leader / gap for every lane
    inject()                            # Poisson arrivals at source links
    for each active vehicle:
        y = (s, v)
        k1 = f(y)
        k2 = f(y + h/2·k1)
        k3 = f(y + h/2·k2)
        k4 = f(y + h·k3)
        y_next = y + h/6·(k1 + 2k2 + 2k3 + k4)
        if any stage drives v below 0:
            bisect h until the step stays non-negative   # exact stop instant
        s ← y_next.s ,  v ← max(0, y_next.v)
    accumulate_detectors(h)
    transfer()                          # lane / link transfer at step boundaries
    detect_alerts()                     # Newton-Raphson on the threshold functions
    t ← t + h
```

```
        ┌───────────────────────┐
        │   t ← t + dt (0.05 s) │
        └───────────┬───────────┘
                    ▼
        ┌───────────────────────┐
        │  signal phase update  │◄── fixed-time plan + site offset
        └───────────┬───────────┘
                    ▼
        ┌───────────────────────┐
        │  leader / gap lookup  │
        └───────────┬───────────┘
                    ▼
        ┌───────────────────────┐        ┌──────────────────────┐
        │  RK4 stages k1..k4    │───────►│  any stage v < 0 ?   │
        └───────────┬───────────┘        └──────────┬───────────┘
                    │                               │ yes
                    ▼                               ▼
        ┌───────────────────────┐        ┌──────────────────────┐
        │  v, s accept step     │        │  h ← h/2, retry      │
        └───────────┬───────────┘        └──────────┬───────────┘
                    │                               │
                    ▼                               │
        ┌───────────────────────┐◄──────────────────┘
        │  detector accumulation│
        └───────────┬───────────┘
                    ▼
        ┌───────────────────────┐
        │  transfer + alerts    │
        └───────────┬───────────┘
                    └──────► next step
```

### 1.3 Why clipping matters

A naive `v = max(0, v)` clamp is first-order in time and destroys RK4's order in
exactly the stop-and-go regime this project is about. Instead, the step is
shortened to the stopping instant: for Euler and RK2 the stop time is the closed
form root of a linear velocity stage, and for RK4 the step is bisected until all
four stages stay non-negative. Twelve halvings settle the stop instant to
`h/4096 ≈ 12 µs`, far below the 0.01 s reporting resolution.

### 1.4 Verification

Reference problem: drag-only deceleration `v' = a − k·v²`, which has the closed
form `v(t) = √(a/k)·tanh(√(a·k)·t)`. With `a = 2`, `k = 0.02`, `t = 20 s` the
exact speed is 9.993293 m/s.

| method | dt = 1 | dt = 0.0625 | fitted slope |
| --- | --- | --- | --- |
| Euler | 5.59e-3 | 5.40e-4 | **0.85** |
| RK2 | 1.50e-3 | 4.09e-6 | **2.12** |
| RK4 | 1.16e-5 | 1.32e-10 | **4.10** |

Measured slopes match the theoretical 1 / 2 / 4. The RK4 error falls by 10⁵ over
five halvings, four orders better than Euler for four times the work per step.

On a live scenario the difference shows up in the traffic metric rather than the
speed: six simulated minutes at `dt = 0.5 s` gives a total delay of **812
vehicle-seconds under Euler versus 566 under RK4** — Euler's first-order error
fabricates 43 % extra queueing.

---

## 2. Newton divided differences

### 2.1 Purpose

A link has three to five loop detectors, so speed and density are known at a
handful of points. The heatmap and the corridor report need a continuous profile
along the whole link.

### 2.2 Construction

```
for i in 0..n-1:  f[x_i] = y_i
for j in 1..n-1:
    for i in 0..n-1-j:
        f[x_i..x_{i+j}] = ( f[x_{i+1}..x_{i+j}] − f[x_i..x_{i+j-1}] ) / (x_{i+j} − x_i)

evaluate with the nested form:
    acc = f[x_0..x_{n-1}]
    for k = n-2 down to 0:  acc = f[x_0..x_k] + (x − x_k)·acc
```

### 2.3 Guardrails

| guard | rule | implementation |
| --- | --- | --- |
| degree cap | ≤ 4 (five points) | `NewtonDividedDifference::build(..., max_degree = 4)` |
| sliding window | > 5 samples | window of the 5 **most recent consecutive** samples |
| extrapolation | outside the sampled span | `extrapolating(x)` flag, drawn dashed |
| low confidence | any gap > 30 % of link length | `low_confidence_spans` |
| minimum samples | 3 checkpoints | `ready()` is false below 3 |

The window keeps *consecutive* samples rather than thinned ones: thinning
re-introduces the wide spacing that causes the oscillation in the first place.

```
        ┌────────────────────────────┐
        │ detector chain (3–5 loops) │
        └──────────────┬─────────────┘
                       ▼
        ┌────────────────────────────┐      ┌───────────────────────┐
        │ samples sorted by s (m)    │─────►│ n > 5 ? keep 5 newest │
        └──────────────┬─────────────┘      └───────────┬───────────┘
                       ▼                                │
        ┌────────────────────────────┐◄─────────────────┘
        │ divided-difference table   │
        └──────────────┬─────────────┘
                       ▼
        ┌────────────────────────────┐      ┌───────────────────────┐
        │ nested evaluation at s     │─────►│ outside span? dashed  │
        └──────────────┬─────────────┘      │ gap > 30% ? flagged   │
                       ▼                    └───────────────────────┘
        ┌────────────────────────────┐
        │ profile → heatmap / report │
        └────────────────────────────┘
```

### 2.4 Verification

Reference curve: density `k(x) = 40 + 26·sin(πx/600) + 4·sin(2πx/600)` on a
600 m link. Errors are measured **inside the fitted span**; values outside it are
extrapolation and are flagged separately.

| samples | window | degree | max error | rms error | span covered |
| --- | --- | --- | --- | --- | --- |
| 4 | 4 | 3 | 2.14 | 0.90 | 100 % |
| 5 | 5 | 4 | 0.77 | 0.40 | 100 % |
| 6 | 5 | 4 | 0.30 | 0.14 | 80 % |
| 9 | 5 | 4 | **0.012** | 0.004 | 50 % |

The 9-sample case is 25× more accurate than the 5-sample case because the window
lands on the tightest spacing. An uncapped degree-8 fit of the same 9 samples
reaches 0.0048 over the full span but costs stability: adding even 1 % noise to
the samples makes it diverge, which is why the cap exists.

---

## 3. Safeguarded Newton-Raphson

### 3.1 Purpose

An alert must report *when* a threshold was crossed, not which frame noticed it.
Reported times carry three decimals of simulated seconds.

### 3.2 The three root problems

| alert | function | threshold |
| --- | --- | --- |
| over-speed | `f(t) = v(t) − v_limit` | link speed limit |
| standstill | `f(t) = v(t) − 0.05`, sustained 3 s | 0.05 m/s |
| density breach | `f(t) = k(t) − k_threshold` | 85 % of jam density |

### 3.3 Algorithm

```
solve(f, t_lo, t_hi):
    if f(t_lo)·f(t_hi) > 0:
        return minimise |f| by ternary search        # tangential / grazing root
    t ← (t_lo + t_hi)/2 ;  fa ← f(t_lo)
    repeat up to 12 times:
        if |f(t)| < 1e-4: break
        d ← (f(t+h) − f(t−h)) / 2h                    # numerical derivative
        if d degenerate or t − f/d outside [t_lo, t_hi]:
            t ← (t_lo + t_hi)/2 ;  bisections += 1     # the guard fires
        else:
            t ← t − f(t)/d                             # the Newton step
        update the bracket by SIGN, not by the interval endpoints
    return (t, |f|, iterations, bisections)
```

```
        ┌──────────────────────────┐
        │ bracket [t_lo, t_hi]     │
        └────────────┬─────────────┘
                     ▼
        ┌──────────────────────────┐   no   ┌──────────────────────────┐
        │ f(t_lo)·f(t_hi) < 0 ?    │───────►│ minimise |f| (ternary)   │
        └────────────┬─────────────┘        │ tangential root case     │
                     │ yes                  └──────────────────────────┘
                     ▼
        ┌──────────────────────────┐
        │ Newton step t − f/f'      │
        └────────────┬─────────────┘
                     ▼
        ┌──────────────────────────┐   yes  ┌──────────────────────────┐
        │ outside bracket or f'≈0? │───────►│ t ← midpoint (bisect)    │
        └────────────┬─────────────┘        └────────────┬─────────────┘
                     │ no                                │
                     ▼                                   │
        ┌──────────────────────────┐◄───────────────────┘
        │ |f| < 1e-4 ?  → done     │
        └──────────────────────────┘
```

### 3.4 The grazing-root failure mode

A vehicle that decelerates to zero and stays there makes `v(t)` *touch* the
threshold. `f` has a double root, so no sign change exists, the derivative
vanishes at the root, and bisection cannot converge (it only ever halves an
interval that never brackets anything). The guard's answer is to detect the
absence of a bracket and switch to minimising `|f|`, which converges to a
tangential zero.

### 3.5 Verification

| case | method | iterations | \|f\| | error |
| --- | --- | --- | --- | --- |
| linear crossing (over-speed) | Newton | 2 | 9.4e-13 | 7.8e-13 |
| | bisection | 13 | 9.8e-5 | 8.1e-5 |
| | secant | 1 | 8.9e-16 | 0 |
| | **safeguarded** | 2 | 9.4e-13 | 7.8e-13 |
| grazing root (standstill) | Newton | 5 | 3.9e-5 | 1.2e-2 |
| | bisection | 35 | 0.20 | 0.90 ← fails |
| | secant | 14 | 4.3e-5 | 1.3e-2 |
| | **safeguarded** | 58 | 7.1e-26 | **5.3e-13** |
| steep crossing (gap events) | Newton | 4 | 1.9e-9 | 8.9e-11 |
| | bisection | 16 | 5.9e-5 | 2.8e-6 |
| | secant | 20 | 28.6 | 4.3 ← diverges |
| | **safeguarded** | 4 | 1.9e-9 | 8.9e-11 |

The safeguarded solver matches pure Newton's cost on well-behaved roots (2 and 4
iterations), survives the grazing case that defeats bisection entirely, and never
diverges where the secant does.

---

## 4. Signal timing and demand

### 4.1 Fixed-time plans with offsets

Each controller has a cycle, an offset and an ordered phase list of
(green, amber, all-red) durations. At any instant `t`:

```
tt   = (t + offset) mod cycle
walk the phase list accumulating green/amber/all_red
    tt inside a green window   → GREEN,  remaining = window_end − tt
    tt inside the amber window → AMBER,  remaining = window_end − tt
    tt inside the all-red      → RED
```

A link's movement gets right of way when its phase index equals the controller's
active phase **and** the light is green. Offsets are what make coordinated
signals feed a bottleneck in bands rather than all at once.

### 4.2 Demand generation

```
for each source lane:
    vph   = Σ rows starting on this link  (flow_vph_peak × approach scale)
    rate  = vph · hour_factor(hour) · demand_multiplier / 3600    [veh/s]
    n     ~ Poisson(rate · dt / lanes)
    for each arrival:
        class = categorical(row.class_mix)
        admit only if the lane head has room
```

The surveyed movement table (`survey.csv`) and the generated arrivals therefore
reconcile by construction: the compiler splits leg inflow across lanes and
turn shares, and the engine injects exactly those rates.

---

## 5. Reproducibility

`./trackflow_engine --verify` regenerates every table above as CSV in
`verification/`. The state hash printed by `--run` and in every snapshot is FNV-1a
over `(t, id, s, v)` quantised to millimetres and millimetres-per-second, so two
runs of the same scenario with the same seed produce the same hash — the acceptance
check for determinism.
