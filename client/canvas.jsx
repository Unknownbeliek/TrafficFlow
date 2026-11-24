import React, { useEffect, useRef, useState, useCallback } from 'react';

// ---------------------------------------------------------------------------
// Coordinate mapping.
//
// network.json carries metres in a local screen frame (x east, y south) plus an
// imagery block that places that frame on the satellite capture:
//     px = origin_px + R(rotation) * (local_m / m_per_px)
// The canvas draws the image first, then everything else through the same
// transform, so lanes, vehicles and the picture can never drift apart.
// ---------------------------------------------------------------------------
function offsetPolyline(pts, offsetPx) {
  if (!pts || pts.length < 2) return pts;
  const out = [];
  for (let i = 0; i < pts.length; i++) {
    let dx, dy;
    if (i === 0) {
      dx = pts[1][0] - pts[0][0];
      dy = pts[1][1] - pts[0][1];
    } else if (i === pts.length - 1) {
      dx = pts[i][0] - pts[i - 1][0];
      dy = pts[i][1] - pts[i - 1][1];
    } else {
      dx = pts[i + 1][0] - pts[i - 1][0];
      dy = pts[i + 1][1] - pts[i - 1][1];
    }
    const len = Math.hypot(dx, dy) || 1;
    // normal perpendicular to travel direction (pointing right)
    const nx = -dy / len;
    const ny = dx / len;
    out.push([pts[i][0] + nx * offsetPx, pts[i][1] + ny * offsetPx]);
  }
  return out;
}

function makeTransform(imagery, zoom, pan, size) {
  const { m_per_px = 0.55, origin_px = [960, 540], rotation_deg = 0 } = imagery || {};
  const th = (rotation_deg * Math.PI) / 180;
  const cos = Math.cos(th);
  const sin = Math.sin(th);
  const cx = size.w / 2 + pan.x;
  const cy = size.h / 2 + pan.y;
  const ox = origin_px[0];
  const oy = origin_px[1];
  return {
    // screen px per metre (glyph sizing, scale bar)
    pxPerM: zoom / m_per_px,
    zoom,
    origin_px,
    size,
    // local metres -> image pixels.  `rotation_deg` is the angle of the *local
    // frame* inside the image, so this is the only place the rotation is applied.
    toImage(x, y) {
      return [ox + (x * cos - y * sin) / m_per_px, oy + (x * sin + y * cos) / m_per_px];
    },
    // image pixels -> canvas screen pixels, as an axis-aligned similarity.  The
    // picture is never rotated: the geometry is rotated into picture space
    // instead, so roads and imagery cannot drift apart.
    imageToScreen(ix, iy) {
      return [cx + (ix - ox) * zoom, cy + (iy - oy) * zoom];
    },
    toScreen(x, y) {
      const [ix, iy] = this.toImage(x, y);
      return this.imageToScreen(ix, iy);
    },
  };
}

// ---------------------------------------------------------------------------
// Lane offsets.
//
// The engine tracks a vehicle's `lane` index and its arc length `s`, but sends a
// single point per vehicle: the centre of the LINK, not of the lane.  Vehicle
// bodies were therefore all drawn along one shared centreline, so a two-lane
// road looked like cars overlapping each other -- the rendering complaint.
//
// Rather than change the wire protocol, offset each vehicle sideways from the
// link centreline using its own heading and lane index.  Lanes are numbered
// left-to-right when facing the direction of travel, so lane 0 sits at
// -(n-1)/2 lane widths and the last lane at +(n-1)/2.  Both the paper width and
// the offset come from the same lane_width_m, so lanes stay consistent.
// ---------------------------------------------------------------------------
const LANE_W_DEFAULT = 3.5;

function laneOffsetPx(v, link, pxPerM) {
  const lanes = Math.max(1, link?.lanes ?? 1);
  // A single-lane slip lane ends geometrically ON the ring centreline it feeds,
  // so drawing both on the centreline puts merging and circulating vehicles on
  // top of each other.  Nudge every connector/slip onto the right-hand side of
  // its own path so the merge reads as a merge.
  if (lanes < 2) {
    const k = link?.kind;
    return (k === 'slip' || k === 'connector' || k === 'ramp') ? LANE_W_DEFAULT * 0.55 : 0;
  }
  const lw = link?.lane_width_m ?? LANE_W_DEFAULT;
  const lane = Math.max(0, Math.min(lanes - 1, v.lane ?? 0));
  // metres from the centreline; positive = left of the direction of travel
  const m = (lane - (lanes - 1) / 2) * lw;
  // the caller has already rotated into body space (x forward, y right), so
  // "left of travel" is -y there; the value is in metres and gets scaled by
  // pxPerM inside that rotated frame, not here
  return -m;
}

