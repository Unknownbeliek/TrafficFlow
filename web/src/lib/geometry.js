// 1-D to 2-D mapping.
//
// The engine only ever reports "vehicle 17 is 213.4 m along link 3". This module
// turns that into pixels using an arc-length lookup table built once per link,
// so the animation loop never calls getPointAtLength (which is a layout query
// and would dominate the frame budget at a few hundred vehicles).

export const VEHICLE_CLASSES = [
  { key: "car", label: "Car", len: 4.3, width: 1.8, color: "#7dd3fc", pcu: 1.0 },
  { key: "taxi", label: "Taxi", len: 4.4, width: 1.8, color: "#fbbf24", pcu: 1.0 },
  { key: "2w", label: "Two-wheeler", len: 1.9, width: 0.7, color: "#34d399", pcu: 0.5 },
  { key: "auto", label: "Auto-rickshaw", len: 2.6, width: 1.4, color: "#a78bfa", pcu: 1.2 },
  { key: "lcv", label: "LCV", len: 5.5, width: 2.1, color: "#f472b6", pcu: 1.5 },
  { key: "truck", label: "Truck", len: 9.0, width: 2.5, color: "#fb923c", pcu: 3.0 },
  { key: "bus", label: "Bus", len: 12.0, width: 2.5, color: "#ef4444", pcu: 3.0 },
];

export function buildGeometry(network) {
  const mpp = network?.metres_per_pixel || 1;
  return (network?.links || []).map((link, index) => {
    const pts = link.points;
    const cum = [0];
    for (let i = 1; i < pts.length; i++) {
      cum.push(cum[i - 1] + Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]));
    }
    const totalPx = cum[cum.length - 1] || 1;
    return {
      ...link,
      index,
      cum,
      totalPx,
      lengthM: totalPx * mpp,
      lanePx: (link.lane_width_m || 3.4) / mpp,
    };
  });
}

// Position, heading and lane offset for a given arc-length position.
export function pointAt(geo, sMetres, lane = 0) {
  const t = Math.max(0, Math.min(1, sMetres / geo.lengthM));
  const target = t * geo.totalPx;
  let i = 1;
  while (i < geo.cum.length - 1 && geo.cum[i] < target) i++;
  const a = geo.points[i - 1];
  const b = geo.points[i];
  const segLen = geo.cum[i] - geo.cum[i - 1] || 1;
  const f = (target - geo.cum[i - 1]) / segLen;
  const x0 = a[0] + (b[0] - a[0]) * f;
  const y0 = a[1] + (b[1] - a[1]) * f;
  const angle = Math.atan2(b[1] - a[1], b[0] - a[0]);
  const lanes = geo.lanes || 1;
  const offset = (lane - (lanes - 1) / 2) * geo.lanePx;
  return {
    x: x0 + Math.cos(angle + Math.PI / 2) * offset,
    y: y0 + Math.sin(angle + Math.PI / 2) * offset,
    angle,
    deg: (angle * 180) / Math.PI,
  };
}

export function pathD(points) {
  if (!points?.length) return "";
  return points.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" ");
}

// Density ratio -> the documented heat ramp (teal / amber / crimson).
export function heatColor(k) {
  const r = Math.max(0, Math.min(1, k / 55));
  if (r < 0.35) {
    const f = r / 0.35;
    return lerp("#0d9488", "#14b8a6", f);
  }
  if (r < 0.7) {
    const f = (r - 0.35) / 0.35;
    return lerp("#14b8a6", "#f59e0b", f);
  }
  const f = (r - 0.7) / 0.3;
  return lerp("#f59e0b", "#dc2626", f);
}

function lerp(a, b, f) {
  const pa = [1, 3, 5].map((i) => parseInt(a.slice(i, i + 2), 16));
  const pb = [1, 3, 5].map((i) => parseInt(b.slice(i, i + 2), 16));
  const p = pa.map((v, i) => Math.round(v + (pb[i] - v) * f));
  return `#${p.map((v) => v.toString(16).padStart(2, "0")).join("")}`;
}

export const LOS_COLORS = {
  A: "#22c55e",
  B: "#84cc16",
  C: "#eab308",
  D: "#f97316",
  E: "#ef4444",
  F: "#b91c1c",
};
