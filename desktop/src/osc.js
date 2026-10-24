'use strict';
/*
  NEW (2.0.0): FrivOSC, built into the app.

  The bridge between VRChat and Frivo, which used to be a separate install
  (the FrivOSC repository, frivosc_service.py). The app is almost always
  running on the PC that plays VRChat, so it does the job itself now:

      VRChat  --OSC 9001-->  the app  --HTTPS-->  Frivo    (mute state)
      VRChat  <--OSC 9000--  the app  <--HTTPS--  Frivo    (chatbox, typing,
                                                            unmute)

  The same contract as FrivOSC (/api/frivosc/* on Frivo), so Frivo can't
  tell them apart and nothing on its side changed. Ported from
  frivosc_service.py: the OSC encoder and parser, the chatbox pager, the
  paced sender, the one-way unmute tap and the bridge loop, with their
  reasons kept beside them.

  Two things are new:
    - It only runs while VRChat is running on this PC. The app on the PC
      Frivo runs on (no VRChat there) must not collect the chatbox messages
      meant for the app on the VRChat PC, and nothing should sit on VRChat's
      port while VRChat isn't using it.
    - It stands aside while the separate FrivOSC is running, rather than the
      two fighting over the port and the outbox.

  Frivo is reached through the app's own connection (the certificate the
  app already trusts), never with verification turned off.
*/

const dgram = require('dgram');

const CHATBOX_LIMIT = 144;
const MIN_GAP_SECONDS = 1.5;
const PAGE_SECONDS_SPEAKING = 1.6;
const PAGE_SECONDS_SILENT = 4.0;
const MUTE_ADDRESS = '/avatar/parameters/MuteSelf';

// ---------------------------------------------------------------- OSC wire format

// OSC strings are null-terminated and padded to a multiple of 4 bytes.
function oscString(text) {
  const data = Buffer.from(`${text}\0`, 'utf8');
  const padding = (4 - (data.length % 4)) % 4;
  return Buffer.concat([data, Buffer.alloc(padding)]);
}

// Arguments: true/false (T/F, never 1/0: VRChat rejects the wrong tag),
// whole numbers as int32, other numbers as float32, anything else a string.
function oscMessage(address, ...args) {
  let tags = ',';
  const payload = [];
  for (const arg of args) {
    if (typeof arg === 'boolean') {
      tags += arg ? 'T' : 'F';
    } else if (typeof arg === 'number' && Number.isInteger(arg)) {
      tags += 'i';
      const b = Buffer.alloc(4); b.writeInt32BE(arg); payload.push(b);
    } else if (typeof arg === 'number') {
      tags += 'f';
      const b = Buffer.alloc(4); b.writeFloatBE(arg); payload.push(b);
    } else {
      tags += 's';
      payload.push(oscString(String(arg)));
    }
  }
  return Buffer.concat([oscString(address), oscString(tags), ...payload]);
}

function oscReadString(data, offset) {
  const end = data.indexOf(0, offset);
  if (end < 0) throw new RangeError('unterminated string');
  const text = data.toString('utf8', offset, end);
  const consumed = end + 1 - offset;
  return [text, offset + consumed + ((4 - (consumed % 4)) % 4)];
}

// One incoming message as [address, args]. Anything that doesn't parse is
// ['', []]: an open UDP port has to expect noise.
function oscParseMessage(data) {
  try {
    let [address, offset] = oscReadString(data, 0);
    if (!address.startsWith('/') || offset >= data.length || data[offset] !== 0x2c) return [address, []];
    let tags;
    [tags, offset] = oscReadString(data, offset);
    const args = [];
    for (const tag of tags.slice(1)) {
      if (tag === 'i') { args.push(data.readInt32BE(offset)); offset += 4; }
      else if (tag === 'f') { args.push(data.readFloatBE(offset)); offset += 4; }
      else if (tag === 's') { let v; [v, offset] = oscReadString(data, offset); args.push(v); }
      else if (tag === 'T') args.push(true);
      else if (tag === 'F') args.push(false);
      else if (tag === 'N' || tag === 'I') args.push(null);
      else break;   // blobs and rarer tags aren't needed for avatar parameters
    }
    return [address, args];
  } catch {
    return ['', []];
  }
}

