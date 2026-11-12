import React, { useEffect, useMemo, useState } from "react";
import { VEHICLE_CLASSES, LOS_COLORS, heatColor } from "../lib/geometry.js";

const fmtClock = (t) => {
  const s = Math.floor(t % 60);
  const m = Math.floor(t / 60);
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
};

export function TopBar({ sites, site, onSite, running, setRunning, speed, setSpeed, snap, mode, setMode, cycle, setCycle }) {
  return (
    <header className="flex items-center gap-3 border-b border-hairline bg-panel px-4 py-2">
      <div className="flex items-baseline gap-2">
        <span className="text-[15px] font-semibold tracking-tight text-ink">TRACKFLOW</span>
        <span className="mono text-[10px] uppercase tracking-widest text-muted">microsim · ES-251</span>
      </div>

      <select
        value={site?.id || ""}
        onChange={(e) => onSite(e.target.value)}
        className="ml-2 rounded border border-hairline bg-asphalt px-2 py-1 text-xs text-ink outline-none focus:border-accent"
      >
        {sites.map((s) => (
          <option key={s.id} value={s.id}>
            {s.name}
          </option>
        ))}
      </select>

      <div className="ml-2 flex items-center gap-1">
        <button className={`btn ${running ? "btn-active" : ""}`} onClick={() => setRunning(!running)}>
          {running ? "Pause" : "Play"}
        </button>
        {[0.5, 1, 2, 5].map((s) => (
          <button key={s} className={`btn ${speed === s ? "btn-active" : ""}`} onClick={() => setSpeed(s)}>
            {s}×
          </button>
        ))}
      </div>

      <div className="ml-3 flex items-center gap-2">
        <span className="mono text-lg text-ink">{fmtClock(snap?.t || 0)}</span>
        <span className={`h-2 w-2 rounded-full ${running ? "bg-emerald-400 live-dot" : "bg-slate-600"}`} />
      </div>

      <div className="ml-auto flex items-center gap-3">
        <div className="flex items-center gap-1">
          <span className="mono text-[10px] uppercase text-muted">Demand</span>
          {["surveyed", "manual"].map((m) => (
            <button key={m} className={`btn ${mode === m ? "btn-active" : ""}`} onClick={() => setMode(m)}>
              {m === "surveyed" ? "Natural" : "Manual"}
            </button>
          ))}
        </div>
        <label className="flex items-center gap-2">
          <span className="mono text-[10px] uppercase text-muted">cycle</span>
          <input
            type="range"
            min="40"
            max="180"
            step="4"
            value={cycle}
            onChange={(e) => setCycle(Number(e.target.value))}
            className="w-24 accent-sky-400"
          />
          <span className="mono w-10 text-[11px] text-ink">{cycle}s</span>
        </label>
        <span className="chip text-muted">
          {snap?.totals?.active ?? 0} veh · {snap?.totals?.meanV ?? 0} km/h
        </span>
      </div>
    </header>
  );
}

