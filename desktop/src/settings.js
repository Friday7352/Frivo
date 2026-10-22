'use strict';
/*
  The app's own settings, in one JSON file in its own folder
  (%APPDATA%\Frivo App\app-settings.json). Never Frivo's folder: Frivo keeps
  its settings, profiles and keys in %APPDATA%\Frivo, and the app only ever
  touches one value there (appPath in launcher.json, see frivo-local.js).

  Written whole to a temporary file and renamed over the old one, so a crash
  mid-write leaves the previous settings rather than half a file.
*/

const fs = require('fs');
const path = require('path');

const DEFAULTS = Object.freeze({
  // Where Frivo runs: null (not chosen yet), 'local' or 'remote'.
  mode: null,
  // The other PC's address, normalised (see normalizeAddress in address.js).
  remoteUrl: '',
  // hostname -> SHA-256 of the certificate at the top of the chain that
  // Frivo on that PC sends (its own certificate authority). Trusted once,
  // with the person's say-so, and checked on every connection after that.
  trusted: {},
  // What closing the window does: 'tray' keeps Frivo running, 'quit' quits.
  closeAction: 'tray',
  // The "still running in the tray" notice is shown once.
  trayNoticeShown: false,
  // Window position and size, restored next time.
  bounds: null,
  // Start with Windows when connecting to another PC. When Frivo runs on
  // this PC, starting with Windows is Frivo's own sign-in entry instead.
  remoteStartAtLogin: false,
  // Shortcuts this app removed because Frivo's own ones do the same job;
  // put back if that stops being true.
  removedShortcuts: [],
});

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

class Settings {
  constructor(file) {
    this.file = file;
    this.data = clone(DEFAULTS);
    this.load();
  }

  load() {
    try {
      const raw = JSON.parse(fs.readFileSync(this.file, 'utf8'));
      if (raw && typeof raw === 'object') {
        for (const key of Object.keys(DEFAULTS)) {
          if (Object.prototype.hasOwnProperty.call(raw, key)) this.data[key] = raw[key];
        }
      }
    } catch {
      // Missing or unreadable: defaults. Nothing here is precious.
    }
    if (!['local', 'remote', null].includes(this.data.mode)) this.data.mode = null;
    if (!['tray', 'quit'].includes(this.data.closeAction)) this.data.closeAction = 'tray';
    if (!this.data.trusted || typeof this.data.trusted !== 'object') this.data.trusted = {};
    if (!Array.isArray(this.data.removedShortcuts)) this.data.removedShortcuts = [];
  }

  get(key) {
    return this.data[key];
  }

  set(key, value) {
    this.data[key] = value;
    this.save();
  }

  update(values) {
    Object.assign(this.data, values);
    this.save();
  }

  save() {
    try {
      fs.mkdirSync(path.dirname(this.file), { recursive: true });
      const temp = `${this.file}.tmp`;
      fs.writeFileSync(temp, JSON.stringify(this.data, null, 2), 'utf8');
      fs.renameSync(temp, this.file);
    } catch {
      // A settings file that can't be written costs a remembered window
      // size, not a working app.
    }
  }
}

module.exports = { Settings, DEFAULTS };