/*
  Chatbox-sized pages, broken at sentence ends where possible and word
  boundaries otherwise, with " (1/3)" counters when there's more than one.
  The same as chatbox_pages() in frivosc_service.py and app.py (the tests
  compare them).
*/
function chatboxPages(text, limit = CHATBOX_LIMIT) {
  text = String(text || '').split(/\s+/).filter(Boolean).join(' ');
  if (!text) return [];
  if (text.length <= limit) return [text];

  const sentences = text.match(/[^.!?]+[.!?]*|[.!?]+/g) || [text];
  function pack(budget) {
    const pages = [];
    let current = '';
    for (let sentence of sentences) {
      sentence = sentence.trim();
      while (sentence.length > budget) {
        let cut = sentence.lastIndexOf(' ', budget);
        if (cut <= 0) cut = budget;
        if (current) { pages.push(current); current = ''; }
        pages.push(sentence.slice(0, cut).trim());
        sentence = sentence.slice(cut).trim();
      }
      if (!sentence) continue;
      if (!current) current = sentence;
      else if (current.length + 1 + sentence.length <= budget) current = `${current} ${sentence}`;
      else { pages.push(current); current = sentence; }
    }
    if (current) pages.push(current);
    return pages;
  }

  let pages = pack(limit);
  if (pages.length <= 1) return pages;
  for (let i = 0; i < 3; i++) {
    const suffix = ` (${pages.length}/${pages.length})`.length;
    const repacked = pack(limit - suffix);
    const settled = repacked.length === pages.length;
    pages = repacked;
    if (settled) break;
  }
  return pages.map((p, i) => `${p} (${i + 1}/${pages.length})`);
}

// ---------------------------------------------------------------- the bridge

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

class FrivOSC {
  /*
    deps:
      request(method, path, body) -> Promise<object>   Frivo, over the app's connection
      vrchatRunning() -> Promise<bool>
      standaloneRunning() -> bool                      the separate FrivOSC is at work
      version, hostname, log(text), onChange()
      listenPort (9001), sendPort (9000)
  */
  constructor(deps) {
    this.deps = deps;
    this.listenPort = deps.listenPort || 9001;
    this.sendPort = deps.sendPort || 9000;
    this.enabled = false;
    this.connectedTo = null;       // Frivo's origin, while the app is connected
    this.socket = null;            // listening for VRChat
    this.out = dgram.createSocket('udp4');
    this.out.on('error', () => {});
    this.reset();
    this.queue = [];
    this.sending = false;
    this.loopRunning = false;
  }

  reset() {
    this.vrchat = false;           // VRChat seen running on this PC
    this.muted = null;
    this.packets = 0;
    this.reportedMute = 'unset';
    this.lastHeartbeat = 0;
    this.frivoOk = null;
    this.typing = false;
    this.typingSentAt = 0;
    this.unmuteCooldownAt = 0;
    this.chatboxTotal = this.chatboxTotal || 0;
    this.portProblem = '';
    this.standalone = false;
  }

  // What Settings › App shows.
  status() {
    let text;
    if (!this.enabled) text = 'Off.';
    else if (this.standalone) text = 'The separate FrivOSC app is doing this on this PC. Uninstall it to use the one built in.';
    else if (!this.connectedTo) text = 'Waiting for Frivo.';
    else if (!this.vrchat) text = 'Starts by itself when VRChat runs on this PC.';
    else if (this.portProblem) text = this.portProblem;
    else if (!this.packets) text = 'VRChat is running. Turn on OSC in its Options menu if nothing shows up.';
    else text = `Connected to VRChat. Microphone ${this.muted ? 'muted' : 'on'}.`;
    return {
      enabled: this.enabled,
      active: Boolean(this.enabled && this.connectedTo && this.vrchat && !this.standalone && !this.portProblem),
      vrchat: this.vrchat,
      muted: this.muted,
      heard: this.packets > 0,
      chatboxTotal: this.chatboxTotal,
      text,
    };
  }

  setEnabled(on) {
    this.enabled = Boolean(on);
    this.kick();
  }

  // The app connected to Frivo at `origin`, or lost it (null).
  setConnection(origin) {
    this.connectedTo = origin || null;
    this.kick();
  }

