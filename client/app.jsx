import React, { useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './styles.css';
import Canvas from './canvas.jsx';
import {
  TopBar, ObjectTree, Inspector, Telemetry, AlertsPanel,
  DemandPanel, NumericsPanel, StatusBar,
} from './panels.jsx';

const SITES = [
  { id: 'kalindi_kunj', label: 'Kalindi Kunj', sub: 'bridge bottleneck' },
  { id: 'connaught_place', label: 'Connaught Place', sub: 'Inner / Outer Circles' },
  { id: 'ito', label: 'ITO', sub: 'multi-way grid' },
  { id: 'gaur_city', label: 'Gaur City Char Murti', sub: 'signalised roundabout' },
  { id: 'botanical_okhla', label: 'Botanical Okhla', sub: 'cloverleaf' },
];

// ---------------------------------------------------------------------------
// live socket: one connection, reconnecting, with a small command queue so a
// slider drag does not flood the engine
// ---------------------------------------------------------------------------
function useTrackflow() {
  const [connected, setConnected] = useState(false);
  const [site, setSite] = useState(null);
  const [snap, setSnap] = useState(null);
  const [detectors, setDetectors] = useState({});
  const [interp, setInterp] = useState(null);
  const [sites, setSites] = useState(SITES);
  const wsRef = useRef(null);
  const queueRef = useRef([]);
  const timerRef = useRef(null);

  useEffect(() => {
    let closed = false;
    let retry = null;
    const connect = () => {
      const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
      const ws = new WebSocket(`${proto}//${location.host}/ws`);
      wsRef.current = ws;
      ws.onopen = () => { setConnected(true); flush(); };
      ws.onclose = () => {
        setConnected(false);
        if (!closed) retry = setTimeout(connect, 900);
      };
      ws.onmessage = (ev) => {
        let msg;
        try { msg = JSON.parse(ev.data); } catch { return; }
        if (msg.type === 'hello') { if (msg.sites) setSites(SITES); }
        else if (msg.type === 'site') setSite(msg.site);
        else if (msg.type === 'snapshot') setSnap(msg);
        else if (msg.type === 'interpolation') setInterp(msg);
        else if (msg.type === 'detectors') {
          const next = {};
          for (const r of msg.readings) (next[r.link] ||= []).push(r);
          setDetectors(next);
        }
      };
    };
    const flush = () => {
      const ws = wsRef.current;
      if (!ws || ws.readyState !== 1) return;
      while (queueRef.current.length) ws.send(JSON.stringify(queueRef.current.shift()));
    };
    connect();
    timerRef.current = setInterval(flush, 40);
    return () => {
      closed = true;
      clearTimeout(retry);
      clearInterval(timerRef.current);
      wsRef.current?.close();
    };
  }, []);

  const send = (msg) => { queueRef.current.push(msg); };
  return { connected, site, snap, sites, send, detectors, interp, setInterp };
}

// ---------------------------------------------------------------------------
// animation clock: the client decides how much simulated time a frame is worth
// ---------------------------------------------------------------------------
function useClock(send, running, speed, paused) {
  useEffect(() => {
    if (!running || paused) return;
    let raf = 0;
    let last = performance.now();
    const loop = (now) => {
      const dtWall = Math.min(0.25, (now - last) / 1000);
      last = now;
      // 1x = 0.1 s simulated per 0.1 s of wall time, scaled by the multiplier
      send({ cmd: 'tick', seconds: dtWall * speed });
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [running, speed, paused, send]);
}

function App() {
  const tf = useTrackflow();
  const { snap, site, send, detectors, interp, setInterp } = tf;
  const [siteId, setSiteId] = useState('kalindi_kunj');
  const [running, setRunning] = useState(true);
  const [paused, setPaused] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [selected, setSelected] = useState(null);       // { kind, id }
  const [overlay, setOverlay] = useState('speed');      // speed | density | none
  const [view, setView] = useState('satellite');        // satellite | schematic
  const [rightTab, setRightTab] = useState('inspector');
  const [demandMode, setDemandMode] = useState('surveyed');
  const [hour, setHour] = useState(9);
  const [demandMul, setDemandMul] = useState(1);
  const [approachScales, setApproachScales] = useState({});
  const [integrator, setIntegrator] = useState('rk4');
  const [showSignals, setShowSignals] = useState(true);
  const [showLabels, setShowLabels] = useState(false);

  useClock(send, running, speed, paused);

  // keep local control state in step with whatever the engine reports
  useEffect(() => {
    if (!snap) return;
    setDemandMode(snap.demand_mode);
    setDemandMul(snap.demand_multiplier);
    setHour(snap.hour);
    setIntegrator(snap.integrator);
    setPaused(snap.paused);
    if (snap.approach_scales) setApproachScales(snap.approach_scales);
  }, [snap?.demand_mode, snap?.integrator, snap?.paused, snap?.hour]);

  // fetch the static network once per site for the tree and the schematic view
  const [network, setNetwork] = useState(null);
  useEffect(() => {
    let live = true;
    fetch(`/api/site/${siteId}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((j) => { if (live) setNetwork(j); })
      .catch(() => {});
    return () => { live = false; };
  }, [siteId]);

  useEffect(() => {
    send({ cmd: 'load_site', site: siteId });
    setSelected(null);
    setInterp(null);
  }, [siteId]); // eslint-disable-line react-hooks/exhaustive-deps

  // detector polling: one window per second is enough for the heatmap
  useEffect(() => {
    const id = setInterval(() => send({ cmd: 'detector_window' }), 1000);
    return () => clearInterval(id);
  }, [send]);

  const changeSite = (id) => { setSiteId(id); setRunning(true); };
  const setSpeedMul = (k) => { setSpeed(k); send({ cmd: 'set_speed_multiplier', value: k }); };
  const togglePause = () => {
    const next = !paused;
    setPaused(next);
    send({ cmd: next ? 'pause' : 'resume' });
  };
  const doReset = () => send({ cmd: 'reset', seed: 12345 });
  const doStep = () => send({ cmd: 'step', steps: 2 });
  const changeMode = (m) => { setDemandMode(m); send({ cmd: 'set_demand_mode', mode: m }); };
  const changeHour = (h) => { setHour(h); send({ cmd: 'set_hour', value: h }); };
  const changeDemand = (v) => { setDemandMul(v); send({ cmd: 'set_demand_multiplier', value: v }); };
  const changeApproach = (id, v) => {
    setApproachScales((s) => ({ ...s, [id]: v }));
    send({ cmd: 'set_approach_scale', approach: id, value: v });
  };
  const changeIntegrator = (k) => { setIntegrator(k); send({ cmd: 'set_integrator', value: k }); };
  const runScenario = (id) => send({ cmd: 'scenario', id });

  const inspectLink = (id) => {
    setSelected({ kind: 'link', id });
    setRightTab('inspector');
    send({ cmd: 'interpolate', link: id });
  };

  const siteMeta = useMemo(
    () => tf.sites.find((s) => s.id === siteId) || { label: siteId, sub: '' },
    [tf.sites, siteId],
  );

  return (
    <div className="h-full flex flex-col bg-[var(--color-bg)] text-[var(--color-ink)]">
      <TopBar
        sites={tf.sites}
        siteId={siteId}
        onSite={changeSite}
        connected={tf.connected}
        running={running}
        setRunning={setRunning}
        paused={paused}
        onPause={togglePause}
        speed={speed}
        onSpeed={setSpeedMul}
        onReset={doReset}
        onStep={doStep}
        overlay={overlay}
        setOverlay={setOverlay}
        view={view}
        setView={setView}
        showSignals={showSignals}
        setShowSignals={setShowSignals}
        showLabels={showLabels}
        setShowLabels={setShowLabels}
        snap={snap}
      />

      <div className="flex-1 min-h-0 flex">
        <ObjectTree
          network={network}
          siteMeta={siteMeta}
          snap={snap}
          detectors={detectors}
          selected={selected}
          onSelect={(sel) => { setSelected(sel); setRightTab('inspector'); }}
          onInspectLink={inspectLink}
        />

        <div className="flex-1 min-w-0 relative">
          <Canvas
            siteId={siteId}
            network={network}
            site={site}
            snap={snap}
            detectors={detectors}
            overlay={overlay}
            view={view}
            showSignals={showSignals}
            showLabels={showLabels}
            selected={selected}
            onSelect={setSelected}
            interp={interp}
          />
          <AlertsPanel snap={snap} onFocus={(link) => inspectLink(link)} />
        </div>

        <div className="w-[330px] shrink-0 border-l hairline bg-[var(--color-panel)] flex flex-col">
          <div className="flex border-b hairline">
            {[
              ['inspector', 'Inspector'],
              ['demand', 'Demand'],
              ['numerics', 'Numerics'],
            ].map(([k, label]) => (
              <button
                key={k}
                onClick={() => setRightTab(k)}
                className={`flex-1 px-2 py-2 text-[11px] font-semibold tracking-wide uppercase border-b-2 ${
                  rightTab === k
                    ? 'border-[var(--color-accent)] text-[var(--color-accent)]'
                    : 'border-transparent text-[var(--color-muted)] hover:text-[var(--color-ink)]'
                }`}
              >
                {label}
              </button>
            ))}
          </div>
          <div className="flex-1 min-h-0 overflow-y-auto thin-scroll">
            {rightTab === 'inspector' && (
              <Inspector
                selected={selected}
                network={network}
                snap={snap}
                interp={interp}
                onInspectLink={inspectLink}
              />
            )}
            {rightTab === 'demand' && (
              <DemandPanel
                network={network}
                snap={snap}
                mode={demandMode}
                setMode={changeMode}
                hour={hour}
                setHour={changeHour}
                demandMul={demandMul}
                setDemandMul={changeDemand}
                approachScales={approachScales}
                setApproach={changeApproach}
                runScenario={runScenario}
              />
            )}
            {rightTab === 'numerics' && (
              <NumericsPanel
                snap={snap}
                integrator={integrator}
                setIntegrator={changeIntegrator}
                interp={interp}
              />
            )}
            <Telemetry snap={snap} network={network} />
          </div>
        </div>
      </div>

      <StatusBar snap={snap} site={site} connected={tf.connected} siteMeta={siteMeta} />
    </div>
  );
}

createRoot(document.getElementById('root')).render(<App />);
