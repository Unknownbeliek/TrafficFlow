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
    const fit = Math.min((size.w * 0.88) / (spanX / mpp),
                         (size.h * 0.88) / (spanY / mpp));
    setZoom(Math.max(0.15, Math.min(8, fit)));
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
    ctx.fillStyle = view === 'schematic' ? '#0b1220' : '#0a1424';
    ctx.fillRect(0, 0, size.w, size.h);

    const img = imgRef.current;
    if (view === 'satellite' && img) {
      // The capture is a browser screenshot: the maps search bar and category
      // chips are burnt into the top of it and the last screenshots carry the
      // taskbar.  `imagery.view` is the clean imagery rectangle, so only that is
      // drawn.  The picture itself is never rotated — the network is rotated
      // into picture space by `toImage`.
      const [ox, oy] = T.origin_px;
      const vx = imagery?.view?.[0] ?? 0;
      const vy = imagery?.view?.[1] ?? 0;
      const vw = imagery?.view?.[2] ?? img.naturalWidth;
      const vh = imagery?.view?.[3] ?? img.naturalHeight;
      ctx.save();
      ctx.imageSmoothingQuality = 'high';
      ctx.globalAlpha = imgAlpha;
      // source rect is the clean crop; the destination keeps the capture's full
      // coordinate space so pixel coordinates stay comparable with the site data
      ctx.drawImage(
        img, vx, vy, vw, vh,
        size.w / 2 + pan.x - ox * zoom + vx * zoom,
        size.h / 2 + pan.y - oy * zoom + vy * zoom,
        vw * zoom,
        vh * zoom,
      );
      ctx.globalAlpha = 1;
      ctx.restore();
      // a vignette keeps the panel chrome readable over bright imagery
      const g = ctx.createRadialGradient(
        size.w / 2, size.h / 2, Math.min(size.w, size.h) * 0.55,
        size.w / 2, size.h / 2, Math.max(size.w, size.h) * 0.95,
      );
      g.addColorStop(0, 'rgba(15,23,42,0)');
      g.addColorStop(1, 'rgba(15,23,42,0.45)');
      ctx.fillStyle = g;
      ctx.fillRect(0, 0, size.w, size.h);
    } else if (view === 'schematic') {
      ctx.strokeStyle = '#12253c';
      ctx.lineWidth = 1;
      const step = 50 * T.pxPerM;
      for (let x = (size.w / 2) % step; x < size.w; x += step) {
        ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, size.h); ctx.stroke();
      }
      for (let y = (size.h / 2) % step; y < size.h; y += step) {
        ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(size.w, y); ctx.stroke();
      }
    }

    if (!network) return;

    // --- lane network -----------------------------------------------------
    const det = detRef.current || {};
    const links = network.links;
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';

    // pass 1: carriageway casing, so lane lines read against the imagery
    for (const l of links) {
      const path = l.path || polyOf(l);
      if (!path || path.length < 2) continue;
      ctx.beginPath();
      const [x0, y0] = T.toScreen(path[0][0], path[0][1]);
      ctx.moveTo(x0, y0);
      for (let i = 1; i < path.length; i++) {
        const [x, y] = T.toScreen(path[i][0], path[i][1]);
        ctx.lineTo(x, y);
      }
      ctx.strokeStyle = 'rgba(9,15,26,0.55)';
      ctx.lineWidth = Math.max(2.2, 4.4 * T.pxPerM * 0.82);
      ctx.stroke();
    }

    const selectedLink = selected?.kind === 'link' ? selected.id : null;
    for (const l of links) {
      const path = l.path || polyOf(l);
      if (!path || path.length < 2) continue;
      const isSel = l.id === selectedLink;
      let color = '#7dd3fc';
      let w = Math.max(1.6, 2.4 * T.pxPerM * 0.42);

      if (overlay !== 'none') {
        const reads = det[l.id];
        let v = null;
        if (reads && reads.length) {
          v = reads.reduce((a, r) => a + r.speed_kmph, 0) / reads.length;
        }
        if (v != null && v > 0.5) {
          color = overlay === 'speed' ? heatColor(v, 5, 65) : heatColor(v, 65, 5);
        } else {
          color = overlay === 'speed' ? '#334155' : '#334155';
        }
        w = Math.max(2.0, 3.2 * T.pxPerM * 0.5);
      }
      if (isSel) { color = '#fbbf24'; w += 1.4; }

      ctx.beginPath();
      const [x0, y0] = T.toScreen(path[0][0], path[0][1]);
      ctx.moveTo(x0, y0);
      for (let i = 1; i < path.length; i++) {
        const [x, y] = T.toScreen(path[i][0], path[i][1]);
        ctx.lineTo(x, y);
      }
      ctx.strokeStyle = color;
      ctx.globalAlpha = l.kind === 'connector' || l.kind === 'slip' ? 0.75 : 0.92;
      ctx.lineWidth = w;
      ctx.stroke();
      ctx.globalAlpha = 1;
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
        ctx.beginPath();
        ctx.arc(x, y, 9, 0, Math.PI * 2);
        ctx.fillStyle = 'rgba(10,16,26,0.9)';
        ctx.fill();
        ctx.strokeStyle = col;
        ctx.lineWidth = 2;
        ctx.stroke();
        ctx.beginPath();
        ctx.arc(x, y, 4.2, 0, Math.PI * 2);
        ctx.fillStyle = col;
        ctx.fill();
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
      for (const v of snap.vehicles) {
        const [x, y] = T.toScreen(v.x, v.y);
        if (x < -40 || y < -40 || x > size.w + 40 || y > size.h + 40) continue;
        const cls = vcMap.get(v.cls);
        const lenM = cls?.length ?? 4.3;
        const widM = cls?.width ?? 1.8;
        const L = Math.max(5.5, lenM * T.pxPerM);
        const Wd = Math.max(3.0, widM * T.pxPerM);
        ctx.save();
        // place the glyph on its own lane, not on the shared link centreline
        const linkOf = linkById.get(v.link);
        const off = laneOffsetPx(v, linkOf, T.pxPerM) * T.pxPerM;
        ctx.translate(x, y);
        ctx.rotate(((v.hdg ?? 0) * Math.PI) / 180);
        ctx.translate(0, off);
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