  kick() {
    if (this.enabled && this.connectedTo && !this.loopRunning) this.loop();
    if (!this.enabled || !this.connectedTo) this.stopListening();
    this.changed();
  }

  changed() { if (this.deps.onChange) this.deps.onChange(); }

  log(text) { if (this.deps.log) this.deps.log(text); }

  // ---- VRChat → the app ----

  startListening() {
    if (this.socket) return;
    const socket = dgram.createSocket({ type: 'udp4', reuseAddr: true });
    socket.on('message', (data) => {
      const [address, args] = oscParseMessage(data);
      if (address !== MUTE_ADDRESS || !args.length) return;
      const muted = Boolean(args[0]);
      const changed = muted !== this.muted;
      this.muted = muted;
      this.packets += 1;
      if (this.packets === 1) this.log('VRChat is talking to the app.');
      if (changed) { this.log(`VRChat microphone: ${muted ? 'muted' : 'unmuted'}`); this.changed(); }
    });
    socket.on('error', (err) => {
      this.portProblem = `Couldn't listen for VRChat on port ${this.listenPort}: another OSC app may be using it.`;
      this.log(`${this.portProblem} (${err.message})`);
      try { socket.close(); } catch { /* closed */ }
      if (this.socket === socket) this.socket = null;
      this.changed();
    });
    // Loopback only: VRChat sends nowhere else, and this keeps the app off
    // the network (no firewall rule).
    socket.bind(this.listenPort, '127.0.0.1', () => { this.portProblem = ''; this.changed(); });
    this.socket = socket;
  }

  stopListening() {
    if (!this.socket) return;
    try { this.socket.close(); } catch { /* closed */ }
    this.socket = null;
    this.muted = null;
    this.packets = 0;
    this.reportedMute = 'unset';
  }

  // ---- the app → VRChat ----

  emit(message) {
    this.out.send(message, this.sendPort, '127.0.0.1');
  }

  setTyping(on) {
    this.typing = Boolean(on);
    this.typingSentAt = Date.now();
    try { this.emit(oscMessage('/chatbox/typing', this.typing)); } catch { /* VRChat not listening */ }
  }

  // One queue for every message: VRChat's rate limit has to hold across
  // messages, not just between the pages of one.
  enqueue(pages, sfx, pageSeconds) {
    if (this.queue.length >= 40) throw new Error('Too many messages queued for VRChat.');
    this.queue.push({ pages, sfx, pageSeconds });
    if (!this.sending) this.drain();
  }

  async drain() {
    this.sending = true;
    let lastSend = this.lastSend || 0;
    while (this.queue.length) {
      const { pages, sfx, pageSeconds } = this.queue.shift();
      for (let i = 0; i < pages.length; i++) {
        const wait = Math.max(MIN_GAP_SECONDS, pageSeconds) * 1000;
        const gap = wait - (Date.now() - lastSend);
        if (gap > 0) await sleep(gap);
        const more = i < pages.length - 1;
        try {
          this.emit(oscMessage('/chatbox/input', pages[i], true, sfx));
          this.emit(oscMessage('/chatbox/typing', more || this.typing));
        } catch (err) { this.log(`Chatbox send failed: ${err.message}`); }
        lastSend = Date.now();
        this.lastSend = lastSend;
      }
    }
    this.sending = false;
  }

  /*
    Taps VRChat's virtual mute key, only to unmute, only when VRChat has
    said it's muted, as a tap (holding it takes your own mute key away),
    and checks it worked: with "Toggle Voice" off the tap does nothing.
  */
  async unmute() {
    if (!this.packets || this.muted === null || this.muted === false) return;
    const now = Date.now();
    if (this.unmuteCooldownAt && now - this.unmuteCooldownAt < 3000) return;
    this.unmuteCooldownAt = now;
    this.log('Muted in VRChat: tapping the mute key.');
    try {
      this.emit(oscMessage('/input/Voice', true));
      await sleep(120);
    } finally {
      try { this.emit(oscMessage('/input/Voice', false)); } catch { /* VRChat gone */ }
    }
    const until = Date.now() + 2000;
    while (Date.now() < until) {
      await sleep(100);
      if (this.muted === false) { this.log('Unmuted.'); return; }
    }
    this.log("VRChat didn't unmute. In VRChat's Settings › Voice, turn on Toggle Voice.");
  }

