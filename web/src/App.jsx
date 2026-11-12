import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { io } from "socket.io-client";
import MapCanvas from "./components/MapCanvas.jsx";
import { TopBar, LeftPanel, Inspector, BottomPanel, NumericsPanel } from "./components/Panels.jsx";
import { buildGeometry } from "./lib/geometry.js";

export default function App() {
  const [sites, setSites] = useState([]);
  const [siteId, setSiteId] = useState(null);
  const [snapshot, setSnapshot] = useState(null);
  const [running, setRunning] = useState(true);
  const [speed, setSpeed] = useState(1);
  const [mode, setMode] = useState("surveyed");
  const [cycle, setCycle] = useState(88);
  const [selection, setSelection] = useState(null);
  const [showNumerics, setShowNumerics] = useState(false);
  const [layers, setLayers] = useState({
    base: true,
    heatmap: true,
    network: true,
    signals: true,
    vehicles: true,
    labels: false,
    alerts: true,
  });
  const [events, setEvents] = useState([]);
  const socketRef = useRef(null);

  useEffect(() => {
    fetch("/api/sites")
      .then((r) => r.json())
      .then((data) => {
        setSites(data);
        if (!data.length) return;
        const preferred = data.find((s) => s.id === "connaught_place") || data[0];
        setSiteId(preferred.id);
        const plan = preferred.network?.signal_plans?.[0];
        if (plan?.cycle) setCycle(Math.round(plan.cycle));
      })
      .catch((e) => console.error("catalogue failed", e));
  }, []);

  useEffect(() => {
    const socket = io({ transports: ["websocket", "polling"] });
    socketRef.current = socket;
    socket.on("snapshot", (snap) => {
      setSnapshot(snap);
      if (snap.events?.length) {
        setEvents((prev) => [...snap.events.slice(-4), ...prev].slice(0, 24));
      }
    });
    socket.on("connect", () => {
      if (siteId) socket.emit("select_site", siteId);
    });
    return () => socket.disconnect();
  }, []);

  useEffect(() => {
    if (!siteId) return;
    if (socketRef.current?.connected) socketRef.current.emit("select_site", siteId);
    const chosen = sites.find((s) => s.id === siteId);
    const plan = chosen?.network?.signal_plans?.[0];
    if (plan?.cycle && plan.cycle < 1e6) setCycle(Math.round(plan.cycle));
  }, [siteId]);

  const site = sites.find((s) => s.id === siteId) || null;
  const geometry = useMemo(() => (site ? buildGeometry(site.network) : []), [site]);
  const approaches = snapshot?.approaches || [];

  const onSelect = useCallback((sel) => setSelection(sel), []);
  const onMultiplier = useCallback((id, value) => {
    socketRef.current?.emit("set_multiplier", { id, value });
  }, []);

  useEffect(() => {
    socketRef.current?.emit("set_running", running);
  }, [running]);
  useEffect(() => {
    socketRef.current?.emit("set_speed", speed);
  }, [speed]);
  useEffect(() => {
    socketRef.current?.emit("set_mode", mode);
  }, [mode]);
  useEffect(() => {
    socketRef.current?.emit("set_cycle", cycle);
  }, [cycle]);

  // keep the selected vehicle's telemetry fresh
  const liveSelection = useMemo(() => {
    if (selection?.kind !== "vehicle") return selection;
    const v = snapshot?.vehicles?.find((x) => x[0] === selection.id);
    if (!v) return selection;
    const g = geometry[v[2]];
    return { ...selection, cls: v[1], link: g?.id, lane: v[3], s: v[4], v: v[5], a: v[6] };
  }, [selection, snapshot, geometry]);

  return (
    <div className="flex h-full flex-col bg-asphalt">
      <TopBar
        sites={sites}
        site={site}
        onSite={setSiteId}
        running={running}
        setRunning={setRunning}
        speed={speed}
        setSpeed={setSpeed}
        snap={snapshot}
        mode={mode}
        setMode={setMode}
        cycle={cycle}
        setCycle={setCycle}
      />

      <div className="flex min-h-0 flex-1">
        <LeftPanel
          site={site}
          geometry={geometry}
          snapshot={snapshot}
          layers={layers}
          setLayers={setLayers}
          selection={selection}
          onSelect={onSelect}
        />

        <main className="relative min-w-0 flex-1 bg-[#080d16]">
          {site ? (
            <MapCanvas
              site={site}
              geometry={geometry}
              snapshot={snapshot}
              layers={layers}
              selection={selection}
              onSelect={onSelect}
              pulseEvents={events}
            />
          ) : (
            <div className="flex h-full items-center justify-center text-sm text-muted">loading site…</div>
          )}

          <div className="pointer-events-none absolute left-3 top-3 flex flex-col gap-1">
            <div className="pointer-events-auto flex items-center gap-2 rounded border border-hairline bg-asphalt/80 px-2 py-1">
              <span className="mono text-[10px] uppercase tracking-wider text-muted">sim clock</span>
              <span className="mono text-xs text-ink">{fmt(snapshot?.t || 0)}</span>
              <span className="mono text-[10px] text-muted">
                {snapshot?.mode === "manual" ? "manual demand" : "surveyed demand"}
              </span>
            </div>
            <button className="pointer-events-auto rounded border border-hairline bg-asphalt/80 px-2 py-1 text-[10px] text-muted hover:border-accent hover:text-accent" onClick={() => setShowNumerics(true)}>
              numerics · error analysis
            </button>
          </div>

          <Legend />
        </main>

        <Inspector selection={liveSelection} geometry={geometry} snapshot={snapshot} site={site} />
      </div>

      <BottomPanel snapshot={snapshot} approaches={site?.network?.demand || []} onMultiplier={onMultiplier} mode={mode} />

      {showNumerics && <NumericsPanel onClose={() => setShowNumerics(false)} />}
    </div>
  );
}

function Legend() {
  return (
    <div className="pointer-events-none absolute bottom-3 right-3 rounded border border-hairline bg-asphalt/85 p-2">
      <div className="mono mb-1 text-[9px] uppercase tracking-wider text-muted">density</div>
      <div className="flex items-center gap-1">
        {["#14b8a6", "#eab308", "#dc2626"].map((c) => (
          <span key={c} className="h-1.5 w-8 rounded-sm" style={{ background: c }} />
        ))}
      </div>
      <div className="mono mt-1 flex justify-between text-[8px] text-muted">
        <span>clear</span>
        <span>jam</span>
      </div>
    </div>
  );
}

function fmt(t) {
  const m = Math.floor(t / 60);
  const s = Math.floor(t % 60);
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}
