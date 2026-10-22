'use strict';
/*
  Frivo on this PC (Windows): finding it, starting and stopping it through
  its launcher, and the few settings the app shares with it.

  The app never starts Frivo's server itself. It starts Frivo's launcher,
  which starts the server, follows in-app updates and starts Frivo again
  after one (installer\Launcher.ps1). In app mode the launcher has no window
  and no tray icon:

    launcher.json  appPath    this app's .exe. Written when "Frivo on this PC"
                              is chosen, cleared when it isn't. The launcher
                              opens the app wherever it used to show itself.
    Local\FrivoLauncherStop   set by Stop and Quit here: the launcher stops
                              the server and closes.

  Everything here runs as the signed-in person; nothing needs administrator
  rights except installing Frivo, which its own setup asks for.
*/

const fs = require('fs');
const path = require('path');
const dgram = require('dgram');
const { execFile, spawn } = require('child_process');

const UNINSTALL_KEYS = [
  'HKLM\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\Frivo',
  'HKLM\\Software\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\Frivo',
  'HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\Frivo',
  'HKCU\\Software\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\Frivo',
];
const RUN_KEY = 'HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run';
const RUN_VALUE = 'Frivo';   // Frivo's own sign-in entry (installer\Launcher.ps1)

function run(file, args, options = {}) {
  return new Promise((resolve) => {
    execFile(file, args, { windowsHide: true, timeout: options.timeout || 15000, ...options }, (error, stdout, stderr) => {
      resolve({ code: error ? (typeof error.code === 'number' ? error.code : 1) : 0, stdout: String(stdout || ''), stderr: String(stderr || '') });
    });
  });
}