export function LeftPanel({ site, geometry, snapshot, layers, setLayers, selection, onSelect }) {
  const links = snapshot?.links || [];
  const [openSection, setOpen] = useState("links");
  const layerRows = [
    ["base", "Satellite base"],
    ["heatmap", "Density heatmap"],
    ["network", "Lane geometry"],
    ["signals", "Signal heads"],
    ["vehicles", "Vehicles"],
    ["labels", "Link labels"],
    ["alerts", "Alert pulses"],
  ];
  return (
    <aside className="flex w-[248px] shrink-0 flex-col gap-3 border-r border-hairline bg-panel/70 p-3 text-xs">
      <div className="panel p-2.5">
        <div className="mono text-[10px] uppercase tracking-wider text-muted">Site</div>
        <div className="mt-1 text-sm font-medium text-ink">{site?.name || "loading…"}</div>
        <div className="mono mt-0.5 text-[10px] text-muted">{site?.kind}</div>
        <div className="mono mt-2 flex flex-wrap gap-1">
          <span className="chip">{(site?.network?.links || []).length} links</span>
          <span className="chip">{(site?.network?.signal_groups || []).length} groups</span>
          <span className="chip">{site?.network?.metres_per_pixel} m/px</span>
        </div>
      </div>

      <div className="panel p-2.5">
        <Section title="Layers" open={openSection === "layers"} onClick={() => setOpen(openSection === "layers" ? "" : "layers")} />
        {openSection === "layers" && (
          <div className="mt-2 grid grid-cols-1 gap-1">
            {layerRows.map(([k, label]) => (
              <label key={k} className="flex cursor-pointer items-center gap-2 text-muted hover:text-ink">
                <input
                  type="checkbox"
                  checked={layers[k]}
                  onChange={() => setLayers({ ...layers, [k]: !layers[k] })}
                  className="accent-sky-400"
                />
                <span>{label}</span>
              </label>
            ))}
          </div>
        )}
      </div>

      <div className="panel flex-1 overflow-hidden p-2.5">
        <Section title="Network objects" open={openSection === "links"} onClick={() => setOpen(openSection === "links" ? "" : "links")} />
        {openSection === "links" && (
          <div className="mt-2 max-h-[42vh] space-y-0.5 overflow-auto pr-1">
            {geometry.map((g, i) => {
              const st = links[i];
              const sel = selection?.kind === "link" && selection.id === g.id;
              return (
                <button
                  key={g.id}
                  onClick={() => onSelect(sel ? null : { kind: "link", id: g.id })}
                  className={`flex w-full items-center gap-2 rounded px-1.5 py-1 text-left ${
                    sel ? "bg-accent/10 text-ink" : "text-muted hover:bg-white/5 hover:text-ink"
                  }`}
                >
                  <span className="h-2 w-2 shrink-0 rounded-sm" style={{ background: heatColor(st?.k || 0) }} />
                  <span className="mono shrink-0 text-[10px] opacity-70">{g.id}</span>
                  <span className="ml-auto mono text-[10px]">{st ? `${st.n}` : 0}</span>
                  {g.signal_group && <span className="mono text-[9px] text-sky-400">SIG</span>}
                </button>
              );
            })}
          </div>
        )}
      </div>
    </aside>
  );
}

function Section({ title, open, onClick }) {
  return (
    <button onClick={onClick} className="flex w-full items-center gap-1.5 text-left">
      <span className="mono text-[10px] uppercase tracking-wider text-muted">{title}</span>
      <span className="ml-auto text-[9px] text-muted">{open ? "▾" : "▸"}</span>
    </button>
  );
}

