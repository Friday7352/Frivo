// === server.js ===
// NEW (2.0.0): the Server page (/server). Polls Frivo and draws what it
// says; built from DOM nodes, never HTML strings (device names and log
// lines come from the network).
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const STATUS_MS = 3000;
  const GPU_MS = 4000;
  const SERVICES_MS = 15000;
  const LOG_SHORT = 8;
  const LOG_LONG = 40;

  let last = null;          // the last status Frivo sent
  let logLong = false;
  let stopped = false;      // Stop was pressed here
  let restarting = 0;       // when Restart was pressed (ms), or 0
  let address = "";

  function el(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }

  async function getJson(url, ms) {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), ms || 6000);
    try {
      // The header says it's the Server page asking, so looking at this page
      // doesn't list this PC as using Frivo (note_client in app.py).
      const res = await fetch(url, { cache: "no-store", signal: ctrl.signal, headers: { "X-Frivo-Server-Page": "1" } });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw Object.assign(new Error(data.error || `Frivo answered ${res.status}.`), { status: res.status });
      return data;
    } finally {
      clearTimeout(timer);
    }
  }

  // ---------------------------------------------------------------- words

  function duration(seconds) {
    const s = Math.max(0, Math.round(seconds));
    if (s < 60) return "under a minute";
    const m = Math.floor(s / 60);
    if (m < 60) return `${m} min`;
    const h = Math.floor(m / 60);
    if (h < 48) return `${h} hour${h === 1 ? "" : "s"}`;
    const d = Math.floor(h / 24);
    return `${d} days`;
  }

  function ago(seconds) {
    if (seconds < 90) return "now";
    return `${duration(seconds)} ago`;
  }

  function gb(mb) {
    return `${(mb / 1024).toFixed(1)} GB`;
  }

  function initials(device) {
    const k = device.kind || "";
    if (/iPhone|Android/.test(k)) return "PH";
    if (/iPad/.test(k)) return "TAB";
    return "PC";
  }

  // ---------------------------------------------------------------- top

  function setPill(state, text) {
    const pill = $("srvPill");
    pill.className = `srv-pill${state ? ` is-${state}` : ""}`;
    $("srvPillText").textContent = text;
  }

  function setBanner(text) {
    const b = $("srvBanner");
    b.textContent = text || "";
    b.classList.toggle("is-hidden", !text);
  }

  function drawTop(st) {
    $("srvMeta").textContent = `${st.name} · version ${st.version}`;
    const problems = (st.checks || []).filter((c) => c.state === "bad").length;
    setPill(problems ? "warn" : "ok", `Running · up ${duration(st.uptime_seconds)}`);
    // Restart and Stop only work on this PC (Frivo refuses them from the network).
    for (const id of ["srvRestart", "srvStop"]) {
      const btn = $(id);
      btn.disabled = !st.this_pc;
      btn.title = st.this_pc ? "" : `Only on ${st.name}, the PC Frivo runs on`;
    }
  }

  // ---------------------------------------------------------------- connect

  function drawConnect(st) {
    const urls = st.network_urls || [];
    const here = window.location.origin;
    // The address this page was opened at, when it's one other devices can use.
    const pick = urls.find((u) => u === here) || urls[0] || here;
    if (pick !== address) {
      address = pick;
      $("srvAddress").textContent = pick;
      $("srvQr").src = `/api/qr.png?text=${encodeURIComponent(pick)}`;
    }
    $("srvCode").textContent = st.pairing_code || "—";
    $("srvCodeField").classList.toggle("is-hidden", !st.pairing_code);
  }

  $("srvCopy").addEventListener("click", async () => {
    const btn = $("srvCopy");
    try {
      await navigator.clipboard.writeText(address);
      btn.textContent = "Copied";
    } catch {
      btn.textContent = "Couldn't copy";
    }
    setTimeout(() => { btn.textContent = "Copy address"; }, 1600);
  });

  // ---------------------------------------------------------------- health

  const MARKS = { ok: "✓", warn: "!", bad: "!", off: "–" };

  function drawChecks(st) {
    const list = $("srvChecks");
    list.replaceChildren(...(st.checks || []).map((c) => {
      const li = el("li", `srv-check is-${c.state}`);
      const mark = el("span", "srv-mark", MARKS[c.state] || "");
      mark.setAttribute("aria-hidden", "true");
      const label = el("span", "srv-check-label", c.label);
      const value = el("span", "srv-check-value");
      if (c.link) {
        const a = el("a", null, c.value);
        a.href = c.link;
        value.append(a);
      } else {
        value.textContent = c.value;
      }
      // Said for screen readers, since the mark is only a picture.
      const sr = el("span", "srv-sr", c.state === "ok" ? " (fine)" : c.state === "off" ? " (off)" : " (needs a look)");
      label.append(sr);
      li.append(mark, label, value);
      return li;
    }));
  }

  // ---------------------------------------------------------------- devices

  function drawDevices(st) {
    const devices = st.devices || [];
    const online = devices.filter((d) => d.online);
    $("srvDevicesCount").textContent = online.length === 1 ? "1 device" : `${online.length} devices`;
    $("srvDevicesEmpty").classList.toggle("is-hidden", devices.length > 0);
    $("srvDevices").replaceChildren(...devices.map((d) => {
      const li = el("li", `srv-device${d.online ? "" : " is-away"}`);
      const icon = el("span", "srv-device-icon", initials(d));
      icon.setAttribute("aria-hidden", "true");
      const main = el("div", "srv-device-main");
      const name = d.this_pc ? `This PC · ${d.via}` : (d.name === d.kind ? `${d.kind} · ${d.via}` : `${d.name} · ${d.via}`);
      main.append(el("span", "srv-device-name", name), el("span", "srv-device-sub", d.ip));
      const doing = d.doing ? d.doing : (d.online ? "Open · idle" : `Last seen ${ago(d.seen_seconds)}`);
      li.append(icon, main, el("span", `srv-device-doing${d.doing ? " is-busy" : ""}`, doing));
      return li;
    }));
  }

  // ---------------------------------------------------------------- graphics card

  const SVG = "http://www.w3.org/2000/svg";

  function svg(tag, attrs) {
    const node = document.createElementNS(SVG, tag);
    for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
    return node;
  }

  function drawGpu(data) {
    const graph = $("srvGpuGraph");
    const none = $("srvGpuNone");
    $("srvGpuTitle").textContent = data && data.enabled ? "Graphics card" : "Services";
    if (!data || !data.enabled) {
      graph.replaceChildren();
      $("srvGpuUsed").textContent = "";
      none.textContent = "Nothing Frivo uses runs on a graphics card here. With Ollama or Evora selected in Settings › Providers, the card's memory shows up here.";
      none.classList.remove("is-hidden");
      return;
    }
    const card = data.card;
    const points = (data.history || []).map((p) => ({ t: p.t, used: p.used != null ? p.used : (p.ollama || 0) + (p.evora || 0) + (p.other || 0), total: p.total }));
    const total = (card && card.total_mb) || Math.max(1, ...points.map((p) => p.total || p.used || 0));
    $("srvGpuUsed").textContent = card
      ? `${card.name ? `${card.name} · ` : ""}${gb(card.used_mb)} of ${gb(card.total_mb)}`
      : (data.card_problem || "");
    if (points.length < 2) {
      graph.replaceChildren();
      none.textContent = data.card_problem || "Collecting readings…";
      none.classList.remove("is-hidden");
      return;
    }
    none.classList.add("is-hidden");
    const W = 400;
    const H = 120;
    const t0 = points[0].t;
    const span = Math.max(1, points[points.length - 1].t - t0);
    const xy = points.map((p) => [((p.t - t0) / span) * W, H - Math.min(1, p.used / total) * (H - 6) - 3]);
    const line = xy.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
    const box = svg("svg", { viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: "none", role: "img",
      "aria-label": `Graphics card memory over the last ${Math.round(span / 60) || 1} minutes. Now ${gb(points[points.length - 1].used)} of ${gb(total)}.` });
    for (const y of [H / 4, H / 2, (3 * H) / 4]) box.append(svg("line", { x1: 0, x2: W, y1: y, y2: y, class: "srv-graph-grid" }));
    box.append(svg("polygon", { points: `0,${H} ${line} ${W},${H}`, class: "srv-graph-fill" }));
    box.append(svg("polyline", { points: line, class: "srv-graph-line" }));
    const note = el("p", "srv-graph-note", `Memory in use, last ${Math.round(span / 60) || 1} minutes`);
    graph.replaceChildren(box, note);
  }

  function drawServices(data) {
    const services = (data && data.services) || [];
    $("srvServices").replaceChildren(...services.map((s) => {
      const caveat = s.state === "no key" || s.state === "not downloaded";
      const state = s.idle || caveat ? "" : s.ok ? "ok" : "bad";
      const tile = el("div", `srv-tile${state ? ` is-${state}` : ""}`);
      const what = (s.used_for || []).map((u) => ({ chat: "Replies", translation: "Translation", transcription: "Dictation" }[u] || u)).join(" · ");
      tile.append(
        el("span", "srv-tile-label", what || s.name),
        el("span", "srv-tile-value", s.name),
        el("span", "srv-tile-sub", s.ok ? (s.state || (s.idle ? "Waiting" : "Working")) : (s.state || "Not reachable")));
      tile.title = s.message || s.url || "";
      return tile;
    }));
  }

  // ---------------------------------------------------------------- log

  function drawLog(st) {
    const lines = (st.log || []).slice(0, logLong ? LOG_LONG : LOG_SHORT);
    $("srvLogEmpty").classList.toggle("is-hidden", lines.length > 0);
    $("srvLogMore").classList.toggle("is-hidden", (st.log || []).length <= LOG_SHORT);
    $("srvLogMore").textContent = logLong ? "Show less" : "Show more";
    const d = new Date();
    const today = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    $("srvLog").replaceChildren(...lines.map((l) => {
      const li = el("li", `is-${l.level}`);
      li.append(
        el("span", "srv-log-time", l.date === today ? l.time : `${l.date.slice(5)} ${l.time}`),
        el("span", "srv-log-level", l.level),
        el("span", "srv-log-text", l.text));
      return li;
    }));
  }

  $("srvLogMore").addEventListener("click", () => {
    logLong = !logLong;
    if (last) drawLog(last);
  });

  // ---------------------------------------------------------------- restart / stop

  async function post(url) {
    const res = await fetch(url, { method: "POST", headers: { "X-Frivo-Server-Page": "1" } });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || `Frivo answered ${res.status}.`);
    return data;
  }

  $("srvRestart").addEventListener("click", async () => {
    const btn = $("srvRestart");
    btn.disabled = true;
    try {
      await post("/api/server/restart");
      restarting = Date.now();
      setPill("warn", "Restarting…");
      setBanner("Frivo is restarting. Devices reconnect by themselves in a few seconds.");
    } catch (err) {
      setBanner(err.message);
      btn.disabled = false;
    }
  });

  $("srvStop").addEventListener("click", async () => {
    const who = last && (last.devices || []).filter((d) => d.online && !d.this_pc).length;
    const warning = who ? `${who === 1 ? "1 device is" : `${who} devices are`} using Frivo. Stop it anyway?` : "Stop Frivo?";
    if (!window.confirm(`${warning} Start it again from the Frivo shortcut or the tray icon.`)) return;
    try {
      await post("/api/server/stop");
      stopped = true;
      document.querySelector(".srv").classList.add("is-down");
      setPill("bad", "Stopped");
      setBanner("Frivo is stopped. Start it again from the Frivo shortcut or the tray icon; this page picks it up by itself.");
    } catch (err) {
      setBanner(err.message);
    }
  });

  // ---------------------------------------------------------------- polling

  async function pollStatus() {
    try {
      const st = await getJson("/api/server/status");
      const cameBack = stopped || restarting || (last && last.uptime_seconds > st.uptime_seconds);
      last = st;
      if (cameBack) {
        stopped = false;
        restarting = 0;
        document.querySelector(".srv").classList.remove("is-down");
        setBanner("");
      }
      drawTop(st);
      drawConnect(st);
      drawChecks(st);
      drawDevices(st);
      drawLog(st);
    } catch {
      if (restarting) {
        setPill("warn", "Restarting…");
      } else if (!stopped) {
        document.querySelector(".srv").classList.add("is-down");
        setPill("bad", "Not answering");
        setBanner("Frivo isn't answering. It may be stopped, or still starting.");
      }
    }
  }

  async function pollGpu() {
    if (stopped) return;
    try { drawGpu(await getJson("/api/gpu")); } catch { /* the status poll says so */ }
  }

  async function pollServices() {
    if (stopped) return;
    try { drawServices(await getJson("/api/local-status", 8000)); } catch { /* the status poll says so */ }
  }

  pollStatus();
  pollGpu();
  pollServices();
  setInterval(pollStatus, STATUS_MS);
  setInterval(pollGpu, GPU_MS);
  setInterval(pollServices, SERVICES_MS);
}());