function powershell(script, env = {}, timeout = 30000) {
  const root = process.env.SystemRoot || 'C:\\Windows';
  const exe = path.join(root, 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe');
  return run(exe, ['-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-Command', script],
    { env: { ...process.env, ...env }, timeout });
}

function parseRegValue(stdout, name) {
  // "    InstallLocation    REG_SZ    C:\Program Files\Frivo"
  for (const line of String(stdout).split(/\r?\n/)) {
    const m = line.match(/^\s*(\S.*?)\s{2,}(REG_\w+)\s{2,}(.*)$/);
    if (m && m[1].toLowerCase() === name.toLowerCase()) return m[3].trim();
  }
  return null;
}

async function regValue(key, name) {
  const r = await run('reg.exe', ['query', key, '/v', name]);
  return r.code === 0 ? parseRegValue(r.stdout, name) : null;
}

class FrivoLocal {
  constructor({ appData, programData, publicDir, execPath }) {
    this.appData = appData;
    this.programData = programData || process.env.ProgramData || 'C:\\ProgramData';
    this.publicDir = publicDir || process.env.PUBLIC || 'C:\\Users\\Public';
    this.execPath = execPath;
    this.dataDir = path.join(appData, 'Frivo');
  }

  get launcherJson() { return path.join(this.dataDir, 'launcher.json'); }
  get serverLog() { return path.join(this.dataDir, 'server.log'); }
  get authorityCert() { return path.join(this.dataDir, 'ca.crt'); }
  get updateStatusFile() { return path.join(this.programData, 'Frivo', 'Updates', 'status.json'); }

  /*
    Frivo's install, as its setup registered it, or null. Read through
    PowerShell as JSON in UTF-8: reg.exe prints in the console's code page,
    which would garble an install folder with accents or other non-English
    letters in its name.
  */
  async findInstall() {
    const script = [
      '[Console]::OutputEncoding = [System.Text.Encoding]::UTF8',
      '$found = foreach ($key in ($env:FRIVO_KEYS -split \'\\|\')) {',
      "  try { $p = Get-ItemProperty -LiteralPath ('Registry::' + $key) -ErrorAction Stop",
      '        [pscustomobject] @{ dir = [string] $p.InstallLocation; version = [string] $p.DisplayVersion } } catch { }',
      '}',
      'ConvertTo-Json -InputObject @($found) -Compress',
    ].join('\n');
    const r = await powershell(script, { FRIVO_KEYS: UNINSTALL_KEYS.map((k) => k.replace(/^HKLM\\/, 'HKEY_LOCAL_MACHINE\\').replace(/^HKCU\\/, 'HKEY_CURRENT_USER\\')).join('|') });
    let entries = [];
    try { entries = JSON.parse(r.stdout.trim() || '[]'); } catch { entries = []; }
    for (const entry of Array.isArray(entries) ? entries : [entries]) {
      const dir = entry && String(entry.dir || '').trim();
      if (!dir) continue;
      const install = {
        dir,
        version: String(entry.version || ''),
        launcher: path.join(dir, 'installer', 'Launcher.ps1'),
        host: path.join(dir, 'installer', 'FrivoHost.exe'),
        shim: path.join(dir, 'Frivo.vbs'),
      };
      if (fs.existsSync(install.launcher) && fs.existsSync(install.host)) return install;
    }
    return null;
  }

  readLauncherSettings() {
    try {
      return JSON.parse(fs.readFileSync(this.launcherJson, 'utf8').replace(/^\uFEFF/, '')) || {};
    } catch {
      return {};
    }
  }

  /*
    App mode on (this app's path) or off (''). Everything else in the file
    is the launcher's and is written back as it was. UTF-8 with a BOM, the
    way Windows PowerShell writes it.
  */
  // True when written (or already so). The launcher reads this file every
  // few seconds, and antivirus may too, so a write that finds it busy tries
  // again a few times rather than failing.
  setAppMode(on) {
    const want = on ? this.execPath : '';
    for (let attempt = 0; attempt < 5; attempt++) {
      try {
        const settings = this.readLauncherSettings();
        if ((settings.appPath || '') === want) return true;
        settings.appPath = want;
        fs.mkdirSync(this.dataDir, { recursive: true });
        const temp = `${this.launcherJson}.tmp`;
        fs.writeFileSync(temp, '\uFEFF' + JSON.stringify(settings, null, 2), 'utf8');
        fs.renameSync(temp, this.launcherJson);
        return true;
      } catch {
        const until = Date.now() + 150 * (attempt + 1);
        while (Date.now() < until) { /* brief wait, then try again */ }
      }
    }
    return false;
  }

  isAppMode() {
    return (this.readLauncherSettings().appPath || '').toLowerCase() === String(this.execPath).toLowerCase();
  }

  // Starts Frivo's launcher in the background. It starts the server, or
  // finds it already running.
  startLauncher(install) {
    const child = spawn(install.host, ['--script', install.launcher, '--tray'], {
      cwd: install.dir,
      detached: true,
      stdio: 'ignore',
      windowsHide: true,
    });
    child.on('error', () => {});
    child.unref();
  }

  /*
    Stops Frivo, and waits until it really has: the launcher gone and
    nothing answering on Frivo's port. Resolves 'stopped', or 'running' when
    it couldn't be stopped (Frivo started as administrator, by its setup).

    Asks the launcher, which stops the server and the built-in AI and
    closes. With no launcher listening (an older Frivo, or a server started
    some other way), asks an older launcher to close, and stops Frivo's own
    Python processes and the built-in AI directly.
  */
  async stopFrivo(install, port = 5000) {
    const script = [
      "$ErrorActionPreference = 'SilentlyContinue'",
      '$dir = $env:FRIVO_DIR.TrimEnd(\'\\\') + \'\\\'',
      'function Test-Port { $c = New-Object System.Net.Sockets.TcpClient; try { $a = $c.BeginConnect(\'127.0.0.1\', [int] $env:FRIVO_PORT, $null, $null); if (-not $a.AsyncWaitHandle.WaitOne(400)) { return $false }; $c.EndConnect($a); $true } catch { $false } finally { $c.Close() } }',
      'function Test-Launcher { $m = $null; [System.Threading.Mutex]::TryOpenExisting(\'Local\\FrivoLauncher\', [ref] $m) }',
      '$asked = $false',
      "try { $e = [System.Threading.EventWaitHandle]::OpenExisting('Local\\FrivoLauncherStop'); [void] $e.Set(); $asked = $true } catch { }",
      'if (-not $asked) {',
      "  try { $q = [System.Threading.EventWaitHandle]::OpenExisting('Local\\FrivoLauncherQuit'); [void] $q.Set() } catch { }",
      "  Get-CimInstance Win32_Process -Filter \"Name = 'python.exe' OR Name = 'pythonw.exe'\" |",
      '    Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($dir, [System.StringComparison]::OrdinalIgnoreCase) } |',
      '    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }',
      "  try { Import-Module (Join-Path $dir 'installer\\Frivo.Setup.psm1') -Force; [void] (Stop-FrivoBuiltinAI -Folders @($env:FRIVO_DATA, $dir.TrimEnd('\\'))) } catch { }",
      '}',
      '$until = (Get-Date).AddSeconds(15)',
      'while ((Get-Date) -lt $until) {',
      "  if (-not (Test-Port) -and -not (Test-Launcher)) { 'stopped'; exit 0 }",
      '  Start-Sleep -Milliseconds 300',
      '}',
      "if (Test-Port) { 'running' } else { 'stopped' }",
    ].join('\n');
    const r = await powershell(script, {
      FRIVO_DIR: install ? install.dir : '',
      FRIVO_DATA: this.dataDir,
      FRIVO_PORT: String(port),
    });
    return r.stdout.trim().split(/\r?\n/).pop() === 'running' ? 'running' : 'stopped';
  }

  // Frivo's sign-in entry: when Frivo runs on this PC, starting with
  // Windows is this, the same as the launcher's own checkbox.
  async getStartAtLogin() {
    return Boolean(await regValue(RUN_KEY, RUN_VALUE));
  }

  async setStartAtLogin(on, install) {
    if (on) {
      const root = process.env.SystemRoot || 'C:\\Windows';
      const command = `"${path.join(root, 'System32', 'wscript.exe')}" "${install.shim}" -Tray`;
      const r = await run('reg.exe', ['add', RUN_KEY, '/v', RUN_VALUE, '/t', 'REG_SZ', '/d', command, '/f']);
      return r.code === 0;
    }
    const r = await run('reg.exe', ['delete', RUN_KEY, '/v', RUN_VALUE, '/f']);
    return r.code === 0 || !(await this.getStartAtLogin());
  }

  // What Frivo's in-app updater is doing, from the file it keeps for the
  // launcher. Null when there's nothing recent.
  updateStatus() {
    try {
      const s = JSON.parse(fs.readFileSync(this.updateStatusFile, 'utf8').replace(/^\uFEFF/, ''));
      const started = Date.parse(s.started_utc || s.updated_utc || '');
      if (!started || Date.now() - started > 60 * 60 * 1000) return null;
      return { state: String(s.state || ''), message: String(s.message || ''), version: String(s.version || '') };
    } catch {
      return null;
    }
  }

  // Frivo's own shortcuts, made by its setup for everyone on the PC.
  frivoShortcutsExist() {
    return [
      path.join(this.publicDir, 'Desktop', 'Frivo.lnk'),
      path.join(this.programData, 'Microsoft', 'Windows', 'Start Menu', 'Programs', 'Frivo.lnk'),
    ].some((p) => fs.existsSync(p));
  }

  /*
    Runs Frivo's setup, which asks for administrator rights itself, and
    waits for it to close. Resolves to its exit code; 1223 means the
    administrator prompt was turned down.
  */
  async runSetup(file) {
    // Process.WaitForExit, not Start-Process -Wait: Windows PowerShell's
    // -Wait also waits for everything setup starts, and setup's last step
    // can start Frivo, which keeps running.
    const script = [
      "$ErrorActionPreference = 'Stop'",
      'try {',
      '  $info = New-Object System.Diagnostics.ProcessStartInfo',
      '  $info.FileName = $env:FRIVO_SETUP',
      "  $info.Verb = 'runas'",
      '  $info.UseShellExecute = $true',
      '  $p = [System.Diagnostics.Process]::Start($info)',
      '  $p.WaitForExit()',
      '  $p.ExitCode',
      '} catch {',
      '  $x = $_.Exception',
      '  $code = 1',
      '  while ($x) { if ($x -is [System.ComponentModel.Win32Exception] -and $x.NativeErrorCode -eq 1223) { $code = 1223; break }; $x = $x.InnerException }',
      '  $code',
      '}',
    ].join('\n');
    const r = await powershell(script, { FRIVO_SETUP: file }, 60 * 60 * 1000);
    const code = parseInt(r.stdout.trim().split(/\r?\n/).pop(), 10);
    return Number.isFinite(code) ? code : r.code;
  }
}

// This PC's address on the network, the way Frivo and its launcher work it
// out: whichever local address would be used to reach the internet.
function lanAddress() {
  return new Promise((resolve) => {
    const socket = dgram.createSocket('udp4');
    const done = (value) => { try { socket.close(); } catch { /* closed */ } resolve(value); };
    socket.on('error', () => done(null));
    try {
      socket.connect(80, '8.8.8.8', () => {
        try { done(socket.address().address); } catch { done(null); }
      });
    } catch {
      done(null);
    }
  });
}

module.exports = { FrivoLocal, lanAddress, parseRegValue, UNINSTALL_KEYS };