const VEH_COLORS = {
  car: '#e2e8f0',
  taxi: '#fbbf24',
  two_wheeler: '#38bdf8',
  auto_rickshaw: '#34d399',
  lcv: '#a78bfa',
  truck: '#f87171',
  bus: '#fb923c',
};

function heatColor(v, lo, hi) {
  // green -> amber -> red, the PRD's heat ramp
  const t = Math.max(0, Math.min(1, (v - lo) / Math.max(1e-6, hi - lo)));
  if (t < 0.5) {
    const k = t / 0.5;
    return `rgb(${Math.round(16 + (245 - 16) * k)},${Math.round(185 + (158 - 185) * k)},${Math.round(129 + (11 - 129) * k)})`;
  }
  const k = (t - 0.5) / 0.5;
  return `rgb(${Math.round(245 + (239 - 245) * k)},${Math.round(158 + (68 - 158) * k)},${Math.round(11 + (68 - 11) * k)})`;
}

export default function Canvas({
  siteId, network, site, snap, detectors, overlay, view,
  showSignals, showLabels, selected, onSelect, interp, imgAlpha = 0.95,
}) {
  const wrapRef = useRef(null);
  const canvasRef = useRef(null);
  const imgRef = useRef(null);
  const [size, setSize] = useState({ w: 900, h: 600 });
  const [zoom, setZoom] = useState(1);
  const [imgTick, setImgTick] = useState(0);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [hover, setHover] = useState(null);
  const dragRef = useRef(null);
  const detRef = useRef(detectors);
  detRef.current = detectors;

  // ---- image loading -------------------------------------------------------
  useEffect(() => {
    const img = new Image();
    img.src = `/api/image/${siteId}`;
    img.onload = () => { imgRef.current = img; setImgTick((t) => t + 1); };
    img.onerror = () => { imgRef.current = null; setImgTick((t) => t + 1); };
  }, [siteId]);

  // ---- size tracking -------------------------------------------------------
  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => {
      setSize({ w: el.clientWidth, h: el.clientHeight });
    });
    ro.observe(el);
    setSize({ w: el.clientWidth, h: el.clientHeight });
    return () => ro.disconnect();
  }, []);

  useEffect(() => { setPan({ x: 0, y: 0 }); setZoom(1); }, [siteId]);

  // ---- fit the network into view on first load ----------------------------
  useEffect(() => {
    if (!network || !size.w) return;
    let minX = 1e9, maxX = -1e9, minY = 1e9, maxY = -1e9;
    for (const l of network.links) {
      for (const p of l.geometry || []) {
        const pts = p.type === 'line' ? [p.a, p.b] : [p.c];
        for (const q of pts) {
          if (!q) continue;
          minX = Math.min(minX, q[0]); maxX = Math.max(maxX, q[0]);
          minY = Math.min(minY, q[1]); maxY = Math.max(maxY, q[1]);
        }
      }
    }
    const spanX = Math.max(60, maxX - minX);
    const spanY = Math.max(60, maxY - minY);
    // zoom is "image pixels on screen per image pixel": the network spans
    // spanX / m_per_px image pixels, so this is the zoom that fits it
    const mpp = network.imagery?.m_per_px || 0.55;
    const imgW = imgRef.current?.naturalWidth || 1920;
    const imgH = imgRef.current?.naturalHeight || 1080;
    const fitImage = Math.min(size.w / imgW, size.h / imgH);
    const fitNet = Math.min((size.w * 0.95) / (spanX / mpp), (size.h * 0.95) / (spanY / mpp));
    const fit = Math.min(fitNet, fitImage);
    setZoom(Math.max(0.35, Math.min(4.0, fit)));
  }, [network, siteId, size.w, size.h]);

  // ---- draw loop -----------------------------------------------------------
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    canvas.width = size.w * dpr;
    canvas.height = size.h * dpr;
    const ctx = canvas.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, size.w, size.h);

    const imagery = network?.imagery || site?.imagery;
    const T = makeTransform(imagery, zoom, pan, size);

    // --- background: satellite image (or the schematic grid) --------------
    ctx.fillStyle = view === 'schematic' ? '#142a1e' : '#0a1424';
    ctx.fillRect(0, 0, size.w, size.h);

    const img = imgRef.current;
    let clipBounds = null;
    if (view === 'satellite' && img) {
      const [ox, oy] = T.origin_px;
      const vx = imagery?.view?.[0] ?? 0;
      const vy = imagery?.view?.[1] ?? 0;
      const vw = imagery?.view?.[2] ?? img.naturalWidth;
      const vh = imagery?.view?.[3] ?? img.naturalHeight;
      const sx = size.w / 2 + pan.x - ox * zoom + vx * zoom;
      const sy = size.h / 2 + pan.y - oy * zoom + vy * zoom;
      const sw = vw * zoom;
      const sh = vh * zoom;
      clipBounds = { sx, sy, sw, sh };

      ctx.save();
      ctx.imageSmoothingQuality = 'high';
      ctx.globalAlpha = imgAlpha;
      ctx.drawImage(img, vx, vy, vw, vh, sx, sy, sw, sh);
      ctx.restore();

      // Subtle vignette over outer edges of the capture
      const g = ctx.createRadialGradient(
        size.w / 2, size.h / 2, Math.min(size.w, size.h) * 0.55,
        size.w / 2, size.h / 2, Math.max(size.w, size.h) * 0.95,
      );
      g.addColorStop(0, 'rgba(15,23,42,0)');
      g.addColorStop(1, 'rgba(15,23,42,0.40)');
      ctx.fillStyle = g;
      ctx.fillRect(0, 0, size.w, size.h);
    } else if (view === 'schematic') {
      // Clean landscape terrain (Image 3 reference style): subtle terrain grid
      ctx.strokeStyle = 'rgba(34, 197, 94, 0.08)';
      ctx.lineWidth = 1;
      const step = 60 * T.pxPerM;
      for (let x = (size.w / 2) % step; x < size.w; x += step) {
        ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, size.h); ctx.stroke();
      }
      for (let y = (size.h / 2) % step; y < size.h; y += step) {
        ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(size.w, y); ctx.stroke();
      }
    }

    if (!network) return;

    // In satellite mode, clip road rendering strictly to the satellite capture rectangle
    // so roads NEVER overflow outside the satellite image borders
    if (clipBounds) {
      ctx.save();
      ctx.beginPath();
      ctx.rect(clipBounds.sx, clipBounds.sy, clipBounds.sw, clipBounds.sh);
      ctx.clip();
    }

    // --- lane network -----------------------------------------------------
    const det = detRef.current || {};
    const links = [...(network.links || [])].sort((a, b) => {
      const la = a.layer ?? (a.grade === 'flyover' || a.kind === 'flyover' ? 1 : a.grade === 'underpass' ? -1 : 0);
      const lb = b.layer ?? (b.grade === 'flyover' || b.kind === 'flyover' ? 1 : b.grade === 'underpass' ? -1 : 0);
      return la - lb;
    });

    // Use crisp butt caps (no liquid glassy medicine-capsule bubbles)
    ctx.lineCap = 'butt';
    ctx.lineJoin = 'round';

    // PASS 1: Realistic Asphalt Road Surface (matching Image 3 specification)
    for (const l of links) {
      const path = l.path || polyOf(l);
      if (!path || path.length < 2) continue;
      const isElevated = (l.layer ?? 0) > 0 || l.grade === 'flyover' || l.grade === 'bridge' || l.kind === 'flyover';
      const lanes = Math.max(1, l.lanes || 1);
      const isRamp = l.kind === 'ramp' || l.kind === 'slip' || l.kind === 'connector';
      const lwM = l.lane_width_m || 3.5;
      const lwPx = lwM * T.pxPerM;
      const carriagewayPx = lanes * lwPx;
      const shoulderPx = Math.max(1.8, (isRamp ? 0.6 : 1.2) * T.pxPerM);
      const totalWidthPx = carriagewayPx + 2 * shoulderPx;

      // Elevated Flyover / Bridge structure (crisp concrete deck casing + directional contact shadow)
      if (isElevated) {
        // 1. Crisp contact shadow under the bridge
        ctx.beginPath();
        const [sx0, sy0] = T.toScreen(path[0][0], path[0][1]);
        const shadowOffset = Math.max(2, 3.5 * Math.min(2, T.pxPerM));
        ctx.moveTo(sx0 + shadowOffset * 0.7, sy0 + shadowOffset);
        for (let i = 1; i < path.length; i++) {
          const [sx, sy] = T.toScreen(path[i][0], path[i][1]);
          ctx.lineTo(sx + shadowOffset * 0.7, sy + shadowOffset);
        }
        ctx.strokeStyle = 'rgba(0, 0, 0, 0.40)';
        ctx.lineWidth = totalWidthPx + 4.0;
        ctx.stroke();

        // 2. Concrete parapet / deck border (light concrete grey casing)
        ctx.beginPath();
        ctx.moveTo(sx0, sy0);
        for (let i = 1; i < path.length; i++) {
          const [sx, sy] = T.toScreen(path[i][0], path[i][1]);
          ctx.lineTo(sx, sy);
        }
        ctx.strokeStyle = '#94a3b8';
        ctx.lineWidth = totalWidthPx + 3.0;
        ctx.stroke();

        // 3. Smooth asphalt deck surface
        ctx.strokeStyle = '#1e293b';
        ctx.lineWidth = totalWidthPx;
        ctx.stroke();
      } else {
        // Surface highway / approach
        // 1. Concrete curb / roadbed edge
        ctx.beginPath();
        const [x0, y0] = T.toScreen(path[0][0], path[0][1]);
        ctx.moveTo(x0, y0);
        for (let i = 1; i < path.length; i++) {
          const [x, y] = T.toScreen(path[i][0], path[i][1]);
          ctx.lineTo(x, y);
        }
        ctx.strokeStyle = '#475569';
        ctx.lineWidth = totalWidthPx + 2.0;
        ctx.stroke();

        // 2. Dark asphalt roadbed
        ctx.strokeStyle = '#0f172a';
        ctx.lineWidth = totalWidthPx;
        ctx.stroke();
      }
    }

    // PASS 1A: Open Asphalt Intersection Plazas (Empty asphalt area with NO lines inside, matching real Indian chowks)
    for (const n of network.nodes || []) {
      if (n.signal || n.is_plaza || n.type === 'signal') {
        const [jx, jy] = T.toScreen(n.x, n.y);
        const r = Math.max(28, (n.radius_m || 54) * T.pxPerM);
        // Concrete curb casing around the junction plaza
        ctx.beginPath();
        ctx.arc(jx, jy, r + 2.5, 0, Math.PI * 2);
        ctx.fillStyle = '#475569';
        ctx.fill();
        // Solid dark asphalt junction roadbed (seamlessly merges all meeting arms)
        ctx.beginPath();
        ctx.arc(jx, jy, r, 0, Math.PI * 2);
        ctx.fillStyle = '#0f172a';
        ctx.fill();
      }
    }

    // PASS 1B: White Road Markings (Solid outer edge lines, continuous safety line & dashed lane dividers)
    for (const l of links) {
      const path = l.path || polyOf(l);
      if (!path || path.length < 2) continue;
      const isConnector = l.kind === 'connector' || l.kind === 'slip' || l.is_junction;
      const lanes = Math.max(1, l.lanes || 1);
      const lwM = l.lane_width_m || 3.5;
      const lwPx = lwM * T.pxPerM;
      const carriagewayPx = lanes * lwPx;

      if (!isConnector && carriagewayPx > 3) {
        const screenPts = path.map(p => T.toScreen(p[0], p[1]));

        // 1. Left solid outer continuous edge line
        const leftEdge = offsetPolyline(screenPts, -carriagewayPx / 2);
        ctx.beginPath();
        ctx.moveTo(leftEdge[0][0], leftEdge[0][1]);
        for (let i = 1; i < leftEdge.length; i++) ctx.lineTo(leftEdge[i][0], leftEdge[i][1]);
        ctx.strokeStyle = 'rgba(255, 255, 255, 0.90)';
        ctx.lineWidth = 1.8;
        ctx.stroke();

        // 2. Right solid continuous SAFETY LINE (shoulder / safety edge marking)
        const rightSafety = offsetPolyline(screenPts, carriagewayPx / 2);
        ctx.beginPath();
        ctx.moveTo(rightSafety[0][0], rightSafety[0][1]);
        for (let i = 1; i < rightSafety.length; i++) ctx.lineTo(rightSafety[i][0], rightSafety[i][1]);
        ctx.strokeStyle = '#ffffff';
        ctx.lineWidth = 2.4; // Distinct, continuous safety line
        ctx.stroke();

        // 3. Crisp dotted/dashed white divider lines between EVERY lane (lanes - 1 dividers)
        if (lanes > 1) {
          const dashLen = Math.max(16, 24 * Math.min(1.8, T.pxPerM));
          const gapLen = Math.max(10, 14 * Math.min(1.8, T.pxPerM));
          ctx.setLineDash([dashLen, gapLen]);
          ctx.strokeStyle = 'rgba(255, 255, 255, 0.85)';
          ctx.lineWidth = 1.3;
          for (let k = 1; k < lanes; k++) {
            const off = (k - lanes / 2) * lwPx;
            const dividerPts = offsetPolyline(screenPts, off);
            ctx.beginPath();
            ctx.moveTo(dividerPts[0][0], dividerPts[0][1]);
            for (let i = 1; i < dividerPts.length; i++) ctx.lineTo(dividerPts[i][0], dividerPts[i][1]);
            ctx.stroke();
          }
          ctx.setLineDash([]);
        }
      }
    }

    // PASS 1C: Stop lines across approach corridors entering signalized intersection
    for (const l of links) {
      if (l.kind !== 'approach' || !l.stop_line_m) continue;
      const targetNode = (network.nodes || []).find((nd) => nd.id === l.to && (nd.signal || nd.type === 'signal'));
      if (!targetNode) continue;
      const path = l.path || polyOf(l);
      if (!path || path.length < 2) continue;
      const pEnd = path[path.length - 1];
      const pPrev = path[path.length - 2];
      const dx = pEnd[0] - pPrev[0];
      const dy = pEnd[1] - pPrev[1];
      const dLen = Math.hypot(dx, dy) || 1;
      const nx = -dy / dLen;
      const ny = dx / dLen;
      const lanes = Math.max(1, l.lanes || 1);
      const halfW = (lanes * (l.lane_width_m || 3.5)) * 0.5;
      const [sx1, sy1] = T.toScreen(pEnd[0] + nx * halfW, pEnd[1] + ny * halfW);
      const [sx2, sy2] = T.toScreen(pEnd[0] - nx * halfW, pEnd[1] - ny * halfW);

      ctx.beginPath();
      ctx.moveTo(sx1, sy1);
      ctx.lineTo(sx2, sy2);
      ctx.strokeStyle = '#ffffff';
      ctx.lineWidth = 3.6; // Bold, crisp solid stop line
      ctx.stroke();
    }

    // PASS 2: Selected link or Telemetry Heatmap Overlays (only drawn if active or selected)
    const selectedLink = selected?.kind === 'link' ? selected.id : null;
    for (const l of links) {
      const isSel = l.id === selectedLink;
      const hasOverlay = overlay !== 'none';
      if (!isSel && !hasOverlay) continue;

      const path = l.path || polyOf(l);
      if (!path || path.length < 2) continue;

      let color = null;
      let w = 2.4;

      if (hasOverlay) {
        const reads = det[l.id];
        let v = null;
        if (reads && reads.length) {
          v = reads.reduce((a, r) => a + r.speed_kmph, 0) / reads.length;
        }
        if (v != null && v > 0.5) {
          color = overlay === 'speed' ? heatColor(v, 5, 65) : heatColor(v, 65, 5);
          w = Math.max(3.0, 4.0 * T.pxPerM * 0.5);
        }
      }
      if (isSel) { color = '#fbbf24'; w = 4.0; }

      if (color) {
        ctx.beginPath();
        const [x0, y0] = T.toScreen(path[0][0], path[0][1]);
        ctx.moveTo(x0, y0);
        for (let i = 1; i < path.length; i++) {
          const [x, y] = T.toScreen(path[i][0], path[i][1]);
          ctx.lineTo(x, y);
        }
        ctx.strokeStyle = color;
        ctx.lineWidth = w;
        ctx.stroke();
      }
    }

    // --- interpolated speed profile on the inspected link ------------------
    if (interp?.ok && interp.link && interp.curve?.length) {
      const l = links.find((x) => x.id === interp.link);
      if (l) {
        const path = l.path || polyOf(l);
        const total = l.length_m || 1;
        const at = (s) => {
          // walk the polyline to arc length s
          let acc = 0;
          for (let i = 1; i < path.length; i++) {
            const a = path[i - 1], b = path[i];
            const seg = Math.hypot(b[0] - a[0], b[1] - a[1]);
            if (acc + seg >= s || i === path.length - 1) {
              const t = seg > 0 ? Math.min(1, (s - acc) / seg) : 0;
              return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
            }
            acc += seg;
          }
          return path[path.length - 1];
        };
        ctx.beginPath();
        for (let i = 0; i < interp.curve.length; i++) {
          const [s, v] = interp.curve[i];
          const [ox2, oy2] = T.toScreen(...at((s / total) * (l.length_m || 1)));
          if (i === 0) ctx.moveTo(ox2, oy2); else ctx.lineTo(ox2, oy2);
          void v;
        }
        ctx.strokeStyle = 'rgba(56,189,248,0.9)';
        ctx.lineWidth = 2.4;
        ctx.setLineDash([5, 3]);
        ctx.stroke();
        ctx.setLineDash([]);
      }
    }

    // --- signal heads ------------------------------------------------------
    if (showSignals && snap?.signals) {
      const byId = new Map((network.signals || []).map((s) => [s.id, s]));
      const nodeOf = new Map();
      for (const s of network.signals || []) {
        // the compiler names the signal node by its id
        const n = (network.nodes || []).find((x) => x.signal === s.id);
        if (n) nodeOf.set(s.id, n);
      }
      for (const st of snap.signals) {
        const n = nodeOf.get(st.id);
        if (!n) continue;
        const [x, y] = T.toScreen(n.x, n.y);
        const col = st.light === 'green' ? '#10b981' : st.light === 'amber' ? '#f59e0b' : '#ef4444';
        ctx.save();
        ctx.beginPath();
        ctx.arc(x, y, 11, 0, Math.PI * 2);
        ctx.fillStyle = '#0f172a';
        ctx.fill();
        ctx.shadowColor = col;
        ctx.shadowBlur = 8;
        ctx.strokeStyle = col;
        ctx.lineWidth = 2.5;
        ctx.stroke();
        ctx.beginPath();
        ctx.arc(x, y, 5.5, 0, Math.PI * 2);
        ctx.fillStyle = col;
        ctx.fill();
        ctx.restore();
        if (showLabels) {
          const sig = byId.get(st.id);
          const ph = sig?.phases?.[st.phase];
          const txt = `${st.id} ${ph?.name ?? ''} ${st.remaining.toFixed(0)}s`.trim();
          ctx.font = '600 9px "JetBrains Mono", monospace';
          ctx.textAlign = 'left';
          // measure first: the pill is sized to the text, so long road names
          // cannot spill out of it
          const tw = ctx.measureText(txt).width;
          const px = x + 13;
          const py = y - 8;
          ctx.fillStyle = 'rgba(10,16,26,0.88)';
          ctx.beginPath();
          roundRect(ctx, px - 4, py, tw + 8, 16, 4);
          ctx.fill();
          ctx.strokeStyle = 'rgba(148,163,184,0.28)';
          ctx.lineWidth = 1;
          ctx.stroke();
          ctx.fillStyle = '#cbd5e1';
          ctx.fillText(txt, px, py + 11);
        }
      }
    }

    // --- vehicles ----------------------------------------------------------
    const vcIds = site?.vehicle_classes || [];
    const vcMap = new Map(vcIds.map((c) => [c.id, c]));
    const linkById = new Map((network.links || []).map((l) => [l.id, l]));
    if (snap?.vehicles) {
      // Draw vehicles sorted by elevation layer (underpass -> ground -> flyover)
      const sortedVehicles = [...snap.vehicles].sort((a, b) => (a.layer || 0) - (b.layer || 0));
      for (const v of sortedVehicles) {
        const [x, y] = T.toScreen(v.x, v.y);
        if (x < -40 || y < -40 || x > size.w + 40 || y > size.h + 40) continue;
        const cls = vcMap.get(v.cls);
        const lenM = cls?.length ?? 4.3;
        const widM = cls?.width ?? 1.8;
        const L = Math.max(5.5, lenM * T.pxPerM);
        const Wd = Math.max(3.0, widM * T.pxPerM);
        ctx.save();
        // The C++ engine computes exact lane coordinates, perfectly bound to the road
        ctx.translate(x, y);
        ctx.rotate(((v.hdg ?? 0) * Math.PI) / 180);
        if ((v.layer || 0) > 0) {
          ctx.shadowColor = 'rgba(0,0,0,0.5)';
          ctx.shadowBlur = Math.max(3, 4 * T.pxPerM * 0.3);
          ctx.shadowOffsetY = Math.max(1, 2 * T.pxPerM * 0.2);
        }
        ctx.fillStyle = VEH_COLORS[v.cls] || '#cbd5e1';
        if (v.cls === 'two_wheeler') {
          ctx.beginPath();
          ctx.ellipse(0, 0, Math.max(2.6, L * 0.5), Math.max(1.8, Wd * 0.5), 0, 0, Math.PI * 2);
          ctx.fill();
        } else if (v.cls === 'auto_rickshaw') {
          ctx.beginPath();
          ctx.moveTo(L * 0.5, 0);
          ctx.lineTo(-L * 0.3, Wd * 0.5);
          ctx.lineTo(-L * 0.5, 0);
          ctx.lineTo(-L * 0.3, -Wd * 0.5);
          ctx.closePath();
          ctx.fill();
        } else {
          const r = Math.min(1.6, Wd * 0.35);
          roundRect(ctx, -L / 2, -Wd / 2, L, Wd, r);
          ctx.fill();
          // windscreen hint so the glyph reads directionally
          ctx.fillStyle = 'rgba(15,23,42,0.45)';
          roundRect(ctx, L * 0.18, -Wd * 0.34, L * 0.2, Wd * 0.68, 0.8);
          ctx.fill();
        }
        // brake lights
        if (v.v < 0.6) {
          ctx.fillStyle = '#ef4444';
          ctx.fillRect(-L / 2 - 0.8, -Wd / 2, 1.4, Wd);
        }
        ctx.restore();
      }
    }

    // --- scale bar ---------------------------------------------------------
    // The authored geometry is schematic (Connaught Place's Outer Circle is
    // modelled at 100 m but is about 600 m across), so image pixels are not
    // ground metres.  When the true ground scale is known the bar is drawn from
    // it and labelled as picture scale; otherwise it measures the schematic,
    // which is what vehicle spacing and lane widths are drawn in.
    if (clipBounds) {
      ctx.restore();
    }

    // --- scale bar ---------------------------------------------------------
    const groundMpp = imagery?.ground_m_per_px;
    if (groundMpp) {
      const NICE_G = [10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000];
      const maxPx = size.w * 0.30;
      // a ground metre is 1 / groundMpp picture pixels, and the picture is
      // currently drawn at `zoom` screen pixels per picture pixel
      const pxPerM = zoom / groundMpp;
      let barM = NICE_G[0];
      for (const m of NICE_G) if (m * pxPerM <= maxPx) barM = m;
      const barPx = barM * pxPerM;
      ctx.strokeStyle = 'rgba(229,237,247,0.85)';
      ctx.lineWidth = 2;
      const bx = 18, by = size.h - 34;
      ctx.beginPath();
      ctx.moveTo(bx, by); ctx.lineTo(bx + barPx, by);
      ctx.moveTo(bx, by - 4); ctx.lineTo(bx, by + 4);
      ctx.moveTo(bx + barPx, by - 4); ctx.lineTo(bx + barPx, by + 4);
      ctx.stroke();
      ctx.font = '500 10px "JetBrains Mono", monospace';
      ctx.fillStyle = 'rgba(229,237,247,0.9)';
      ctx.textAlign = 'left';
      ctx.fillText(`${barM} m ground`, bx, by - 8);
    } else {
      const NICE = [10, 20, 25, 50, 100, 200, 250, 500, 1000];
      let barM = NICE[0];
      for (const m of NICE) if (m * T.pxPerM <= size.w * 0.30) barM = m;
      const barPx = barM * T.pxPerM;
      ctx.strokeStyle = 'rgba(229,237,247,0.85)';
      ctx.lineWidth = 2;
      const bx = 18, by = size.h - 34;
      ctx.beginPath();
      ctx.moveTo(bx, by); ctx.lineTo(bx + barPx, by);
      ctx.moveTo(bx, by - 4); ctx.lineTo(bx, by + 4);
      ctx.moveTo(bx + barPx, by - 4); ctx.lineTo(bx + barPx, by + 4);
      ctx.stroke();
      ctx.font = '500 10px "JetBrains Mono", monospace';
      ctx.fillStyle = 'rgba(229,237,247,0.9)';
      ctx.textAlign = 'left';
      ctx.fillText(`${barM} m (schematic)`, bx, by - 8);
    }
  }, [network, site, snap, size, zoom, pan, overlay, view, showSignals, showLabels, selected, interp, imgAlpha, imgTick]);

  // ---- interaction --------------------------------------------------------
  const onWheel = useCallback((e) => {
    e.preventDefault();
    const k = Math.exp(-e.deltaY * 0.0016);
    setZoom((z) => Math.max(0.22, Math.min(14, z * k)));
  }, []);

  const onDown = (e) => {
    dragRef.current = { x: e.clientX, y: e.clientY, pan: { ...pan }, moved: false };
  };
  const onMove = (e) => {
    const d = dragRef.current;
    if (d) {
      const dx = e.clientX - d.x;
      const dy = e.clientY - d.y;
      if (Math.abs(dx) + Math.abs(dy) > 3) d.moved = true;
      setPan({ x: d.pan.x + dx, y: d.pan.y + dy });
      return;
    }
    // hover pick: nearest lane within 8 px
    const rect = canvasRef.current?.getBoundingClientRect();
    if (!rect || !network) return;
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;
    const T = makeTransform(network.imagery || site?.imagery, zoom, pan, size);
    let best = null, bestD = 10;
    for (const l of network.links) {
      const path = l.path || polyOf(l);
      if (!path) continue;
      for (let i = 1; i < path.length; i++) {
        const [ax, ay] = T.toScreen(...path[i - 1]);
        const [bx, by] = T.toScreen(...path[i]);
        const d2 = pointSegDist(mx, my, ax, ay, bx, by);
        if (d2 < bestD) { bestD = d2; best = l; }
      }
    }
    setHover(best ? { id: best.id, name: best.name, carriageway: best.carriageway } : null);
  };
  const onUp = () => {
    const d = dragRef.current;
    dragRef.current = null;
    if (!d?.moved && hover) onSelect?.({ kind: 'link', id: hover.id });
  };

  return (
    <div ref={wrapRef} className="absolute inset-0 overflow-hidden">
      <canvas
        ref={canvasRef}
        style={{ width: size.w, height: size.h, cursor: dragRef.current ? 'grabbing' : 'crosshair' }}
        onWheel={onWheel}
        onMouseDown={onDown}
        onMouseMove={onMove}
        onMouseUp={onUp}
        onMouseLeave={() => { dragRef.current = null; setHover(null); }}
      />

      {/* legend: docked under the map so it never covers the imagery */}
      <div className="absolute left-0 right-0 bottom-0 h-7 px-3 flex items-center gap-3 border-t hairline bg-[rgba(10,16,26,0.94)] text-[10px] text-[var(--color-muted)]">
        <span className="label">{overlay === 'none' ? 'lanes' : overlay === 'speed' ? 'speed km/h' : 'density'}</span>
        <span className="w-16 h-1.5 rounded" style={{
          background: 'linear-gradient(90deg,#10b981,#f59e0b,#ef4444)',
        }} />
        <span className="font-mono">{overlay === 'density' ? '5 → 65' : '5 → 65'}</span>
        <span className="flex-1" />
        {Object.entries(VEH_COLORS).map(([k, c]) => (
          <span key={k} className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-sm" style={{ background: c }} />
            <span>{k.replace(/_/g, ' ')}</span>
          </span>
        ))}
      </div>

      {hover && (
        <div className="absolute bottom-3 right-3 px-2 py-1 rounded bg-[rgba(10,16,26,0.9)] border hairline font-mono text-[10px] text-[var(--color-muted)]">
          {hover.id} · {hover.carriageway}
        </div>
      )}

      <div className="absolute right-3 top-3 flex flex-col gap-1">
        <button
          onClick={() => setZoom((z) => Math.min(14, z * 1.25))}
          className="w-7 h-7 rounded bg-[rgba(10,16,26,0.9)] border hairline text-[var(--color-ink)] hover:border-[var(--color-accent)]"
        >+</button>
        <button
          onClick={() => setZoom((z) => Math.max(0.22, z / 1.25))}
          className="w-7 h-7 rounded bg-[rgba(10,16,26,0.9)] border hairline text-[var(--color-ink)] hover:border-[var(--color-accent)]"
        >−</button>
        <button
          onClick={() => { setZoom(1); setPan({ x: 0, y: 0 }); }}
          className="w-7 h-7 rounded bg-[rgba(10,16,26,0.9)] border hairline text-[var(--color-muted)] hover:border-[var(--color-accent)] text-[9px]"
        >fit</button>
      </div>
    </div>
  );
}

