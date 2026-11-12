import React, { useMemo, useState } from 'react';

// ---------------------------------------------------------------------------
// shared bits
// ---------------------------------------------------------------------------
const SITE_LIST = [
  { id: 'kalindi_kunj', label: 'Kalindi Kunj', sub: 'bridge' },
  { id: 'connaught_place', label: 'Connaught Place', sub: 'circles' },
  { id: 'ito', label: 'ITO', sub: 'grid' },
  { id: 'gaur_city', label: 'Gaur City', sub: 'roundabout' },
  { id: 'botanical_okhla', label: 'Botanical Okhla', sub: 'cloverleaf' },
];

const fmt = (v, dp = 1) => (v == null || Number.isNaN(v) ? '—' : Number(v).toFixed(dp));
const pct = (v) => `${(v * 100).toFixed(0)}%`;

function Section({ title, right, children }) {
  return (
    <div className="px-3 py-2.5 border-b hairline last:border-0">
      <div className="flex items-center justify-between mb-1.5">
        <div className="label">{title}</div>
        {right}
      </div>
      {children}
    </div>
  );
}

function Row({ k, v, mono = true, tone }) {
  return (
    <div className="flex justify-between items-baseline py-[1px] gap-3">
      <span className="text-[11px] text-[var(--color-muted)] truncate">{k}</span>
      <span
        className={`text-[11px] tabular shrink-0 ${mono ? 'font-mono' : ''}`}
        style={{ color: tone || 'var(--color-ink)' }}
      >
        {v}
      </span>
    </div>
  );
}

function Pill({ children, tone = 'muted' }) {
  const map = {
    green: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30',
    amber: 'bg-amber-500/15 text-amber-300 border-amber-500/30',
    red: 'bg-red-500/15 text-red-300 border-red-500/30',
    accent: 'bg-sky-500/15 text-sky-300 border-sky-500/30',
    muted: 'bg-slate-500/10 text-slate-300 border-slate-500/30',
  };
  return (
    <span className={`px-1.5 py-[1px] rounded-sm border text-[9px] font-semibold uppercase tracking-wide ${map[tone]}`}>
      {children}
    </span>
  );
}

