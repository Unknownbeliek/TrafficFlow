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
  const scale = zoom / m_per_px;   // image px per metre, times the user's zoom
  const cx = size.w / 2 + pan.x;
  const cy = size.h / 2 + pan.y;
  const ox = origin_px[0];
  const oy = origin_px[1];
  return {
    scale,
    toScreen(x, y) {
      // rotate into the image frame, then offset, then zoom about the centre
      const ix = ox + (x * cos - y * sin) / m_per_px;
      const iy = oy + (x * sin + y * cos) / m_per_px;
      return [cx + (ix - ox) * zoom, cy + (iy - oy) * zoom];
    },
    // the scale factor for glyph sizes, in screen px per metre
    get pxPerM() { return scale * zoom; },
    imageIsLoaded: true,
  };
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
  showSignals, showLabels, selected, onSelect, interp,
}) {
  const wrapRef = useRef(null);
  const canvasRef = useRef(null);
  const imgRef = useRef(null);
  const [size, setSize] = useState({ w: 900, h: 600 });
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [hover, setHover] = useState(null);
  const dragRef = useRef(null);
  const detRef = useRef(detectors);
  detRef.current = detectors;

  // ---- image loading -------------------------------------------------------
  useEffect(() => {
    const img = new Image();
    img.src = `/api/image/${siteId}`;
    img.onload = () => { imgRef.current = img; };
    img.onerror = () => { imgRef.current = null; };
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
    const fit = Math.min((size.w * 0.86) / spanX, (size.h * 0.86) / spanY);
    // express the fit as a multiplier of the natural image scale, which the
    // transform applies on top of the site's own m/px
    setZoom(Math.max(0.25, Math.min(6, fit / 6.2)));
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
      const th = ((imagery?.rotation_deg ?? 0) * Math.PI) / 180;
      const [ox, oy] = imagery?.origin_px || [960, 540];
      ctx.save();
      ctx.translate(size.w / 2 + pan.x, size.h / 2 + pan.y);
      ctx.rotate(th);
      ctx.scale(zoom, zoom);
      ctx.globalAlpha = 0.72;
      ctx.drawImage(img, -ox, -oy);
      ctx.globalAlpha = 1;
      ctx.restore();
      // a vignette keeps the panel chrome readable over bright imagery
      const g = ctx.createRadialGradient(
        size.w / 2, size.h / 2, Math.min(size.w, size.h) * 0.25,
        size.w / 2, size.h / 2, Math.max(size.w, size.h) * 0.72,
      );
      g.addColorStop(0, 'rgba(15,23,42,0)');
      g.addColorStop(1, 'rgba(15,23,42,0.82)');
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
      let w = Math.max(1.1, 2.4 * T.pxPerM * 0.42);

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
        w = Math.max(1.4, 3.2 * T.pxPerM * 0.5);
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
          ctx.font = '600 9px "JetBrains Mono", monospace';
          ctx.fillStyle = '#cbd5e1';
          ctx.textAlign = 'left';
          ctx.fillText(`${st.id} ${ph?.name ?? ''} ${st.remaining.toFixed(0)}s`, x + 12, y + 3);
        }
      }
    }

    // --- vehicles ----------------------------------------------------------
    const vcIds = site?.vehicle_classes || [];
    const vcMap = new Map(vcIds.map((c) => [c.id, c]));
    if (snap?.vehicles) {
      for (const v of snap.vehicles) {
        const [x, y] = T.toScreen(v.x, v.y);
        if (x < -40 || y < -40 || x > size.w + 40 || y > size.h + 40) continue;
        const cls = vcMap.get(v.cls);
        const lenM = cls?.length ?? 4.3;
        const widM = cls?.width ?? 1.8;
        const L = Math.max(3.2, lenM * T.pxPerM);
        const Wd = Math.max(1.8, widM * T.pxPerM);
        ctx.save();
        ctx.translate(x, y);
        ctx.rotate(((v.hdg ?? 0) * Math.PI) / 180);
        ctx.fillStyle = VEH_COLORS[v.cls] || '#cbd5e1';
        if (v.cls === 'two_wheeler') {
          ctx.beginPath();
          ctx.ellipse(0, 0, Math.max(1.6, L * 0.5), Math.max(1.0, Wd * 0.5), 0, 0, Math.PI * 2);
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
    const barM = 50;
    const barPx = barM * T.pxPerM;
    ctx.strokeStyle = 'rgba(229,237,247,0.85)';
    ctx.lineWidth = 2;
    const bx = 18, by = size.h - 26;
    ctx.beginPath();
    ctx.moveTo(bx, by); ctx.lineTo(bx + barPx, by);
    ctx.moveTo(bx, by - 4); ctx.lineTo(bx, by + 4);
    ctx.moveTo(bx + barPx, by - 4); ctx.lineTo(bx + barPx, by + 4);
    ctx.stroke();
    ctx.font = '500 10px "JetBrains Mono", monospace';
    ctx.fillStyle = 'rgba(229,237,247,0.9)';
    ctx.textAlign = 'left';
    ctx.fillText(`${barM} m`, bx, by - 8);
  }, [network, site, snap, size, zoom, pan, overlay, view, showSignals, showLabels, selected, interp]);

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

      {/* legend */}
      <div className="absolute left-3 top-3 px-2.5 py-2 rounded bg-[rgba(10,16,26,0.82)] border hairline text-[10px]">
        <div className="label mb-1.5">
          {overlay === 'none' ? 'lanes' : overlay === 'speed' ? 'speed (km/h)' : 'density'}
        </div>
        <div className="flex items-center gap-1.5">
          <span className="w-16 h-1.5 rounded" style={{
            background: overlay === 'density'
              ? 'linear-gradient(90deg,#10b981,#f59e0b,#ef4444)'
              : 'linear-gradient(90deg,#10b981,#f59e0b,#ef4444)',
          }} />
        </div>
        <div className="flex justify-between mt-1 text-[var(--color-muted)] font-mono">
          <span>{overlay === 'density' ? '65' : '5'}</span>
          <span>{overlay === 'density' ? '5' : '65'}</span>
        </div>
        <div className="mt-2 space-y-1">
          {Object.entries(VEH_COLORS).map(([k, c]) => (
            <div key={k} className="flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-sm" style={{ background: c }} />
              <span className="text-[var(--color-muted)]">{k.replace('_', ' ')}</span>
            </div>
          ))}
        </div>
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
