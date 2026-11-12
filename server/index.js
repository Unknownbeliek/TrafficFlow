// Trackflow bridge: owns the C++ engine process and relays its stdio JSON to
// the browser over WebSocket, plus a REST fallback for the static site data.
import express from 'express';
import { WebSocketServer } from 'ws';
import { spawn } from 'node:child_process';
import { createInterface } from 'node:readline';
import path from 'node:path';
import fs from 'node:fs';
import os from 'node:os';

const ROOT = path.resolve(import.meta.dirname, '..');
const ENGINE = process.env.TRACKFLOW_ENGINE || path.join(ROOT, 'engine', 'trackflow_engine');
const DATA = process.env.TRACKFLOW_DATA || path.join(ROOT, 'site-data');
const PORT = Number(process.env.PORT || 5173);
const SITES = ['kalindi_kunj', 'ito', 'gaur_city', 'connaught_place', 'botanical_okhla'];

// ---------------------------------------------------------------------------
// engine process
// ---------------------------------------------------------------------------
class Engine {
  constructor() {
    this.proc = null;
    this.pending = new Map();
    this.site = null;
    this.snapshot = null;
    this.siteInfo = null;
    this.subscribers = new Set();
    this.alive = false;
    this.start('kalindi_kunj');
  }

  start(site) {
    // bump the generation so the outgoing process's exit handler cannot trigger
    // a respawn: only the current generation is allowed to restart itself
    this.generation = (this.generation || 0) + 1;
    const gen = this.generation;
    if (this.proc) {
      const old = this.proc;
      old.removeAllListeners('exit');
      try { old.kill('SIGTERM'); } catch { /* already gone */ }
      this.proc = null;
    }
    this.site = site;
    const args = ['--stdio', '--data', DATA, '--site', site];
    this.proc = spawn(ENGINE, args, { stdio: ['pipe', 'pipe', 'pipe'] });
    this.alive = true;

    const rl = createInterface({ input: this.proc.stdout });
    rl.on('line', (line) => {
      let msg;
      try { msg = JSON.parse(line); } catch { return; }
      if (msg.type === 'site') {
        this.siteInfo = msg;
        this.broadcast({ type: 'site', site: msg });
      } else if (msg.type === 'snapshot') {
        this.snapshot = msg;
        this.broadcast(msg);
      } else if (msg.type === 'error') {
        this.broadcast(msg);
      } else {
        this.broadcast(msg);
      }
      const waiters = this.pending.get(msg.type);
      if (waiters && waiters.length) waiters.shift()(msg);
    });

    this.proc.stderr.on('data', (d) => {
      console.error('[engine]', d.toString().trim());
    });
    this.proc.on('exit', (code) => {
      if (gen !== this.generation) return;   // a superseded process: ignore
      this.alive = false;
      this.broadcast({ type: 'engine_down', code });
      // restart the engine so the demo never sits on a dead process
      setTimeout(() => {
        if (gen === this.generation && !this.alive) this.start(this.site || 'kalindi_kunj');
      }, 500);
    });
  }

  broadcast(msg) {
    const payload = JSON.stringify(msg);
    for (const ws of this.subscribers) {
      if (ws.readyState === 1) ws.send(payload);
    }
  }

  send(cmd) {
    if (!this.alive || !this.proc) return false;
    this.proc.stdin.write(JSON.stringify(cmd) + '\n');
    return true;
  }
}

const engine = new Engine();

// ---------------------------------------------------------------------------
// HTTP
// ---------------------------------------------------------------------------
const app = express();
app.use(express.json());

app.get('/api/health', (_req, res) => {
  res.json({
    ok: engine.alive,
    site: engine.site,
    engine: ENGINE,
    engine_binary: fs.existsSync(ENGINE),
    sites: SITES,
    uptime_s: Math.round(process.uptime()),
  });
});

app.get('/api/sites', (_req, res) => {
  const out = SITES.map((id) => {
    const file = path.join(DATA, id, 'network.json');
    if (!fs.existsSync(file)) return { id, available: false };
    const net = JSON.parse(fs.readFileSync(file, 'utf8'));
    return {
      id,
      available: true,
      name: net.site.name,
      kind: net.site.kind,
      summary: net.site.summary,
      links: net.links.length,
      nodes: net.nodes.length,
      movements: net.demand.length,
      peak_vph: net.demand.reduce((a, d) => a + d.flow_vph_peak, 0),
      imagery: net.imagery,
      display: net.display,
      image: net.site.image,
    };
  });
  res.json(out);
});

app.get('/api/site/:id', (req, res) => {
  const file = path.join(DATA, req.params.id, 'network.json');
  if (!fs.existsSync(file)) return res.status(404).json({ error: 'no such site' });
  res.json(JSON.parse(fs.readFileSync(file, 'utf8')));
});

app.get('/api/calibration/:id', (req, res) => {
  const file = path.join(DATA, req.params.id, 'calibration.json');
  if (!fs.existsSync(file)) return res.status(404).json({ error: 'no calibration' });
  res.json(JSON.parse(fs.readFileSync(file, 'utf8')));
});

app.get('/api/image/:id', (req, res) => {
  // serve the committed satellite capture for a site
  const map = {
    kalindi_kunj: 'KalindiKunj.png',
    ito: 'ITO.png',
    gaur_city: 'GaurCIty_charmurti.png',
    connaught_place: 'CP.png',
    botanical_okhla: 'Botanical_interchange.png',
  };
  const name = map[req.params.id];
  if (!name) return res.status(404).end();
  res.sendFile(path.join(ROOT, 'section_img', name));
});

// the built client (npm run build) is served from dist/; fall back to the
// source folder so a checkout without a build still opens
const DIST = path.join(ROOT, 'dist');
const CLIENT = fs.existsSync(path.join(DIST, 'index.html')) ? DIST : path.join(ROOT, 'client');
app.use(express.static(CLIENT));

const server = app.listen(PORT, '0.0.0.0', () => {
  console.log(`Trackflow bridge on http://0.0.0.0:${PORT}`);
  console.log(`  engine  ${ENGINE}`);
  console.log(`  data    ${DATA}`);
});

// ---------------------------------------------------------------------------
// WebSocket
// ---------------------------------------------------------------------------
const wss = new WebSocketServer({ server, path: '/ws' });
wss.on('connection', (ws) => {
  engine.subscribers.add(ws);
  ws.send(JSON.stringify({ type: 'hello', sites: SITES, engine: engine.alive }));
  if (engine.siteInfo) ws.send(JSON.stringify({ type: 'site', site: engine.siteInfo }));
  if (engine.snapshot) ws.send(JSON.stringify(engine.snapshot));

  ws.on('message', (raw) => {
    let msg;
    try { msg = JSON.parse(raw.toString()); } catch { return; }
    // a "tick" from the browser drives the animation clock: one frame at the
    // selected speed multiplier.  The client is the clock, the engine is the
    // source of truth (PRD section 8).
    if (msg.cmd === 'tick') {
      engine.send({ cmd: 'tick', seconds: msg.seconds ?? 0.1 });
    } else if (msg.cmd === 'load_site') {
      engine.start(msg.site);
    } else {
      engine.send(msg);
    }
  });
  ws.on('close', () => engine.subscribers.delete(ws));
});

function shutdown() {
  try { engine.proc?.kill('SIGTERM'); } catch { /* ignore */ }
  server.close(() => process.exit(0));
  setTimeout(() => process.exit(0), 500);
}
process.on('SIGINT', shutdown);
process.on('SIGTERM', shutdown);

export { app, engine };