// ---------------------------------------------------------------------------
// top bar
// ---------------------------------------------------------------------------
export function TopBar({
  sites, siteId, onSite, connected, running, setRunning, paused, onPause,
  speed, onSpeed, onReset, onStep, overlay, setOverlay, view, setView,
  showSignals, setShowSignals, showLabels, setShowLabels, snap,
}) {
  const list = sites?.length ? sites : SITE_LIST;
  return (
    <div className="shrink-0 border-b hairline bg-[var(--color-panel)]">
      {/* row 1: brand, site switcher, transport */}
      <div className="flex items-center gap-3 px-3 h-11">
        <div className="flex items-center gap-2 pr-3 border-r hairline">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
            <path d="M3 17h3l2-6h8l2 6h3" stroke="#38bdf8" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
            <circle cx="7.5" cy="18.5" r="1.6" stroke="#38bdf8" strokeWidth="1.6" />
            <circle cx="16.5" cy="18.5" r="1.6" stroke="#38bdf8" strokeWidth="1.6" />
          </svg>
          <div className="leading-none">
            <div className="text-[13px] font-semibold tracking-tight">Trackflow</div>
            <div className="text-[9px] text-[var(--color-muted)] mt-0.5 tracking-wide">
              DELHI-NCR · MICROSCOPIC
            </div>
          </div>
        </div>

        <div className="flex items-center gap-1">
          {list.map((s) => (
            <button
              key={s.id}
              onClick={() => onSite(s.id)}
              className={`px-2.5 h-7 rounded-sm border text-[11px] transition-colors ${
                siteId === s.id
                  ? 'border-[var(--color-accent)] bg-sky-500/10 text-[var(--color-accent)]'
                  : 'border-transparent text-[var(--color-muted)] hover:border-[var(--color-hair)] hover:text-[var(--color-ink)]'
              }`}
              title={s.sub || s.kind}
            >
              {s.label || s.name}
            </button>
          ))}
        </div>

        <div className="flex-1" />

        <div className="flex items-center gap-1.5">
          <span className={`w-1.5 h-1.5 rounded-full ${connected ? 'bg-emerald-400 pulse-dot' : 'bg-red-500'}`} />
          <span className="text-[10px] text-[var(--color-muted)] font-mono">
            {connected ? 'linked' : 'offline'}
          </span>
        </div>

        <div className="flex items-center gap-1 pl-2 border-l hairline">
          <button
            onClick={() => setRunning(!running)}
            className={`w-7 h-7 rounded-sm border text-[11px] ${running ? 'border-emerald-500/40 text-emerald-300' : 'border-[var(--color-hair)] text-[var(--color-muted)]'}`}
            title={running ? 'pause the clock' : 'run'}
          >{running ? '❚❚' : '▶'}</button>
          <button onClick={onPause} className="w-7 h-7 rounded-sm border hairline text-[11px] text-[var(--color-muted)]" title="engine pause">
            {paused ? '↺' : '⏸'}
          </button>
          <button onClick={onStep} className="h-7 px-2 rounded-sm border hairline text-[10px] text-[var(--color-muted)]" title="single step">
            step
          </button>
          <button onClick={onReset} className="h-7 px-2 rounded-sm border hairline text-[10px] text-[var(--color-muted)]" title="reset">
            reset
          </button>
        </div>

        <div className="flex items-center gap-1 pl-2 border-l hairline">
          {[0.5, 1, 2, 5].map((k) => (
            <button
              key={k}
              onClick={() => onSpeed(k)}
              className={`h-7 w-8 rounded-sm border text-[10px] font-mono ${
                speed === k
                  ? 'border-[var(--color-accent)] text-[var(--color-accent)] bg-sky-500/10'
                  : 'border-transparent text-[var(--color-muted)] hover:border-[var(--color-hair)]'
              }`}
            >{k}×</button>
          ))}
        </div>
        <div className="pl-2 border-l hairline font-mono text-[11px] text-[var(--color-ink)] tabular w-[74px] text-right">
          {fmt(snap?.t, 1)}<span className="text-[var(--color-muted)]"> s</span>
        </div>
      </div>

      {/* row 2: view / overlay controls */}
      <div className="flex items-center gap-2 px-3 h-8 border-t hairline">
        <div className="label">view</div>
        {['satellite', 'schematic'].map((v) => (
          <button
            key={v}
            onClick={() => setView(v)}
            className={`h-5 px-1.5 rounded-sm text-[10px] border ${
              view === v ? 'border-[var(--color-accent)] text-[var(--color-accent)]' : 'border-transparent text-[var(--color-muted)]'
            }`}
          >{v}</button>
        ))}
        <div className="w-px h-4 bg-[var(--color-hair)] mx-1" />
        <div className="label">overlay</div>
        {[['speed', 'speed'], ['density', 'density'], ['none', 'off']].map(([k, l]) => (
          <button
            key={k}
            onClick={() => setOverlay(k)}
            className={`h-5 px-1.5 rounded-sm text-[10px] border ${
              overlay === k ? 'border-[var(--color-accent)] text-[var(--color-accent)]' : 'border-transparent text-[var(--color-muted)]'
            }`}
          >{l}</button>
        ))}
        <div className="w-px h-4 bg-[var(--color-hair)] mx-1" />
        <label className="flex items-center gap-1 text-[10px] text-[var(--color-muted)] cursor-pointer">
          <input type="checkbox" checked={showSignals} onChange={(e) => setShowSignals(e.target.checked)} className="accent-sky-500" />
          signal heads
        </label>
        <label className="flex items-center gap-1 text-[10px] text-[var(--color-muted)] cursor-pointer">
          <input type="checkbox" checked={showLabels} onChange={(e) => setShowLabels(e.target.checked)} className="accent-sky-500" />
          labels
        </label>

        <div className="flex-1" />
        <div className="flex items-center gap-3 font-mono text-[10px]">
          <span className="text-[var(--color-muted)]">
            active <span className="text-[var(--color-ink)] tabular">{snap?.active ?? 0}</span>
          </span>
          <span className="text-[var(--color-muted)]">
            arrived <span className="text-[var(--color-ink)] tabular">{snap?.arrived ?? 0}</span>
          </span>
          <span className="text-[var(--color-muted)]">
            delay <span className="text-[var(--color-ink)] tabular">{fmt(snap?.mean_delay, 1)}s</span>
          </span>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// network object tree
// ---------------------------------------------------------------------------
export function ObjectTree({ network, siteMeta, snap, detectors, selected, onSelect, onInspectLink }) {
  const [open, setOpen] = useState({
    site: true, links: true, carriageways: true, signals: true, approaches: false,
    vehicles: false, heat: false, scenarios: true,
  });
  const [filter, setFilter] = useState('');

  const toggle = (k) => setOpen((o) => ({ ...o, [k]: !o[k] }));

  const carriageways = useMemo(() => {
    if (!network) return [];
    const m = new Map();
    for (const l of network.links) {
      const key = l.carriageway || l.id;
      if (!m.has(key)) m.set(key, { name: key, heat: l.heat_group, links: [], lanes: l.lanes });
      m.get(key).links.push(l);
    }
    return [...m.values()].filter((c) => !filter || c.name.toLowerCase().includes(filter.toLowerCase()));
  }, [network, filter]);

  const vehCounts = useMemo(() => {
    const m = {};
    for (const v of snap?.vehicles || []) m[v.cls] = (m[v.cls] || 0) + 1;
    return m;
  }, [snap]);

  const signalStates = useMemo(() => {
    const m = {};
    for (const s of snap?.signals || []) m[s.id] = s;
    return m;
  }, [snap]);

  return (
    <div className="w-[248px] shrink-0 border-r hairline bg-[var(--color-panel)] flex flex-col">
      <div className="px-3 h-8 flex items-center justify-between border-b hairline">
        <div className="label">network</div>
        <input
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="filter…"
          className="w-24 h-5 text-[10px]"
        />
      </div>
      <div className="flex-1 overflow-y-auto thin-scroll text-[11px]">
        <TreeRow depth={0} open={open.site} onToggle={() => toggle('site')} bold>
          {siteMeta?.label || 'site'}
        </TreeRow>
        {open.site && (
          <>
            <TreeRow depth={1} leaf>geometry <span className="text-[var(--color-muted)] font-mono">{network ? `${network.links.length} links` : ''}</span></TreeRow>
            <TreeRow depth={1} leaf>imagery <span className="text-[var(--color-muted)] font-mono">{network ? `${network.imagery?.m_per_px} m/px` : ''}</span></TreeRow>
          </>
        )}

        <TreeRow depth={0} open={open.carriageways} onToggle={() => toggle('carriageways')} bold>
          carriageways <span className="text-[var(--color-muted)] font-mono">{carriageways.length}</span>
        </TreeRow>
        {open.carriageways && carriageways.map((c) => (
          <div key={c.name}>
            <TreeRow depth={1} leaf onClick={() => onInspectLink?.(c.links[0].id)}>
              <span className="truncate">{c.name}</span>
              <span className="text-[var(--color-muted)] font-mono ml-1">{c.links.length}</span>
            </TreeRow>
            {c.links.slice(0, 40).map((l) => {
              const det = detectors?.[l.id];
              const v = det?.length ? det.reduce((a, r) => a + r.speed_kmph, 0) / det.length : null;
              return (
                <TreeRow
                  key={l.id}
                  depth={2}
                  leaf
                  active={selected?.kind === 'link' && selected.id === l.id}
                  onClick={() => onInspectLink?.(l.id)}
                >
                  <span className="font-mono text-[10px]">{l.id}</span>
                  <span className="flex-1" />
                  {v != null && v > 0.1 && (
                    <span className="font-mono text-[9px] text-[var(--color-muted)]">{v.toFixed(0)}</span>
                  )}
                </TreeRow>
              );
            })}
            {c.links.length > 40 && (
              <TreeRow depth={2} leaf><span className="text-[var(--color-muted)]">+{c.links.length - 40} more</span></TreeRow>
            )}
          </div>
        ))}

        <TreeRow depth={0} open={open.signals} onToggle={() => toggle('signals')} bold>
          signal controllers <span className="text-[var(--color-muted)] font-mono">{network?.signals?.length ?? 0}</span>
        </TreeRow>
        {open.signals && (network?.signals || []).map((s) => {
          const st = signalStates[s.id];
          const tone = st?.light === 'green' ? 'green' : st?.light === 'amber' ? 'amber' : 'red';
          return (
            <TreeRow key={s.id} depth={1} leaf onClick={() => onSelect?.({ kind: 'signal', id: s.id })}>
              <span className="font-mono text-[10px]">{s.id}</span>
              <span className="flex-1" />
              {st && <Pill tone={tone}>{st.remaining.toFixed(0)}s</Pill>}
            </TreeRow>
          );
        })}

        <TreeRow depth={0} open={open.vehicles} onToggle={() => toggle('vehicles')} bold>
          vehicles <span className="text-[var(--color-muted)] font-mono">{snap?.active ?? 0}</span>
        </TreeRow>
        {open.vehicles && Object.entries(vehCounts).sort((a, b) => b[1] - a[1]).map(([k, n]) => (
          <TreeRow key={k} depth={1} leaf>
            {k.replace('_', ' ')}<span className="flex-1" /><span className="font-mono text-[var(--color-muted)]">{n}</span>
          </TreeRow>
        ))}

        <TreeRow depth={0} open={open.heat} onToggle={() => toggle('heat')} bold>
          heat groups <span className="text-[var(--color-muted)] font-mono">{network?.heat_groups?.length ?? 0}</span>
        </TreeRow>
        {open.heat && (network?.heat_groups || []).map((g) => (
          <TreeRow key={g.id} depth={1} leaf><span className="truncate">{g.name}</span></TreeRow>
        ))}

        <TreeRow depth={0} open={open.scenarios} onToggle={() => toggle('scenarios')} bold>
          scenarios <span className="text-[var(--color-muted)] font-mono">{network?.scenarios?.length ?? 0}</span>
        </TreeRow>
        {open.scenarios && (network?.scenarios || []).map((s) => (
          <TreeRow key={s.id} depth={1} leaf onClick={() => onSelect?.({ kind: 'scenario', id: s.id })}>
            <span className="truncate" title={s.note}>{s.name}</span>
          </TreeRow>
        ))}
      </div>
    </div>
  );
}

function TreeRow({ depth, children, open, onToggle, leaf, onClick, active, bold }) {
  return (
    <div
      onClick={onClick}
      className={`flex items-center gap-1 h-[22px] pr-2 cursor-pointer select-none ${
        active ? 'bg-sky-500/15 text-[var(--color-accent)]' : 'hover:bg-white/[0.03]'
      }`}
      style={{ paddingLeft: 6 + depth * 12 }}
    >
      {onToggle ? (
        <span
          onClick={(e) => { e.stopPropagation(); onToggle(); }}
          className="w-3 text-[9px] text-[var(--color-muted)]"
        >{open ? '▾' : '▸'}</span>
      ) : (
        <span className="w-3 text-[9px] text-[var(--color-hair)]">{leaf ? '·' : ''}</span>
      )}
      <span className={`flex-1 flex items-center gap-1 min-w-0 truncate ${bold ? 'font-semibold' : ''}`}>
        {children}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// inspector
// ---------------------------------------------------------------------------
export function Inspector({ selected, network, snap, interp, onInspectLink }) {
  if (!network) {
    return <div className="p-3 text-[11px] text-[var(--color-muted)]">loading network…</div>;
  }
  if (!selected) {
    return (
      <div className="p-3 space-y-2">
        <div className="label">Inspector</div>
        <p className="text-[11px] text-[var(--color-muted)] leading-relaxed">
          Select a carriageway in the network tree, or click a lane on the map, to
          inspect its geometry, demand, detector chain and reconstructed speed
          profile.
        </p>
        <div className="mt-3 pt-3 border-t hairline">
          <Section title="site">
            <Row k="id" v={network.site?.id} />
            <Row k="kind" v={network.site?.kind} />
            <Row k="links" v={network.links?.length} />
            <Row k="nodes" v={network.nodes?.length} />
            <Row k="turns" v={network.turns?.length} />
            <Row k="movements" v={network.demand?.length} />
            <Row k="peak demand" v={`${(network.demand || []).reduce((a, d) => a + d.flow_vph_peak, 0).toLocaleString()} veh/h`} />
          </Section>
        </div>
      </div>
    );
  }

  if (selected.kind === 'signal') {
    const sig = (network.signals || []).find((s) => s.id === selected.id);
    const st = (snap?.signals || []).find((s) => s.id === selected.id);
    return (
      <div className="p-3 space-y-2">
        <div className="label">signal controller</div>
        <div className="text-[13px] font-semibold">{sig?.name || selected.id}</div>
        <Section title="plan">
          <Row k="id" v={sig?.id} />
          <Row k="cycle" v={`${sig?.cycle_s} s`} />
          <Row k="offset" v={`${sig?.offset_s} s`} />
          <Row k="strategy" v={sig?.strategy} />
          <Row k="coordinator" v={sig?.coordinator || '—'} />
        </Section>
        <Section title="state">
          <Row
            k="light"
            v={st?.light?.toUpperCase()}
            tone={st?.light === 'green' ? '#34d399' : st?.light === 'amber' ? '#fbbf24' : '#f87171'}
          />
          <Row k="phase" v={sig?.phases?.[st?.phase]?.name || st?.phase} />
          <Row k="remaining" v={`${(st?.remaining ?? 0).toFixed(1)} s`} />
        </Section>
        <Section title="phases">
          {(sig?.phases || []).map((p) => (
            <div key={p.index} className="mb-1.5 last:mb-0">
              <div className="flex justify-between">
                <span className="text-[11px]">{p.index}. {p.name}</span>
                <span className="font-mono text-[10px] text-[var(--color-muted)]">
                  {p.green}+{p.amber}+{p.all_red}
                </span>
              </div>
              <div className="h-1 mt-1 rounded bg-[var(--color-hair)] overflow-hidden flex">
                <div className="bg-emerald-500" style={{ width: `${(p.green / (p.green + p.amber + p.all_red)) * 100}%` }} />
                <div className="bg-amber-500" style={{ width: `${(p.amber / (p.green + p.amber + p.all_red)) * 100}%` }} />
                <div className="bg-slate-600" style={{ width: `${(p.all_red / (p.green + p.amber + p.all_red)) * 100}%` }} />
              </div>
            </div>
          ))}
        </Section>
      </div>
    );
  }

  if (selected.kind === 'scenario') {
    const sc = (network.scenarios || []).find((s) => s.id === selected.id);
    return (
      <div className="p-3 space-y-2">
        <div className="label">scenario</div>
        <div className="text-[13px] font-semibold">{sc?.name || selected.id}</div>
        <p className="text-[11px] text-[var(--color-muted)] leading-relaxed">{sc?.note}</p>
        {sc?.hour >= 0 && <Row k="hour" v={`${sc.hour}:00`} />}
        {sc?.multipliers && Object.entries(sc.multipliers).map(([k, v]) => (
          <Row key={k} k={k} v={`×${v}`} />
        ))}
      </div>
    );
  }

  // link inspector
  const l = (network.links || []).find((x) => x.id === selected.id);
  if (!l) return <div className="p-3 text-[11px] text-[var(--color-muted)]">link not found</div>;

  const det = (network.links || []).find((x) => x.id === l.id)?.detectors || [];
  const live = (interp && interp.link === l.id && interp.ok) ? interp : null;

  return (
    <div>
      <Section title="link">
        <div className="text-[12px] font-semibold leading-tight mb-1">{l.carriageway}</div>
        <div className="text-[10px] text-[var(--color-muted)] font-mono mb-2">{l.id} · {l.kind}</div>
        <Row k="length drawn" v={`${l.length_m.toFixed(1)} m`} />
        <Row k="length surveyed" v={`${l.length_surveyed_m?.toFixed(1)} m`} />
        <Row k="lanes" v={l.lanes} />
        <Row k="lane index" v={l.lane_index} />
        <Row k="v0" v={`${l.v0_kmph} km/h`} />
        <Row k="speed limit" v={`${l.speed_limit_kmph} km/h`} />
        <Row k="stop line" v={`${l.stop_line_m} m`} />
        <Row k="capacity" v={`${l.capacity_vph} veh/h`} />
        <Row k="from → to" v={`${l.from} → ${l.to}`} />
        <Row k="heat group" v={l.heat_group} />
        <Row k="phases" v={Object.entries(l.phases || {}).map(([m, p]) => `${m}:${p}`).join(' ') || '—'} />
      </Section>

      <Section title="class mix">
        {Object.entries(l.class_mix || {}).sort((a, b) => b[1] - a[1]).map(([k, v]) => (
          <div key={k} className="mb-1">
            <div className="flex justify-between text-[10px]">
              <span className="text-[var(--color-muted)]">{k.replace('_', ' ')}</span>
              <span className="font-mono">{pct(v)}</span>
            </div>
            <div className="h-[3px] bg-[var(--color-hair)] rounded overflow-hidden">
              <div className="h-full bg-sky-500/70" style={{ width: pct(v) }} />
            </div>
          </div>
        ))}
      </Section>

      <Section title={`detector chain · ${det.length}`}>
        {det.length === 0 && <div className="text-[11px] text-[var(--color-muted)]">no detectors</div>}
        {det.map((d) => (
          <Row key={d.id} k={d.id} v={`${d.s_m.toFixed(0)} m`} />
        ))}
        {det.length > 0 && det.length < 3 && (
          <div className="text-[10px] text-amber-300/80 mt-1">
            fewer than 3 checkpoints — interpolation is not meaningful here
          </div>
        )}
      </Section>

      {live && (
        <Section title="reconstructed profile">
          <Row k="method" v="Newton divided differences" mono={false} />
          <Row k="samples" v={live.points} />
          <Row k="rms residual" v={fmt(live.rms_residual, 3)} />
          <div className="mt-2">
            <ProfileChart samples={live.samples} curve={live.curve} />
          </div>
          <div className="text-[10px] text-[var(--color-muted)] mt-1">{live.note}</div>
        </Section>
      )}

      <Section title="geometry">
        <Row k="primitives" v={(l.geometry || []).length} />
        <Row k="curves" v={(l.curves || []).length} />
        {(l.curves || []).map((c, i) => (
          <Row key={i} k={`R ${i + 1}`} v={`${c.R_m} m @ ${c.s0}–${c.s1} m`} />
        ))}
      </Section>
    </div>
  );
}

function ProfileChart({ samples = [], curve = [] }) {
  const w = 280, h = 78, pad = 6;
  const all = [...samples, ...curve].map(([, v]) => v);
  const lo = Math.min(...all, 0);
  const hi = Math.max(...all, 1);
  const xs = curve.length ? curve.map(([s]) => s) : [0];
  const x0 = Math.min(...xs), x1 = Math.max(...xs, 1);
  const px = (s) => pad + ((s - x0) / Math.max(1e-6, x1 - x0)) * (w - pad * 2);
  const py = (v) => h - pad - ((v - lo) / Math.max(1e-6, hi - lo)) * (h - pad * 2);
  const d = curve.map(([s, v], i) => `${i ? 'L' : 'M'}${px(s).toFixed(1)},${py(v).toFixed(1)}`).join(' ');
  return (
    <svg width="100%" viewBox={`0 0 ${w} ${h}`} className="rounded bg-[#0b1220] border hairline">
      {[0.25, 0.5, 0.75].map((f) => (
        <line key={f} x1={pad} x2={w - pad} y1={pad + f * (h - pad * 2)} y2={pad + f * (h - pad * 2)}
          stroke="#1f2f45" strokeWidth="0.5" />
      ))}
      <path d={d} fill="none" stroke="#38bdf8" strokeWidth="1.4" />
      {samples.map(([s, v], i) => (
        <circle key={i} cx={px(s)} cy={py(v)} r="2.4" fill="#0f172a" stroke="#38bdf8" strokeWidth="1.2" />
      ))}
      <text x={pad} y={h - 1} fill="#64748b" fontSize="6" fontFamily="JetBrains Mono">{hi.toFixed(0)}</text>
    </svg>
  );
}

// ---------------------------------------------------------------------------
// alerts
// ---------------------------------------------------------------------------
export function AlertsPanel({ snap, onFocus }) {
  const alerts = (snap?.alerts || []).slice(0, 4);
  if (!alerts.length) {
    return (
      <div className="absolute left-3 bottom-10 px-2.5 py-1.5 rounded bg-[rgba(10,16,26,0.85)] border hairline text-[10px] text-[var(--color-muted)]">
        no active alerts
      </div>
    );
  }
  return (
    <div className="absolute left-3 bottom-10 w-[340px] space-y-1">
      {alerts.map((a, i) => {
        const tone = a.severity === 'critical' ? 'red' : a.severity === 'warn' ? 'amber' : 'accent';
        return (
          <div
            key={i}
            onClick={() => onFocus?.(a.link)}
            className="px-2 py-1.5 rounded bg-[rgba(10,16,26,0.92)] border hairline cursor-pointer hover:border-[var(--color-accent)]"
          >
            <div className="flex items-center gap-1.5">
              <Pill tone={tone}>{a.kind}</Pill>
              <span className="font-mono text-[9px] text-[var(--color-muted)]">t*={a.t.toFixed(3)}s</span>
              <span className="flex-1" />
              <span className="font-mono text-[9px] text-[var(--color-muted)]">
                {a.iterations}it/{a.bisections}bis
              </span>
            </div>
            <div className="text-[10px] mt-0.5 leading-snug text-[var(--color-ink)]">{a.message}</div>
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// demand
// ---------------------------------------------------------------------------
export function DemandPanel({
  network, snap, mode, setMode, hour, setHour, demandMul, setDemandMul,
  approachScales, setApproach, runScenario,
}) {
  const approaches = network?.approaches || [];
  return (
    <div>
      <Section title="demand mode">
        <div className="grid grid-cols-3 gap-1">
          {['surveyed', 'manual', 'scripted'].map((m) => (
            <button
              key={m}
              onClick={() => setMode(m)}
              className={`h-6 rounded-sm border text-[10px] capitalize ${
                mode === m
                  ? 'border-[var(--color-accent)] text-[var(--color-accent)] bg-sky-500/10'
                  : 'border-[var(--color-hair)] text-[var(--color-muted)]'
              }`}
            >{m}</button>
          ))}
        </div>
      </Section>

      <Section title={`hour of day · ${hour.toFixed(1)}:00`}>
        <input
          type="range" min="0" max="23.5" step="0.5" value={hour}
          onChange={(e) => setHour(Number(e.target.value))}
          className="w-full"
        />
        <div className="flex justify-between text-[9px] text-[var(--color-muted)] font-mono mt-1">
          <span>00</span><span>09 AM</span><span>18 PM</span><span>23</span>
        </div>
      </Section>

      <Section title={`global multiplier · ${demandMul.toFixed(2)}×`}>
        <input
          type="range" min="0" max="2" step="0.05" value={demandMul}
          onChange={(e) => setDemandMul(Number(e.target.value))}
          className="w-full"
        />
      </Section>

      <Section title="approach multipliers">
        <div className="space-y-1.5">
          {approaches.map((a) => {
            const v = approachScales[a.id] ?? a.demand_scale ?? 1;
            return (
              <div key={a.id}>
                <div className="flex justify-between items-baseline">
                  <span className="text-[10px] truncate pr-2" title={a.name}>{a.name}</span>
                  <span className="font-mono text-[10px] text-[var(--color-muted)] w-9 text-right">
                    {Math.round(v * 100)}%
                  </span>
                </div>
                <input
                  type="range" min="0" max="2" step="0.05" value={v}
                  onChange={(e) => setApproach(a.id, Number(e.target.value))}
                  className="w-full"
                />
              </div>
            );
          })}
        </div>
      </Section>

      <Section title="scenarios">
        <div className="space-y-1">
          {(network?.scenarios || []).map((s) => (
            <button
              key={s.id}
              onClick={() => runScenario(s.id)}
              className="w-full text-left px-2 py-1.5 rounded-sm border border-[var(--color-hair)] hover:border-[var(--color-accent)]"
            >
              <div className="text-[11px]">{s.name}</div>
              <div className="text-[9px] text-[var(--color-muted)] leading-snug">{s.note}</div>
            </button>
          ))}
        </div>
      </Section>
    </div>
  );
}

// ---------------------------------------------------------------------------
// numerics
// ---------------------------------------------------------------------------
export function NumericsPanel({ snap, integrator, setIntegrator, interp }) {
  return (
    <div>
      <Section title="integrator">
        <div className="grid grid-cols-3 gap-1">
          {['euler', 'rk2', 'rk4'].map((k) => (
            <button
              key={k}
              onClick={() => setIntegrator(k)}
              className={`h-6 rounded-sm border text-[10px] uppercase font-mono ${
                integrator === k
                  ? 'border-[var(--color-accent)] text-[var(--color-accent)] bg-sky-500/10'
                  : 'border-[var(--color-hair)] text-[var(--color-muted)]'
              }`}
            >{k}</button>
          ))}
        </div>
        <div className="text-[10px] text-[var(--color-muted)] mt-1.5 leading-snug">
          RK4 is the production integrator; Euler and RK2 exist so the
          verification suite can show the order difference on identical runs.
        </div>
      </Section>

      <Section title="fixed step">
        <Row k="dt" v="0.05 s" />
        <Row k="steps this run" v={(snap?.steps ?? 0).toLocaleString()} />
        <Row k="sim clock" v={`${fmt(snap?.t, 2)} s`} />
        <Row k="steps per frame @1×" v="2" />
        <Row k="steps per frame @5×" v="50" />
      </Section>

      <Section title="determinism">
        <Row k="state hash" v={snap?.hash != null ? snap.hash.toFixed(9) : '—'} />
        <div className="text-[10px] text-[var(--color-muted)] mt-1 leading-snug">
          The same seed and inputs reproduce this hash exactly.
        </div>
      </Section>

      {interp?.ok && (
        <Section title="interpolation">
          <Row k="link" v={interp.link} />
          <Row k="checkpoints" v={interp.points} />
          <Row k="degree" v={Math.max(0, interp.points - 1)} />
          <Row k="rms residual" v={fmt(interp.rms_residual, 3)} />
          <div className="text-[10px] text-[var(--color-muted)] mt-1">{interp.note}</div>
        </Section>
      )}

      <Section title="verification suite">
        <div className="text-[10px] text-[var(--color-muted)] leading-snug space-y-1">
          <div><code className="font-mono text-[var(--color-ink)]">./trackflow_engine --verify</code></div>
          <div>writes <code className="font-mono">verification/*.csv</code>:</div>
          <ul className="list-disc pl-3.5 space-y-0.5">
            <li>convergence.csv — RK order vs the analytic drag solution</li>
            <li>interpolation.csv — divided-difference residuals</li>
            <li>rootfinding.csv — Newton / bisection / secant / safeguarded</li>
            <li>scenario_comparison.csv — Euler vs RK2 vs RK4 on this site</li>
          </ul>
        </div>
      </Section>
    </div>
  );
}

// ---------------------------------------------------------------------------
// telemetry
// ---------------------------------------------------------------------------
export function Telemetry({ snap, network }) {
  const links = network?.links || [];
  const vph = snap?.arrived != null && snap?.t > 1 ? ((snap.arrived / snap.t) * 3600).toFixed(0) : '—';
  return (
    <Section title="telemetry">
      <Row k="vehicles in network" v={snap?.active ?? 0} />
      <Row k="departed" v={(snap?.departed ?? 0).toLocaleString()} />
      <Row k="arrived" v={(snap?.arrived ?? 0).toLocaleString()} />
      <Row k="throughput" v={`${vph} veh/h`} />
      <Row k="mean delay" v={`${fmt(snap?.mean_delay, 2)} s`} />
      <Row k="lane-level links" v={links.length} />
      <Row k="demand mode" v={snap?.demand_mode} />
      <Row k="speed" v={`${snap?.speed_multiplier ?? 1}×`} />
      <Row k="paused" v={snap?.paused ? 'yes' : 'no'} />
    </Section>
  );
}

// ---------------------------------------------------------------------------
// status bar
// ---------------------------------------------------------------------------
export function StatusBar({ snap, site, connected, siteMeta }) {
  return (
    <div className="shrink-0 h-6 border-t hairline bg-[var(--color-panel)] px-3 flex items-center gap-3 text-[10px] font-mono text-[var(--color-muted)]">
      <span className={connected ? 'text-emerald-400' : 'text-red-400'}>
        {connected ? '● engine linked' : '● engine offline'}
      </span>
      <span className="text-[var(--color-hair)]">|</span>
      <span>{site?.name || siteMeta?.label}</span>
      <span className="text-[var(--color-hair)]">|</span>
      <span>t={fmt(snap?.t, 2)}s</span>
      <span className="text-[var(--color-hair)]">|</span>
      <span>{snap?.integrator?.toUpperCase()}</span>
      <span className="text-[var(--color-hair)]">|</span>
      <span>hash {snap?.hash != null ? snap.hash.toFixed(6) : '—'}</span>
      <span className="flex-1" />
      <span className="truncate max-w-[46ch]">{site?.summary}</span>
    </div>
  );
}
