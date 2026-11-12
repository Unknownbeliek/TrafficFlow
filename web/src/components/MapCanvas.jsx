import React, { useMemo } from "react";
import { VEHICLE_CLASSES, pathD, pointAt, heatColor } from "../lib/geometry.js";

// The canvas is a plain <svg> over a satellite image with viewBox
// "0 0 imageW imageH", so engine metres and image pixels share one frame.
export default function MapCanvas({ site, geometry, snapshot, layers, selection, onSelect, pulseEvents }) {
  const mpp = site?.network?.metres_per_pixel || 1;
  const links = snapshot?.links || [];
  const signals = useMemo(() => {
    const m = {};
    (snapshot?.signals || []).forEach(([g, s, r]) => (m[g] = { state: s, remaining: r }));
    return m;
  }, [snapshot?.signals]);
  const vehicles = snapshot?.vehicles || [];
  const selectedVeh = selection?.kind === "vehicle" ? selection.id : null;
  const selectedLink = selection?.kind === "link" ? selection.id : null;

  return (
    <svg
      viewBox={`0 0 ${site?.network?.image_size?.[0] || 1920} ${site?.network?.image_size?.[1] || 1080}`}
      className="h-full w-full"
      preserveAspectRatio="xMidYMid meet"
      onClick={() => onSelect(null)}
    >
      <defs>
        <filter id="glow" x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="3" result="b" />
          <feMerge>
            <feMergeNode in="b" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>

      {layers.base && site && (
        <image href={site.image} x="0" y="0" width={site.network.image_size[0]} height={site.network.image_size[1]} />
      )}
      {/* keep the dark UI legible over bright satellite imagery */}
      {layers.base && <rect x="0" y="0" width="1920" height="1080" fill="#0f172a" opacity="0.28" />}

      {/* heatmap: stroke width = carriageway width, colour = density */}
      {layers.heatmap &&
        geometry.map((geo, i) => {
          const stat = links[i];
          if (!stat) return null;
          const ratioK = stat.k || 0;
          return (
            <path
              key={`h${geo.id}`}
              d={pathD(geo.points)}
              stroke={heatColor(ratioK)}
              strokeWidth={(geo.lanes * geo.lanePx)}
              strokeLinecap="round"
              fill="none"
              opacity={0.42}
            />
          );
        })}

      {/* lane geometry */}
      {layers.network &&
        geometry.map((geo) => {
          const isSel = selectedLink === geo.id;
          return (
            <g key={geo.id}>
              {Array.from({ length: geo.lanes }).map((_, lane) => (
                <path
                  key={lane}
                  d={lanePath(geo, lane)}
                  stroke={isSel ? "#38bdf8" : "#cbd5e1"}
                  strokeWidth={isSel ? 1.6 : 1}
                  strokeDasharray={isSel ? "" : "6 10"}
                  fill="none"
                  opacity={isSel ? 0.95 : 0.55}
                />
              ))}
              <path
                d={pathD(geo.points)}
                stroke="transparent"
                strokeWidth={Math.max(14, geo.lanes * geo.lanePx)}
                fill="none"
                style={{ cursor: "pointer" }}
                onClick={(e) => {
                  e.stopPropagation();
                  onSelect({ kind: "link", id: geo.id });
                }}
              />
            </g>
          );
        })}

      {/* signals at the stop line of every controlled link */}
      {layers.signals &&
        geometry.map((geo) => {
          if (!geo.signal_group) return null;
          const end = geo.points[geo.points.length - 1];
          const prev = geo.points[geo.points.length - 2] || end;
          const angle = Math.atan2(end[1] - prev[1], end[0] - prev[0]);
          const sg = signals[geo.signal_group] || { state: "G", remaining: 0 };
          const off = geo.lanes * geo.lanePx * 0.9;
          const x = end[0] + Math.cos(angle + Math.PI / 2) * off;
          const y = end[1] + Math.sin(angle + Math.PI / 2) * off;
          return (
            <g key={`s${geo.id}`} transform={`translate(${x},${y})`}>
              <rect x="-7" y="-20" width="14" height="38" rx="3" fill="#0b1220" stroke="#334155" strokeWidth="1" />
              {["R", "A", "G"].map((c, i) => {
                const on = sg.state === c;
                const fill = c === "R" ? "#ef4444" : c === "A" ? "#f59e0b" : "#22c55e";
                return (
                  <circle
                    key={c}
                    cx="0"
                    cy={-13 + i * 12}
                    r="4"
                    fill={on ? fill : "#1e293b"}
                    opacity={on ? 1 : 0.55}
                    filter={on ? "url(#glow)" : undefined}
                  />
                );
              })}
              <text x="10" y="-14" fontSize="10" fill="#94a3b8" className="mono">
                {Math.round(sg.remaining)}s
              </text>
            </g>
          );
        })}

      {/* vehicles */}
      {layers.vehicles &&
        vehicles.map(([id, cls, linkIdx, lane, s, v]) => {
          const geo = geometry[linkIdx];
          if (!geo) return null;
          const spec = VEHICLE_CLASSES[cls] || VEHICLE_CLASSES[0];
          const p = pointAt(geo, s, lane);
          const L = Math.max(6, spec.len / mpp);
          const W = Math.max(3.5, spec.width / mpp);
          const isSel = selectedVeh === id;
          return (
            <g
              key={id}
              transform={`translate(${p.x},${p.y}) rotate(${p.deg})`}
              style={{ cursor: "pointer" }}
              onClick={(e) => {
                e.stopPropagation();
                onSelect({ kind: "vehicle", id, cls, link: geo.id, lane, s, v, id2: id });
              }}
            >
              <rect
                x={-L / 2}
                y={-W / 2}
                width={L}
                height={W}
                rx={Math.min(1.2, W / 3)}
                fill={spec.color}
                stroke={isSel ? "#ffffff" : "rgba(8,15,25,0.85)"}
                strokeWidth={isSel ? 1.4 : 0.5}
                opacity={0.95}
              />
              {spec.key === "taxi" && <rect x={-L * 0.12} y={-W * 0.18} width={L * 0.24} height={W * 0.36} fill="#0f172a" opacity="0.8" />}
              {spec.key === "bus" && <rect x={-L / 2 + 1} y={-W / 2 + 0.6} width={L - 2} height={W - 1.2} fill="none" stroke="#0f172a" strokeWidth="0.4" opacity="0.6" />}
            </g>
          );
        })}

      {/* alert pulses at the computed crossing position */}
      {layers.alerts &&
        (pulseEvents || []).map((ev, i) => {
          const geoIdx = geometry.findIndex((g) => g.id === ev.link);
          if (geoIdx < 0) return null;
          const veh = vehicles.find((v) => v[0] === ev.veh);
          const p = veh ? pointAt(geometry[veh[2]], veh[4], veh[3]) : pointAt(geometry[geoIdx], geometry[geoIdx].lengthM * 0.5, 0);
          const col = ev.type === "overspeed" ? "#f59e0b" : ev.type === "standstill" ? "#ef4444" : "#a855f7";
          return (
            <g key={`${ev.type}-${ev.veh}-${ev.t}-${i}`}>
              <circle cx={p.x} cy={p.y} r="6" fill="none" stroke={col} strokeWidth="2" className="pulse" />
              <circle cx={p.x} cy={p.y} r="2.5" fill={col} />
            </g>
          );
        })}

      {layers.labels &&
        geometry.map((geo) => {
          const mid = geo.points[Math.floor(geo.points.length / 2)];
          return (
            <text key={`l${geo.id}`} x={mid[0]} y={mid[1]} fontSize="11" fill="#e2e8f0" opacity="0.75" className="mono">
              {geo.id}
            </text>
          );
        })}
    </svg>
  );
}

function lanePath(geo, lane) {
  const steps = Math.max(2, geo.points.length - 1);
  let d = "";
  for (let i = 0; i <= steps; i++) {
    const s = (i / steps) * geo.lengthM;
    const p = pointAt(geo, s, lane);
    d += `${i ? "L" : "M"}${p.x.toFixed(1)},${p.y.toFixed(1)} `;
  }
  return d;
}