  // ---- the app ↔ Frivo ----

  async call(method, path, body) {
    try {
      const reply = await this.deps.request(method, path, body);
      if (this.frivoOk !== true) { this.frivoOk = true; this.changed(); }
      return reply || {};
    } catch (err) {
      if (this.frivoOk !== false) { this.frivoOk = false; this.log(`Frivo isn't answering: ${err.message}`); this.changed(); }
      throw err;
    }
  }

  async pushState() {
    if (!this.packets) return;   // nothing heard yet: "unmuted" would be a guess
    const due = Date.now() - this.lastHeartbeat >= 5000;
    if (this.muted === this.reportedMute && !due) return;
    await this.call('POST', '/api/frivosc/state', { muted: this.muted });
    this.reportedMute = this.muted;
    this.lastHeartbeat = Date.now();
  }

  applyTyping(wanted) {
    if (wanted === this.typing && (!wanted || Date.now() - this.typingSentAt < 2000)) return;
    this.setTyping(wanted);
  }

  async pumpOutbox() {
    let reply;
    try {
      reply = await this.call('GET', '/api/frivosc/outbox');
    } catch {
      if (this.typing) this.applyTyping(false);   // nobody's saying you're still typing
      return;
    }
    this.applyTyping(Boolean(reply.typing));
    for (const message of reply.messages || []) {
      if (!message) continue;
      if (message.unmute) this.unmute().catch(() => {});
      const text = message.text || '';
      let pages = 0;
      if (text) {
        pages = chatboxPages(text);
        try {
          this.enqueue(pages, message.sfx !== false, message.speaking === false ? PAGE_SECONDS_SILENT : PAGE_SECONDS_SPEAKING);
        } catch (err) { this.log(err.message); continue; }
        this.chatboxTotal += 1;
        this.changed();
      }
      if (message.id) this.call('POST', '/api/frivosc/ack', { id: message.id, pages: pages.length || 0 }).catch(() => {});
    }
  }

  // ---- the loop: every half second while there's VRChat to talk to ----

  async loop() {
    this.loopRunning = true;
    let lastCheck = 0;
    let helloFor = null;
    try {
      while (this.enabled && this.connectedTo) {
        if (Date.now() - lastCheck >= 5000) {
          lastCheck = Date.now();
          const standalone = Boolean(this.deps.standaloneRunning && this.deps.standaloneRunning());
          let vrchat = false;
          try { vrchat = await this.deps.vrchatRunning(); } catch { vrchat = false; }
          if (standalone !== this.standalone || vrchat !== this.vrchat) {
            this.standalone = standalone;
            this.vrchat = vrchat;
            this.log(standalone ? 'The separate FrivOSC is running: standing aside.'
              : vrchat ? 'VRChat is running: connecting it to Frivo.' : 'VRChat closed.');
            this.changed();
          }
        }
        if (this.vrchat && !this.standalone) {
          this.startListening();
          if (helloFor !== this.connectedTo) {
            try {
              await this.call('POST', '/api/frivosc/hello', {
                version: `${this.deps.version} (Frivo app)`, hostname: this.deps.hostname, oscquery: false,
              });
              helloFor = this.connectedTo;
            } catch { /* tried again next time round */ }
          }
          try { await this.pushState(); } catch { /* Frivo away for a moment */ }
          await this.pumpOutbox();
        } else {
          if (this.typing) this.setTyping(false);
          this.stopListening();
          helloFor = null;
        }
        await sleep(this.vrchat && !this.standalone ? 500 : 1000);
      }
    } finally {
      if (this.typing) this.setTyping(false);   // never leave the dots up behind us
      this.stopListening();
      this.loopRunning = false;
      this.changed();
    }
  }

  close() {
    this.enabled = false;
    this.stopListening();
    try { this.out.close(); } catch { /* closed */ }
  }
}

module.exports = { FrivOSC, oscMessage, oscParseMessage, oscString, chatboxPages, CHATBOX_LIMIT };
