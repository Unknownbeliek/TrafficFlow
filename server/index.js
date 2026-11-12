// Trackflow bridge.
//
//   browser  <—socket.io—>  this server  <—NDJSON over stdio—>  C++ engine
//
// Responsibilities: keep exactly one engine process alive for the selected
// site, tick it at a fixed wall-clock rate, and fan snapshots out to clients.
// It never simulates anything itself — simulated time belongs to the engine.
import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import express from "express";
import { Server } from "socket.io";
import http from "node:http";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..");
const ENGINE = path.join(ROOT, "engine", "trackflow");
const SITES_DIR = path.join(ROOT, "sites");
const WEB_DIST = path.join(ROOT, "webroot");
const PORT = Number(process.env.PORT || 3000);

// --------------------------------------------------------------------------
// site catalogue
// --------------------------------------------------------------------------
function listSites() {
  if (!fs.existsSync(SITES_DIR)) return [];
  return fs
    .readdirSync(SITES_DIR)
    .filter((d) => fs.existsSync(path.join(SITES_DIR, d, "network.json")))
    .map((d) => {
      const net = JSON.parse(fs.readFileSync(path.join(SITES_DIR, d, "network.json"), "utf8"));
      const calPath = path.join(SITES_DIR, d, "calibration.json");
      const cal = fs.existsSync(calPath) ? JSON.parse(fs.readFileSync(calPath, "utf8")) : {};
      // Prefer the clean crop (section_img/<id>/base.png); fall back to the
      // original screenshot named in network.json until the crop is dropped in.
      const crop = path.join(ROOT, "section_img", d, "base.png");
      const rel = String(net.source_image || net.image || "").replace(/^section_img\//, "");
      const image = fs.existsSync(crop) ? `/assets/${d}/base.png` : `/assets/${rel}`;
      return {
        id: d,
        name: net.name,
        kind: net.kind,
        image,
        network: net,
        calibration: cal,
        notes: net.notes || [],
      };
    })
    .sort((a, b) => a.name.localeCompare(b.name));
}

const SITES = listSites();
const DEFAULT_SITE = "connaught_place";

// --------------------------------------------------------------------------
// engine process
// --------------------------------------------------------------------------
class Engine {
  constructor(siteId) {
    this.siteId = siteId;
    this.proc = null;
    this.buffer = "";
    this.ready = false;
    this.last = null;
    this.events = [];
    this.pending = [];
  }

  start() {
    const sitePath = path.join(SITES_DIR, this.siteId, "network.json");
    this.proc = spawn(ENGINE, ["serve", sitePath], { stdio: ["pipe", "pipe", "pipe"] });
    this.proc.stdout.setEncoding("utf8");
    this.proc.stdout.on("data", (chunk) => this.onData(chunk));
    this.proc.stderr.on("data", (d) => console.error("[engine]", String(d).trim()));
    this.proc.on("exit", (code) => {
      console.log(`[engine] ${this.siteId} exited (${code})`);
    });
    this.ready = true;
  }

  onData(chunk) {
    this.buffer += chunk;
    let idx;
    while ((idx = this.buffer.indexOf("\n")) >= 0) {
      const line = this.buffer.slice(0, idx).trim();
      this.buffer = this.buffer.slice(idx + 1);
      if (!line) continue;
      let msg;
      try {
        msg = JSON.parse(line);
      } catch {
        continue;
      }
      if (msg.ready !== undefined) continue;
      if (msg.t !== undefined) {
        this.last = msg;
        if (msg.events && msg.events.length) {
          for (const e of msg.events) this.events.push(e);
          if (this.events.length > 60) this.events = this.events.slice(-60);
        }
      }
    }
  }

  send(cmd) {
    if (!this.proc || this.proc.killed) return;
    this.proc.stdin.write(JSON.stringify(cmd) + "\n");
  }

  stop() {
    if (!this.proc) return;
    try {
      this.send({ cmd: "quit" });
      this.proc.kill("SIGTERM");
    } catch {}
    this.proc = null;
  }
}

let engine = null;
let running = true;
let speed = 1;
let tickTimer = null;

function startSite(siteId) {
  if (engine) engine.stop();
  engine = new Engine(siteId);
  engine.start();
  engine.send({ cmd: "set_speed", value: speed });
  engine.send({ cmd: "resume" });
  running = true;
}

// Fixed 10 Hz tick. Playback speed multiplies how much simulated time each
// tick advances; the engagement of signals and braking stays in the engine.
const TICK_MS = 100;
function startTicker(io) {
  if (tickTimer) clearInterval(tickTimer);
  tickTimer = setInterval(() => {
    if (!engine || !engine.ready) return;
    if (running) engine.send({ cmd: "advance", dt: TICK_MS / 1000 });
    if (engine.last) {
      io.emit("snapshot", { ...engine.last, events: engine.events.slice(-8) });
    }
  }, TICK_MS);
}

// --------------------------------------------------------------------------
// http + sockets
// --------------------------------------------------------------------------
const app = express();
app.use("/assets", express.static(path.join(ROOT, "section_img")));
app.use("/reports", express.static(path.join(ROOT, "engine", "reports")));
app.get("/api/sites", (_req, res) => {
  res.json(SITES.map(({ network, ...rest }) => ({ ...rest, network })));
});
app.get("/api/sites/:id", (req, res) => {
  const site = SITES.find((s) => s.id === req.params.id);
  if (!site) return res.status(404).json({ error: "unknown site" });
  res.json(site);
});
app.get("/api/health", (_req, res) => res.json({ ok: true, sites: SITES.map((s) => s.id) }));

if (fs.existsSync(WEB_DIST)) {
  app.use(express.static(WEB_DIST));
  app.get("*", (_req, res) => res.sendFile(path.join(WEB_DIST, "index.html")));
} else {
  app.get("/", (_req, res) =>
    res
      .status(200)
      .send(
        "<body style='font-family:monospace;background:#0f172a;color:#e5edf7;padding:40px'>" +
          "<h1>Trackflow API is up</h1><p>The dashboard has not been built yet. " +
          "Run <code>cd web &amp;&amp; npm install &amp;&amp; npm run build</code>, then reload.</p>" +
          `<p>Sites: ${SITES.map((s) => s.id).join(", ")}</p></body>`
      )
  );
}

const server = http.createServer(app);
const io = new Server(server, { cors: { origin: "*" } });

io.on("connection", (socket) => {
  if (!engine && SITES.length) startSite(DEFAULT_SITE);
  socket.emit("catalogue", SITES.map(({ network, calibration, ...rest }) => ({ ...rest, network, calibration })));
  if (engine?.last) socket.emit("snapshot", { ...engine.last, events: engine.events.slice(-8) });

  socket.on("select_site", (siteId) => {
    if (!SITES.find((s) => s.id === siteId)) return;
    startSite(siteId);
    io.emit("site_changed", siteId);
  });
  socket.on("set_running", (v) => {
    running = !!v;
    if (!engine) return;
    engine.send({ cmd: running ? "resume" : "pause" });
  });
  socket.on("set_speed", (v) => {
    speed = Math.max(0.1, Math.min(10, Number(v) || 1));
    engine?.send({ cmd: "set_speed", value: speed });
  });
  socket.on("set_mode", (mode) => engine?.send({ cmd: "set_demand_mode", mode }));
  socket.on("set_multiplier", ({ id, value }) =>
    engine?.send({ cmd: "set_multiplier", id, value: Number(value) })
  );
  socket.on("set_cycle", (value) => engine?.send({ cmd: "set_cycle", value: Number(value) }));
  socket.on("reset", () => engine?.send({ cmd: "reset" }));
});

startTicker(io);

server.listen(PORT, "0.0.0.0", () => {
  console.log(`Trackflow bridge on http://0.0.0.0:${PORT}`);
  console.log(`  engine : ${ENGINE}`);
  console.log(`  sites  : ${SITES.map((s) => s.id).join(", ")}`);
  if (SITES.length) startSite(DEFAULT_SITE);
});