export function Inspector({ selection, geometry, snapshot, site }) {
  const linkIndex = geometry.findIndex((g) => g.id === selection?.link || g.id === selection?.id);
  const stat = linkIndex >= 0 ? snapshot?.links?.[linkIndex] : null;
  const geo = linkIndex >= 0 ? geometry[linkIndex] : null;

  if (!selection) {
    return (
      <aside className="w-[268px] shrink-0 border-l border-hairline bg-panel/70 p-3 text-xs">
        <div className="mono text-[10px] uppercase tracking-wider text-muted">Inspector</div>
        <p className="mt-2 leading-relaxed text-muted">
          Click a vehicle or a link on the canvas. Vehicles report engine state only — position along the lane,
          speed and the acceleration the RK4 stages produced — nothing is inferred in the browser.
        </p>
        <div className="mt-3 space-y-1.5">
          {(snapshot?.signals || []).map(([g, st, rem]) => (
            <div key={g} className="flex items-center gap-2 rounded border border-hairline px-2 py-1">
              <span className="mono text-[10px] text-muted">{g}</span>
              <span className="ml-auto flex gap-1">
                {["R", "A", "G"].map((c) => (
                  <span
                    key={c}
                    className="h-2.5 w-2.5 rounded-full"
                    style={{
                      background:
                        st === c ? (c === "R" ? "#ef4444" : c === "A" ? "#f59e0b" : "#22c55e") : "#1e293b",
                    }}
                  />
                ))}
              </span>
              <span className="mono w-8 text-right text-[10px] text-ink">{Math.round(rem)}s</span>
            </div>
          ))}
        </div>
      </aside>
    );
  }

  if (selection.kind === "vehicle") {
    const spec = VEHICLE_CLASSES[selection.cls] || VEHICLE_CLASSES[0];
    return (
      <aside className="w-[268px] shrink-0 space-y-3 border-l border-hairline bg-panel/70 p-3 text-xs">
        <div className="mono text-[10px] uppercase tracking-wider text-muted">Vehicle #{selection.id}</div>
        <div className="flex items-center gap-2">
          <span className="h-3 w-6 rounded-sm" style={{ background: spec.color }} />
          <span className="text-sm text-ink">{spec.label}</span>
          <span className="chip ml-auto">{spec.pcu} PCU</span>
        </div>
        <Row k="Link" v={selection.link} />
        <Row k="Lane" v={selection.lane + 1} />
        <Row k="Position s" v={`${Number(selection.s).toFixed(1)} m`} />
        <Row k="Speed" v={`${(Number(selection.v) * 3.6).toFixed(1)} km/h`} />
        <Row k="Acceleration" v={`${Number(selection.a ?? 0).toFixed(2)} m/s²`} />
        <Row k="Length" v={`${spec.len} m`} />
        <p className="leading-relaxed text-muted">
          1-D state from the C++ engine; the browser only maps <span className="mono">s</span> onto the traced lane.
        </p>
      </aside>
    );
  }

  return (
    <aside className="w-[268px] shrink-0 space-y-3 border-l border-hairline bg-panel/70 p-3 text-xs">
      <div className="mono text-[10px] uppercase tracking-wider text-muted">Link {geo?.id}</div>
      <div className="text-sm text-ink">{geo?.name}</div>
      <Row k="Length" v={`${geo ? Math.round(geo.lengthM) : 0} m`} />
      <Row k="Lanes" v={geo?.lanes} />
      <Row k="Speed limit" v={`${geo?.speed_limit_kmh} km/h`} />
      <Row k="Signal group" v={geo?.signal_group || "none"} />
      <Row k="Vehicles" v={stat?.n ?? 0} />
      <Row k="Queued (v<1.5)" v={stat?.q ?? 0} />
      <Row k="Mean speed" v={`${stat?.v ?? 0} km/h`} />
      <Row k="Density" v={`${stat?.k ?? 0} veh/km/lane`} />
      <Row k="Throughput" v={`${stat?.thr ?? 0} veh/h`} />
      <div className="flex items-center gap-2">
        <span className="text-muted">LOS</span>
        <span
          className="ml-auto rounded px-2 py-0.5 font-mono text-[11px] font-bold text-asphalt"
          style={{ background: LOS_COLORS[stat?.los || "A"] }}
        >
          {stat?.los || "A"}
        </span>
      </div>
    </aside>
  );
}

function Row({ k, v }) {
  return (
    <div className="flex items-baseline justify-between gap-2 border-b border-hairline/60 pb-1">
      <span className="text-muted">{k}</span>
      <span className="mono text-ink">{v}</span>
    </div>
  );
}