function polyOf(l) {
  if (!l.geometry) return null;
  const out = [];
  for (const p of l.geometry) {
    if (p.type === 'line') {
      if (!out.length) out.push(p.a);
      out.push(p.b);
    } else if (p.type === 'arc') {
      const sweep = p.a1 - p.a0;
      const n = Math.max(6, Math.ceil(Math.abs(sweep) / 6));
      for (let i = 0; i <= n; i++) {
        const a = ((p.a0 + (sweep * i) / n) * Math.PI) / 180;
        out.push([p.c[0] + p.r * Math.cos(a), p.c[1] + p.r * Math.sin(a)]);
      }
    } else if (p.type === 'bezier') {
      const n = 16;
      for (let i = 0; i <= n; i++) {
        const t = i / n, u = 1 - t;
        const x = u*u*u*p.p0[0] + 3*u*u*t*p.p1[0] + 3*u*t*t*p.p2[0] + t*t*t*p.p3[0];
        const y = u*u*u*p.p0[1] + 3*u*u*t*p.p1[1] + 3*u*t*t*p.p2[1] + t*t*t*p.p3[1];
        out.push([x, y]);
      }
    }
  }
  return out.length >= 2 ? out : null;
}

function roundRect(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

function pointSegDist(px, py, ax, ay, bx, by) {
  const dx = bx - ax, dy = by - ay;
  const L2 = dx * dx + dy * dy;
  let t = L2 > 0 ? ((px - ax) * dx + (py - ay) * dy) / L2 : 0;
  t = Math.max(0, Math.min(1, t));
  const x = ax + dx * t, y = ay + dy * t;
  return Math.hypot(px - x, py - y);
}