export function BottomPanel({ snapshot, approaches, onMultiplier, mode }) {
  const events = (snapshot?.events || []).slice(-6).reverse();
  // Live rows come from the engine snapshot; the site's demand list only seeds
  // the table before the first frame arrives.
  const rows =
    snapshot?.approaches?.length
      ? snapshot.approaches
      : (approaches || []).map((a) => ({
          id: a.id,
          name: a.name,
          demand: a.veh_per_hour,
          mult: 1,
          queue: 0,
          vk: 0,
          k: 0,
          los: "A",
          thr: 0,
        }));

  return (
    <footer className="grid shrink-0 grid-cols-1 gap-2 border-t border-hairline bg-panel/80 p-2 lg:grid-cols-[1fr_360px]">
      <div className="panel overflow-auto p-2">
        <div className="mono mb-1 text-[10px] uppercase tracking-wider text-muted">Approaches</div>
        <table className="w-full text-left text-[11px]">
          <thead className="mono text-[9px] uppercase text-muted">
            <tr>
              <th className="py-1 font-normal">approach</th>
              <th className="font-normal">demand veh/h</th>
              <th className="font-normal">live</th>
              <th className="font-normal">queue</th>
              <th className="font-normal">speed</th>
              <th className="font-normal">k</th>
              <th className="font-normal">LOS</th>
              <th className="font-normal">thr veh/h</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((a) => (
              <tr key={a.id} className="border-t border-hairline/60">
                <td className="py-1 text-ink">{a.name}</td>
                <td className="mono">{a.demand}</td>
                <td className="whitespace-nowrap">
                  <input
                    type="range"
                    min="0"
                    max="200"
                    step="5"
                    value={Math.round((a.mult ?? 1) * 100)}
                    disabled={mode !== "manual"}
                    onChange={(e) => onMultiplier(a.id, Number(e.target.value) / 100)}
                    className="w-16 accent-sky-400 disabled:opacity-30"
                  />
                  <span className="mono ml-1 text-[10px]">{Math.round((a.mult ?? 1) * 100)}%</span>
                </td>
                <td className="mono">{a.queue}</td>
                <td className="mono">{a.vk} km/h</td>
                <td className="mono">{a.k}</td>
                <td>
                  <span
                    className="rounded px-1.5 text-[10px] font-bold text-asphalt"
                    style={{ background: LOS_COLORS[a.los] }}
                  >
                    {a.los}
                  </span>
                </td>
                <td className="mono">{a.thr}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="panel overflow-auto p-2">
        <div className="mono mb-1 flex items-center gap-2 text-[10px] uppercase tracking-wider text-muted">
          Alert log <span className="text-[9px] normal-case text-muted/70">newton-raphson crossing time</span>
        </div>
        {events.length === 0 && <div className="text-[11px] text-muted">no threshold crossings yet</div>}
        <ul className="space-y-1">
          {events.map((e, i) => (
            <li key={i} className="flex items-center gap-2 text-[11px]">
              <span
                className="h-1.5 w-1.5 rounded-full"
                style={{ background: e.type === "overspeed" ? "#f59e0b" : e.type === "standstill" ? "#ef4444" : "#a855f7" }}
              />
              <span className="mono text-ink">{e.type}</span>
              <span className="mono text-muted">{e.link}</span>
              {e.veh >= 0 && <span className="mono text-muted">#{e.veh}</span>}
              <span className="mono ml-auto text-accent">t={Number(e.t).toFixed(2)}s</span>
              <span className="mono text-[9px] text-muted">{e.iter}it</span>
            </li>
          ))}
        </ul>
      </div>
    </footer>
  );
}

export function NumericsPanel({ onClose }) {
  const [rows, setRows] = useState(null);
  useEffect(() => {
    fetch("/reports/rk4_error.csv")
      .then((r) => (r.ok ? r.text() : Promise.reject(new Error("no report"))))
      .then((txt) => {
        const lines = txt.trim().split("\n").slice(1);
        setRows(
          lines.map((l) => {
            const [method, dt, err, order] = l.split(",");
            return { method, dt: Number(dt), err: Number(err), order: Number(order) };
          })
        );
      })
      .catch(() => setRows([]));
  }, []);

  const W = 460, H = 220, pad = 34;
  const pts = rows?.filter((r) => r.err > 0) || [];
  const maxDt = Math.max(...pts.map((p) => p.dt), 1);
  const minErr = Math.min(...pts.map((p) => p.err), 1e-12);
  const maxErr = Math.max(...pts.map((p) => p.err), 1e-6);
  const sx = (dt) => pad + (Math.log10(maxDt) - Math.log10(dt)) * ((W - 2 * pad) / (Math.log10(maxDt) - Math.log10(1 / 16)));
  const sy = (e) => H - pad - ((Math.log10(maxErr) - Math.log10(e)) / (Math.log10(maxErr) - Math.log10(minErr))) * (H - 2 * pad);
  const colors = { euler: "#f87171", rk2: "#fbbf24", rk4: "#38bdf8" };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={onClose}>
      <div className="panel max-h-[86vh] w-[980px] overflow-auto p-4" onClick={(e) => e.stopPropagation()}>
        <div className="mb-2 flex items-center">
          <h2 className="text-sm font-semibold text-ink">Numerics — error analysis and method comparison</h2>
          <button className="btn ml-auto" onClick={onClose}>
            close
          </button>
        </div>
        <p className="mb-3 text-[11px] leading-relaxed text-muted">
          Generated by <span className="mono">./trackflow verify reports</span> (engine menu option 4). This is the
          ES-251 evidence panel: measured order of accuracy from the log–log slope, not a claim.
        </p>
        {rows === null && <div className="text-xs text-muted">loading report…</div>}
        {rows?.length === 0 && (
          <div className="text-xs text-muted">
            No report yet. Run <span className="mono">cd engine &amp;&amp; make verify</span>.
          </div>
        )}
        {pts.length > 0 && (
          <div className="grid gap-4 md:grid-cols-[460px_1fr]">
            <svg width={W} height={H} className="rounded border border-hairline bg-asphalt">
              {[0, 1, 2, 3, 4].map((i) => (
                <line key={i} x1={pad} x2={W - pad} y1={pad + (i * (H - 2 * pad)) / 4} y2={pad + (i * (H - 2 * pad)) / 4} stroke="#1f2f45" />
              ))}
              {["euler", "rk2", "rk4"].map((m) => {
                const series = pts.filter((p) => p.method === m).sort((a, b) => b.dt - a.dt);
                const d = series.map((p, i) => `${i ? "L" : "M"}${sx(p.dt)},${sy(p.err)}`).join(" ");
                return (
                  <g key={m}>
                    <path d={d} fill="none" stroke={colors[m]} strokeWidth="1.6" />
                    {series.map((p) => (
                      <circle key={p.dt} cx={sx(p.dt)} cy={sy(p.err)} r="2.4" fill={colors[m]} />
                    ))}
                  </g>
                );
              })}
              <text x={pad} y={H - 8} fontSize="9" fill="#8ba0b8" className="mono">
                dt (s, log)
              </text>
              <text x={8} y={pad} fontSize="9" fill="#8ba0b8" className="mono">
                error
              </text>
            </svg>
            <div>
              <table className="w-full text-left text-[11px]">
                <thead className="mono text-[9px] uppercase text-muted">
                  <tr>
                    <th className="font-normal">method</th>
                    <th className="font-normal">dt</th>
                    <th className="font-normal">error (m/s)</th>
                    <th className="font-normal">observed order</th>
                  </tr>
                </thead>
                <tbody>
                  {pts.map((p, i) => (
                    <tr key={i} className="border-t border-hairline/60">
                      <td className="py-0.5 mono" style={{ color: colors[p.method] }}>
                        {p.method}
                      </td>
                      <td className="mono">{p.dt}</td>
                      <td className="mono">{p.err.toExponential(2)}</td>
                      <td className="mono">{p.order ? p.order.toFixed(2) : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="mt-2 text-[11px] leading-relaxed text-muted">
                Expected 1 / 2 / 4 against the closed form of <span className="mono">v' = a − k v²</span>. RK4 keeps
                its order on the vehicle ODE because the IDM acceleration field is continuous; that is why the
                engine integrates the dynamics rather than clamping speed at a stop line.
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
