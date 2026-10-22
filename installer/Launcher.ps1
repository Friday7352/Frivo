<#
    Frivo — launcher
    ------------------------------------------------------------------
    The window that replaces the console. It starts the server hidden,
    watches until it answers, and gives the user one button to open the
    dashboard — plus the two addresses that matter and why they differ.

    Styled to match the app itself: same dark surfaces, same red accent,
    same tone. Settings (close behaviour, sign-in behaviour) live behind
    the Settings button and are written to launcher.json next to the
    app's own settings, so they survive updates.

    Runs without elevation, as the signed-in user — everything it touches
    (the server process, %APPDATA%\Frivo, HKCU's Run key) belongs to that
    user anyway.

    NEW (1.8.0): app mode. When the Frivo app (desktop\ in the repo) is
    set to run Frivo on this PC, it writes its own path to launcher.json as
    appPath. The launcher then has no window and no tray icon: it starts
    and stops the server, follows updates, and opens the app wherever it
    would have shown itself (shortcuts, signing in, after an update). The
    app stops Frivo through the Local\FrivoLauncherStop event. If the app
    is uninstalled, appPath points at nothing and the launcher is its old
    self again.
#>

[CmdletBinding()]
param(
    # Start minimized to the notification area — used by the sign-in
    # entry, so signing in doesn't open a window on top of everything.
    [switch] $Tray,
    # The native Frivo host supplies this so the launcher continues using
    # the installing person's settings if elevation used another account.
    [string] $DataPath
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# The launcher runs with no console, so an unhandled error would be
# completely invisible — a shortcut that "does nothing". Everything below
# is wrapped: a failure writes the reason to a log and shows a plain error
# dialog instead of vanishing.
$LauncherLog = [System.IO.Path]::Combine([System.IO.Path]::GetTempPath(), 'Frivo-Launcher.log')
try {

$ScriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$InstallDir = Split-Path -Parent $ScriptDir

Import-Module (Join-Path $ScriptDir 'Frivo.Setup.psm1') -Force

$AppName      = 'Frivo'
$Port         = 5000
$DataDir      = if ($DataPath) { $DataPath } else { Get-DataPath }
# Combine, not string concatenation: produces the right separator on the
# machine it runs on, which also lets the test harness run this file as-is.
$SettingsPath = [System.IO.Path]::Combine($DataDir, 'launcher.json')
$ServerLog    = [System.IO.Path]::Combine($DataDir, 'server.log')
$IconPath     = [System.IO.Path]::Combine($InstallDir, 'static', 'Frivo.ico')
$PythonW      = [System.IO.Path]::Combine($InstallDir, '.venv', 'Scripts', 'pythonw.exe')
$ShimPath     = [System.IO.Path]::Combine($InstallDir, 'Frivo.vbs')
$RunKey       = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
# NEW (1.7.0): the in-app updater's progress, which the launcher now follows
# itself (see Watch-UpdateStatus).
$UpdateStatusPath = [System.IO.Path]::Combine($(if ($env:ProgramData) { $env:ProgramData } else { 'C:\ProgramData' }),
                                               'Frivo', 'Updates', 'status.json')
$script:launcherStartedUtc = [DateTime]::UtcNow
$script:updateHandled = @{}
$Hostname     = Get-LocalHostname

# ==================================================================
# One launcher at a time
# ==================================================================
# A second copy doesn't open a second window (and a second tray icon, and
# a second server): it signals the first to show itself, then leaves.

$createdMutex = $false
$instanceLock = New-Object System.Threading.Mutex($true, 'Local\FrivoLauncher', [ref] $createdMutex)
$showSignal   = New-Object System.Threading.EventWaitHandle($false,
    [System.Threading.EventResetMode]::ManualReset, 'Local\FrivoLauncherShow')
# NEW (1.8.0): "make sure the server is running", without showing anything.
# What a second launcher started in the background (-Tray: the sign-in
# entry, or the Frivo app starting Frivo) asks for, so signing in or the
# app's Start doesn't bring a window up.
$startSignal  = New-Object System.Threading.EventWaitHandle($false,
    [System.Threading.EventResetMode]::ManualReset, 'Local\FrivoLauncherStart')
if (-not $createdMutex) {
    if ($Tray) { [void] $startSignal.Set() } else { [void] $showSignal.Set() }   # CHANGED (1.8.0)
    exit
}
# NEW (1.8.0): a request left over from a launcher that has since closed
# isn't for this one.
[void] $showSignal.Reset()
[void] $startSignal.Reset()

# NEW (updates): asked to close by the update watcher (Update-Watch.ps1)
# just before setup replaces Frivo's files. Closing on request takes the
# tray icon with it; being killed by setup leaves a ghost icon behind until
# the taskbar repaints, which makes a working update look broken.
$quitSignal = New-Object System.Threading.EventWaitHandle($false,
    [System.Threading.EventResetMode]::ManualReset, 'Local\FrivoLauncherQuit')
[void] $quitSignal.Reset()

# NEW (1.8.0): the Frivo app's Stop and Quit. Unlike the update's quit, this
# one stops the server too.
$stopSignal = New-Object System.Threading.EventWaitHandle($false,
    [System.Threading.EventResetMode]::ManualReset, 'Local\FrivoLauncherStop')
[void] $stopSignal.Reset()

# ==================================================================
# Settings
# ==================================================================

$script:settings = @{
    closeAction = 'keep'    # keep | stop — what closing the window does
    openBrowser = $false    # open the dashboard once the server is up
    lastUpdateNotice = ''   # NEW (updates): the update result already announced
    appPath = ''            # NEW (1.8.0): the Frivo app, when it runs Frivo on this PC
}

function Read-LauncherSettings {
    if (-not (Test-Path -LiteralPath $SettingsPath)) { return }
    try {
        $raw = Get-Content -LiteralPath $SettingsPath -Raw | ConvertFrom-Json
        if ($raw.PSObject.Properties['closeAction'] -and $raw.closeAction -in @('keep', 'stop')) {
            $script:settings.closeAction = [string] $raw.closeAction
        }
        if ($raw.PSObject.Properties['openBrowser']) {
            $script:settings.openBrowser = [bool] $raw.openBrowser
        }
        if ($raw.PSObject.Properties['lastUpdateNotice']) {   # NEW (updates)
            $script:settings.lastUpdateNotice = [string] $raw.lastUpdateNotice
        }
        # NEW (1.8.0): written by the Frivo app; cleared by it when it stops
        # running Frivo on this PC.
        $script:settings.appPath = if ($raw.PSObject.Properties['appPath']) { [string] $raw.appPath } else { '' }
    } catch { }
}

function Save-LauncherSettings {
    try {
        if (-not (Test-Path -LiteralPath $DataDir)) {
            New-Item -ItemType Directory -Path $DataDir -Force | Out-Null
        }
        ($script:settings | ConvertTo-Json) | Set-Content -LiteralPath $SettingsPath -Encoding UTF8
    } catch { }
}

# The sign-in entry is its own source of truth: the registry value either
# exists or it doesn't, so there is nothing to fall out of sync with.
function Test-StartupEnabled {
    try {
        $v = Get-ItemProperty -Path $RunKey -Name $AppName -ErrorAction Stop
        return -not [string]::IsNullOrWhiteSpace([string] $v.$AppName)
    } catch {
        return $false
    }
}

function Set-StartupEnabled {
    param([bool] $Enabled)
    try {
        if ($Enabled) {
            $wscript = if ($env:SystemRoot) { $env:SystemRoot + '\System32\wscript.exe' } else { 'wscript.exe' }
            $cmd = '"{0}" "{1}" -Tray' -f $wscript, $ShimPath
            New-ItemProperty -Path $RunKey -Name $AppName -Value $cmd -PropertyType String -Force | Out-Null
        } else {
            Remove-ItemProperty -Path $RunKey -Name $AppName -ErrorAction SilentlyContinue
        }
        return $true
    } catch {
        return $false
    }
}

Read-LauncherSettings

# NEW (1.8.0): app mode, while the app that asked for it is still installed.
# Never as administrator: the app (an ordinary program) couldn't stop a
# launcher running as administrator, so one with no window or tray icon
# would be a Frivo nobody can stop. That happens when setup's "Launch Frivo
# now" started it from an older setup.
$script:elevated = $false
try {
    $script:elevated = ([System.Security.Principal.WindowsPrincipal] [System.Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [System.Security.Principal.WindowsBuiltInRole]::Administrator)
} catch { }
function Test-AppMode {
    if ($script:elevated) { return $false }
    $path = [string] $script:settings.appPath
    return (-not [string]::IsNullOrWhiteSpace($path)) -and (Test-Path -LiteralPath $path -PathType Leaf)
}
$script:appMode = Test-AppMode

# ==================================================================
# The server
# ==================================================================

$script:serverProc  = $null      # process this launcher started, if any
$script:state       = 'starting' # starting | running | stopped | failed
$script:failReason  = ''

function Test-ServerUp {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $async = $client.BeginConnect('127.0.0.1', $Port, $null, $null)
        if (-not $async.AsyncWaitHandle.WaitOne(400)) { return $false }
        $client.EndConnect($async)
        return $true
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

function Get-LanIp {
    # The same trick app.py uses: ask the routing table which local address
    # would reach the internet. Nothing is actually sent.
    try {
        $sock = New-Object System.Net.Sockets.Socket(
            [System.Net.Sockets.AddressFamily]::InterNetwork,
            [System.Net.Sockets.SocketType]::Dgram,
            [System.Net.Sockets.ProtocolType]::Udp)
        try {
            $sock.Connect('8.8.8.8', 80)
            return ([System.Net.IPEndPoint] $sock.LocalEndPoint).Address.ToString()
        } finally {
            $sock.Close()
        }
    } catch {
        return $null
    }
}

function Test-LocalHostnameWorks {
    try {
        $addrs = [System.Net.Dns]::GetHostAddresses($Hostname)
        foreach ($a in $addrs) {
            if ($a.ToString().StartsWith('127.')) { return $true }
        }
    } catch { }
    return $false
}

function Start-Server {
    if (Test-ServerUp) {
        # Reuse the existing server instead of starting a second instance.
        $script:state = 'running'
        return
    }
    if ($script:serverProc -and -not $script:serverProc.HasExited) {
        # A copy this launcher started is still booting (the port isn't
        # answering yet). Starting another would just race it for the port.
        $script:state = 'starting'
        return
    }
    if (-not (Test-Path -LiteralPath $PythonW)) {
        $script:state = 'failed'
        $script:failReason = 'Frivo''s program files are incomplete. Run the installer again to repair them.'
        return
    }
    try {
        $script:serverProc = Start-Process -FilePath $PythonW -ArgumentList 'app.py' `
            -WorkingDirectory $InstallDir -WindowStyle Hidden -PassThru
        $script:state = 'starting'
    } catch {
        $script:state = 'failed'
        $script:failReason = 'Frivo could not be started: ' + $_.Exception.Message
    }
}

function Stop-Server {
    # NEW (1.8.0): Frivo started before sign-in, by the at-startup task.
    # Ended through Task Scheduler; the copy is also caught below.
    if (Test-FrivoBootTaskRunning) {
        try {
            $service = New-Object -ComObject 'Schedule.Service'
            $service.Connect()
            [void] $service.GetFolder('\').GetTask('Frivo (at startup)').Stop(0)
        } catch { }
    }
    if ($script:serverProc -and -not $script:serverProc.HasExited) {
        try { Stop-Process -Id $script:serverProc.Id -Force -ErrorAction Stop } catch { }
    }
    # Whether or not this launcher started it, catch any copy running from
    # this installation — including one the sign-in entry started.
    try {
        Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'pythonw.exe'" -ErrorAction SilentlyContinue |
            Where-Object { $_.ExecutablePath -and (Test-PathWithinDirectory -Path $_.ExecutablePath -Directory $InstallDir) } |
            ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop } catch { } }
    } catch { }
    # NEW (1.7.0): and the built-in AI's engine, if it outlived Frivo.
    [void] (Stop-FrivoBuiltinAI -Folders @($DataDir, $InstallDir))
    $script:serverProc = $null
    $script:state = 'stopped'
}

function Get-FrivoImage {
    <#
        Loads an image WITHOUT holding the file open.

        Image.FromFile keeps a lock for the lifetime of the image. The
        launcher shows a logo out of the install folder and stays open, so
        that lock is what stopped the uninstaller removing static\.

        FromStream alone would not fix it — GDI+ reads from the stream
        lazily, so the stream must outlive the image. Copying into a new
        Bitmap produces an image that owns its pixels, freeing both.
    #>
    param([string] $Path)
    if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $null }
    $stream = $null
    $loaded = $null
    try {
        # The comma passes the byte array as one argument, not many.
        $stream = New-Object System.IO.MemoryStream(, [System.IO.File]::ReadAllBytes($Path))
        $loaded = [System.Drawing.Image]::FromStream($stream)
        return (New-Object System.Drawing.Bitmap($loaded))
    } catch {
        return $null
    } finally {
        if ($loaded) { $loaded.Dispose() }
        if ($stream) { $stream.Dispose() }
    }
}

function Test-FrivoFirewallRule {
    try {
        $r = Invoke-Tool -FilePath 'netsh.exe' -Arguments @(
            'advfirewall', 'firewall', 'show', 'rule', 'name=Frivo', 'verbose'
        )
        return $r.ExitCode -eq 0 -and $r.StdOut -match [regex]::Escape($PythonW)
    } catch {
        return $false
    }
}

function Enable-FrivoFirewallRule {
    try {
        # $netshArgs, not $args: $args is an automatic variable holding the
        # function's own unbound arguments. Assigning to it works but is the
        # same shadowing class that has bitten this codebase twice.
        $netshArgs = ConvertTo-ArgumentString @(
            'advfirewall', 'firewall', 'add', 'rule', 'name=Frivo',
            'dir=in', 'action=allow', ('program=' + $PythonW),
            # CHANGED (1.5.0): other VLANs on your network too (see Install.ps1).
            'profile=private', 'remoteip=localsubnet,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16', 'protocol=TCP', 'localport=5000'
        )
        Start-Process -FilePath 'netsh.exe' -ArgumentList $netshArgs -Verb RunAs -Wait -WindowStyle Hidden | Out-Null
        return (Test-FrivoFirewallRule)
    } catch {
        return $false
    }
}

# ==================================================================
# Style
# ==================================================================
# The same palette as static/style.css, dark theme.

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()

Add-Type -Namespace FrivoNative -Name Gdi -MemberDefinition @'
[DllImport("gdi32.dll")]
public static extern IntPtr CreateRoundRectRgn(int l, int t, int r, int b, int w, int h);
'@

Add-Type -Namespace FrivoNative -Name Dwm -MemberDefinition @'
[DllImport("dwmapi.dll")]
public static extern int DwmSetWindowAttribute(IntPtr hwnd, int attribute, ref int value, int valueSize);
'@

Add-Type -Namespace FrivoNative -Name Taskbar -MemberDefinition @'
[ComImport, Guid("886d8eeb-8cf2-4446-8d02-cdba1dbdcf99"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface IPropertyStore {
    int GetCount(out uint cProps);
    int GetAt(uint iProp, out PROPERTYKEY pkey);
    int GetValue(ref PROPERTYKEY key, out PROPVARIANT pv);
    int SetValue(ref PROPERTYKEY key, ref PROPVARIANT pv);
    int Commit();
}
[StructLayout(LayoutKind.Sequential, Pack = 4)]
public struct PROPERTYKEY { public Guid fmtid; public uint pid; }
[StructLayout(LayoutKind.Explicit)]
public struct PROPVARIANT {
    [FieldOffset(0)] public ushort vt;
    [FieldOffset(8)] public IntPtr pointerValue;
    public static PROPVARIANT FromString(string value) {
        PROPVARIANT pv = new PROPVARIANT(); pv.vt = 31; pv.pointerValue = Marshal.StringToCoTaskMemUni(value); return pv;
    }
    public void Clear() { if (pointerValue != IntPtr.Zero) Marshal.FreeCoTaskMem(pointerValue); }
}
[DllImport("shell32.dll", CharSet = CharSet.Unicode)]
public static extern int SetCurrentProcessExplicitAppUserModelID(string appID);
[DllImport("shell32.dll")]
public static extern int SHGetPropertyStoreForWindow(IntPtr hwnd, ref Guid riid, out IPropertyStore propertyStore);
public static void SetWindowIdentity(IntPtr hwnd, string appId, string iconResource) {
    SetCurrentProcessExplicitAppUserModelID(appId);
    Guid iid = typeof(IPropertyStore).GUID; IPropertyStore store;
    if (SHGetPropertyStoreForWindow(hwnd, ref iid, out store) < 0 || store == null) return;
    PROPERTYKEY appIdKey = new PROPERTYKEY { fmtid = new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"), pid = 5 };
    PROPERTYKEY iconKey = new PROPERTYKEY { fmtid = new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"), pid = 3 };
    PROPVARIANT id = PROPVARIANT.FromString(appId); PROPVARIANT icon = PROPVARIANT.FromString(iconResource);
    try { store.SetValue(ref appIdKey, ref id); store.SetValue(ref iconKey, ref icon); store.Commit(); }
    finally { id.Clear(); icon.Clear(); }
}
'@

Import-Module (Join-Path $ScriptDir 'Frivo.Ui.psm1') -Force
$ChromeTheme = Get-FrivoTheme

# CHANGED (1.8.0): from the shared theme (Frivo.Ui.psm1), which now has
# Frivo's own colours, so the launcher looks like Frivo.
$ColBg      = $ChromeTheme.Bg
$ColSurface = $ChromeTheme.Surface
$ColCard    = $ChromeTheme.Card
$ColCardHi  = $ChromeTheme.CardHi
$ColHair    = $ChromeTheme.Hair
$ColInk     = $ChromeTheme.Ink
$ColDim     = $ChromeTheme.Dim
$ColFaint   = $ChromeTheme.Faint
$ColAccent  = $ChromeTheme.Accent
$ColAccentH = $ChromeTheme.AccentH
$ColSignal  = $ChromeTheme.Signal
$ColWarn    = $ChromeTheme.Warn

$FontUI    = New-Object System.Drawing.Font('Segoe UI', 10.5)
$FontSmall = New-Object System.Drawing.Font('Segoe UI', 9.25)
$FontCaps  = New-Object System.Drawing.Font('Segoe UI Semibold', 8.25)
$FontMid   = New-Object System.Drawing.Font('Segoe UI Semibold', 12)
$FontBig   = New-Object System.Drawing.Font('Segoe UI Semibold', 19)
$FontBtn   = New-Object System.Drawing.Font('Segoe UI Semibold', 10.5)

function Set-Rounded {
    param($Control, [int] $Radius = 12)
    $handler = {
        param($s, $e)
        $rgn = [FrivoNative.Gdi]::CreateRoundRectRgn(0, 0, $s.Width + 1, $s.Height + 1, $Radius, $Radius)
        $s.Region = [System.Drawing.Region]::FromHrgn($rgn)
    }.GetNewClosure()
    $Control.Add_Resize($handler)
    & $handler $Control $null
}

function Set-FrivoChrome {
    $apply = {
        try {
            $dark = 1
            $caption = $ColBg.ToArgb()
            $text = $ColInk.ToArgb()
            $border = $ColHair.ToArgb()
            [void] [FrivoNative.Dwm]::DwmSetWindowAttribute($form.Handle, 20, [ref] $dark, 4)
            [void] [FrivoNative.Dwm]::DwmSetWindowAttribute($form.Handle, 35, [ref] $caption, 4)
            [void] [FrivoNative.Dwm]::DwmSetWindowAttribute($form.Handle, 36, [ref] $text, 4)
            [void] [FrivoNative.Dwm]::DwmSetWindowAttribute($form.Handle, 34, [ref] $border, 4)
        } catch { }
    }.GetNewClosure()
    $form.Add_HandleCreated(({ & $apply }).GetNewClosure())
}

function New-Card {
    param($Parent, [int] $X, [int] $Y, [int] $W, [int] $H)
    $p = New-Object System.Windows.Forms.Panel
    $p.Location = New-Object System.Drawing.Point($X, $Y)
    $p.Size = New-Object System.Drawing.Size($W, $H)
    $p.BackColor = $ColSurface
    Set-Rounded $p 16
    $Parent.Controls.Add($p)
    return $p
}

function New-DarkLabel {
    param($Parent, [string] $Text, [int] $X, [int] $Y, [int] $W, [int] $H,
          $Font, $Color)
    $l = New-Object System.Windows.Forms.Label
    $l.Location = New-Object System.Drawing.Point($X, $Y)
    $l.Size = New-Object System.Drawing.Size($W, $H)
    $l.Text = $Text
    if ($Font)  { $l.Font = $Font }
    if ($Color) { $l.ForeColor = $Color } else { $l.ForeColor = $ColInk }
    $l.BackColor = [System.Drawing.Color]::Transparent
    $Parent.Controls.Add($l)
    return $l
}

function New-FlatButton {
    param($Parent, [string] $Text, [int] $X, [int] $Y, [int] $W, [int] $H,
          [bool] $Primary = $false)
    $b = New-Object System.Windows.Forms.Button
    $b.Location = New-Object System.Drawing.Point($X, $Y)
    $b.Size = New-Object System.Drawing.Size($W, $H)
    $b.Text = $Text
    $b.FlatStyle = 'Flat'
    $b.Font = $FontBtn
    $b.FlatAppearance.BorderSize = 0
    $b.Cursor = [System.Windows.Forms.Cursors]::Hand
    if ($Primary) {
        $b.BackColor = $ColAccent
        $b.ForeColor = [System.Drawing.Color]::White
        $b.FlatAppearance.MouseOverBackColor = $ColAccentH
        $b.FlatAppearance.MouseDownBackColor = [System.Drawing.Color]::FromArgb(216, 31, 31)
    } else {
        $b.BackColor = $ColCard
        $b.ForeColor = $ColInk
        $b.FlatAppearance.BorderSize = 0   # CHANGED (1.8.0): Frivo's buttons have no outline
        $b.FlatAppearance.BorderColor = $ColHair
        $b.FlatAppearance.MouseOverBackColor = $ColCardHi
        $b.FlatAppearance.MouseDownBackColor = $ColSurface
    }
    Set-Rounded $b 12
    $Parent.Controls.Add($b)
    return $b
}

# NEW (1.8.0): a thin line between rows on a card.
function New-Divider {
    param($Parent, [int] $X, [int] $Y, [int] $W)
    $d = New-Object System.Windows.Forms.Panel
    $d.Location = New-Object System.Drawing.Point($X, $Y)
    $d.Size = New-Object System.Drawing.Size($W, 1)
    $d.BackColor = $ColHair
    $Parent.Controls.Add($d)
    return $d
}

# ==================================================================
# Window
# ==================================================================

$form = New-Object System.Windows.Forms.Form
$form.Text            = $AppName
$form.ClientSize      = New-Object System.Drawing.Size(470, 620)
$form.StartPosition   = 'CenterScreen'
$form.FormBorderStyle = 'FixedDialog'
$form.MaximizeBox     = $false
$form.MinimizeBox     = $false
$form.TopMost         = $false
$form.AutoScaleMode   = 'Dpi'
$form.BackColor       = $ColBg
$form.Font            = $FontUI
# Use the exact shared caption routine that the installer and uninstaller
# use. This keeps all three Frivo windows visually identical.
Set-FrivoWindowChrome -Form $form -Theme $ChromeTheme
if (Test-Path -LiteralPath $IconPath) {
    try { $form.Icon = New-Object System.Drawing.Icon($IconPath) } catch { }
}
$taskbarIconResource = $IconPath + ',0'
$taskbarIdentity = { try { [FrivoNative.Taskbar]::SetWindowIdentity($form.Handle, 'Frivo.Desktop', $taskbarIconResource) } catch { } }.GetNewClosure()
$form.Add_HandleCreated(({ & $taskbarIdentity }).GetNewClosure())

# ---------- header ----------
# CHANGED (1.8.0): laid out like Frivo's own top bar: the logo and name on
# the left, the status as a pill on the right.
$logo = New-Object System.Windows.Forms.PictureBox
$logo.Location = New-Object System.Drawing.Point(24, 24)
$logo.Size = New-Object System.Drawing.Size(36, 36)
$logo.SizeMode = 'Zoom'
$logo.BackColor = [System.Drawing.Color]::Transparent
# The PNG, not Icon.ToBitmap(): converting an icon whose frames are
# PNG-compressed produces garbage pixels on .NET Framework, which is what
# powershell.exe runs on.
#
# And read through a stream rather than Image.FromFile, which holds the
# file open for as long as the image exists. The launcher outlives the
# uninstaller, so that lock is what made removing static\ fail.
$logoPng = [System.IO.Path]::Combine($InstallDir, 'static', 'icon.png')
$logo.Image = Get-FrivoImage $logoPng
$form.Controls.Add($logo)

$titleLbl = New-DarkLabel $form $AppName 70 20 200 40 $FontBig $ColInk

# The status pill: a dot and a word, drawn by hand so it can be round with
# a hairline edge, like Frivo's "Ready" pill.
$statusPill = New-Object System.Windows.Forms.Panel
$statusPill.Location = New-Object System.Drawing.Point(316, 27)
$statusPill.Size = New-Object System.Drawing.Size(130, 30)
$statusPill.BackColor = $ColBg
$statusPill.Tag = @{ Text = 'Starting…'; Color = $ColWarn; Fill = $ColSurface; Edge = $ColHair; Ink = $ColInk; Font = $FontSmall }
$statusPill.Add_Paint({
    param($c, $e)
    $t = $c.Tag
    $g = $e.Graphics
    $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $g.Clear($c.BackColor)
    $size = [System.Windows.Forms.TextRenderer]::MeasureText($t.Text, $t.Font)
    $w = [Math]::Min($c.ClientSize.Width - 1, $size.Width + 38)
    $h = $c.ClientSize.Height - 1
    $x0 = $c.ClientSize.Width - 1 - $w
    $path = New-Object System.Drawing.Drawing2D.GraphicsPath
    $path.AddArc($x0, 0, $h, $h, 90, 180)
    $path.AddArc($x0 + $w - $h, 0, $h, $h, 270, 180)
    $path.CloseFigure()
    $fill = New-Object System.Drawing.SolidBrush($t.Fill)
    $edge = New-Object System.Drawing.Pen($t.Edge)
    $g.FillPath($fill, $path)
    $g.DrawPath($edge, $path)
    $dot = New-Object System.Drawing.SolidBrush($t.Color)
    $g.FillEllipse($dot, $x0 + 13, [int] ($h / 2) - 4, 8, 8)
    [System.Windows.Forms.TextRenderer]::DrawText($g, $t.Text, $t.Font,
        (New-Object System.Drawing.Point(($x0 + 26), ([int] (($h - $size.Height) / 2) + 1))), $t.Ink)
    $fill.Dispose(); $edge.Dispose(); $dot.Dispose(); $path.Dispose()
})
$form.Controls.Add($statusPill)

function Set-StatusPill {
    param([string] $Text, [System.Drawing.Color] $Color)
    $statusPill.Tag.Text = $Text
    $statusPill.Tag.Color = $Color
    $statusPill.Invalidate()
}

# ---------- views ----------
$viewMain = New-Object System.Windows.Forms.Panel
$viewMain.Location = New-Object System.Drawing.Point(0, 84)
$viewMain.Size = New-Object System.Drawing.Size(470, 536)
$viewMain.BackColor = $ColBg
$form.Controls.Add($viewMain)

$viewSettings = New-Object System.Windows.Forms.Panel
$viewSettings.Location = New-Object System.Drawing.Point(0, 84)
$viewSettings.Size = New-Object System.Drawing.Size(470, 536)
$viewSettings.BackColor = $ColBg
$viewSettings.Visible = $false
$form.Controls.Add($viewSettings)

# ---------- main view: addresses ----------
# CHANGED (1.8.0): both addresses on one card, with a line between them.
$hostnameWorks = Test-LocalHostnameWorks
$localUrl = if ($hostnameWorks) { 'https://{0}:{1}' -f $Hostname, $Port } else { 'https://localhost:{0}' -f $Port }
$lanIp    = Get-LanIp
$lanUrl   = if ($lanIp) { 'https://{0}:{1}' -f $lanIp, $Port } else { $null }

# CHANGED (1.8.0): taller, for the pairing code row.
$cardAddr = New-Card $viewMain 24 8 422 204
[void] (New-DarkLabel $cardAddr 'THIS PC' 18 16 300 14 $FontCaps $ColFaint)
[void] (New-DarkLabel $cardAddr $localUrl 18 34 300 24 $FontMid $ColInk)
$copy1 = New-FlatButton $cardAddr 'Copy' 334 26 70 32
$copy1.Font = $FontUI
[void] (New-Divider $cardAddr 18 70 386)
[void] (New-DarkLabel $cardAddr 'OTHER DEVICES ON YOUR NETWORK' 18 86 300 14 $FontCaps $ColFaint)
if ($lanUrl) {
    [void] (New-DarkLabel $cardAddr $lanUrl 18 104 300 24 $FontMid $ColInk)
    $copy2 = New-FlatButton $cardAddr 'Copy' 334 96 70 32
    $copy2.Font = $FontUI
} else {
    [void] (New-DarkLabel $cardAddr 'No network connection detected.' 18 106 300 20 $FontUI $ColDim)
    $copy2 = $null
}

# NEW (1.8.0): the pairing code the Frivo app on another PC asks for, and a
# QR code of the network address for phones.
$CaCertPath = [System.IO.Path]::Combine($DataDir, 'ca.crt')
$FontCode = New-Object System.Drawing.Font('Consolas', 13, [System.Drawing.FontStyle]::Bold)
[void] (New-Divider $cardAddr 18 140 386)
[void] (New-DarkLabel $cardAddr 'PAIRING CODE FOR THE FRIVO APP' 18 156 300 14 $FontCaps $ColFaint)
$script:pairingCode = Get-FrivoPairingCode -CertificatePath $CaCertPath
$codeLbl = New-DarkLabel $cardAddr $(if ($script:pairingCode) { $script:pairingCode } else { 'Shown once Frivo has started' }) 18 174 286 24 $(if ($script:pairingCode) { $FontCode } else { $FontUI }) $(if ($script:pairingCode) { $ColInk } else { $ColDim })
if ($lanUrl) {
    $btnQr = New-FlatButton $cardAddr 'QR code' 314 166 90 32
    $btnQr.Font = $FontUI
} else {
    $btnQr = $null
}

# The certificate authority is made the first time Frivo starts, so the
# code can turn up after the window does.
function Update-PairingCode {
    if ($script:pairingCode) { return }
    $code = Get-FrivoPairingCode -CertificatePath $CaCertPath
    if (-not $code) { return }
    $script:pairingCode = $code
    $codeLbl.Text = $code
    $codeLbl.Font = $FontCode
    $codeLbl.ForeColor = $ColInk
}

# A QR code of the network address, made by Frivo's own Python (the segno
# package Frivo uses for its Settings › Other devices), into a temporary
# file: nothing goes over the network.
function Show-QrCode {
    if (-not $lanUrl) { return }
    $png = [System.IO.Path]::Combine([System.IO.Path]::GetTempPath(), 'frivo-qr.png')
    $ok = $false
    try {
        if (Test-Path -LiteralPath $png) { Remove-Item -LiteralPath $png -Force -ErrorAction SilentlyContinue }
        $code = "import sys, segno; segno.make(sys.argv[1], error='m').save(sys.argv[2], scale=6, border=3)"
        $argLine = '-c "{0}" "{1}" "{2}"' -f $code, $lanUrl, $png
        $p = Start-Process -FilePath $PythonW -ArgumentList $argLine -WindowStyle Hidden -PassThru -Wait
        $ok = ($p.ExitCode -eq 0) -and (Test-Path -LiteralPath $png -PathType Leaf)
    } catch { $ok = $false }
    if (-not $ok) {
        [void] [System.Windows.Forms.MessageBox]::Show($form,
            ("The QR code couldn't be made here. Open {0} and go to Settings › Other devices for it, or type {1} on your phone." -f $AppName, $lanUrl),
            $AppName, 'OK', 'Information')
        return
    }

    $dlg = New-Object System.Windows.Forms.Form
    $dlg.Text = ('{0} on your phone' -f $AppName)
    $dlg.ClientSize = New-Object System.Drawing.Size(340, 448)
    $dlg.StartPosition = 'CenterParent'
    $dlg.FormBorderStyle = 'FixedDialog'
    $dlg.MaximizeBox = $false
    $dlg.MinimizeBox = $false
    $dlg.ShowInTaskbar = $false
    $dlg.AutoScaleMode = 'Dpi'
    $dlg.BackColor = $ColBg
    $dlg.Font = $FontUI
    if ($form.Icon) { $dlg.Icon = $form.Icon }
    Set-FrivoWindowChrome -Form $dlg -Theme $ChromeTheme

    $pic = New-Object System.Windows.Forms.PictureBox
    # At its own size: scaling a QR code blurs its squares.
    $pic.Location = New-Object System.Drawing.Point(45, 20)
    $pic.Size = New-Object System.Drawing.Size(250, 250)
    $pic.SizeMode = 'CenterImage'
    $pic.BackColor = [System.Drawing.Color]::White
    $pic.Image = Get-FrivoImage $png
    $dlg.Controls.Add($pic)

    $u = New-DarkLabel $dlg $lanUrl 20 278 300 24 $FontMid $ColInk
    $u.TextAlign = 'MiddleCenter'
    $t = New-DarkLabel $dlg ("Scan it with your phone's camera, on the same Wi-Fi as this PC. The first time, your phone warns about the certificate: {0}'s Settings › Other devices shows how to trust it." -f $AppName) 24 310 292 80 $FontSmall $ColDim
    $t.TextAlign = 'TopCenter'
    $close = New-FlatButton $dlg 'Close' 120 396 100 36
    $close.Font = $FontUI
    $close.DialogResult = 'OK'
    $dlg.AcceptButton = $close
    $dlg.CancelButton = $close
    [void] $dlg.ShowDialog($form)
    if ($pic.Image) { $pic.Image.Dispose() }
    $dlg.Dispose()
    Remove-Item -LiteralPath $png -Force -ErrorAction SilentlyContinue
}

$noteText = ("{0} works on this PC. Phones and other PCs use the network address." -f $Hostname)
$noteLbl = New-DarkLabel $viewMain $noteText 28 222 414 40 $FontSmall $ColDim

$btnOpen = New-FlatButton $viewMain ('Open {0}' -f $AppName) 24 270 422 46 -Primary $true

$btnSettings = New-FlatButton $viewMain 'Settings' 24 328 205 40
$btnPower    = New-FlatButton $viewMain ('Stop {0}' -f $AppName) 241 328 205 40

$hintLbl = New-DarkLabel $viewMain '' 28 382 414 40 $FontSmall $ColFaint
$hintLbl.TextAlign = 'TopCenter'

# ---------- settings view ----------
# CHANGED (1.8.0): rows with switches, like Frivo's Settings, instead of
# radio buttons and checkboxes.
# [string] first: in Windows PowerShell 5.1 a bare [char] on the left of +
# is treated as a number and the script dies trying to convert the text.
$btnBack = New-FlatButton $viewSettings ([string][char]0x2190 + '  Back') 24 4 90 32
$btnBack.Font = $FontUI

function New-SwitchRow {
    param($Card, [int] $Y, [string] $Label, [string] $Sub, [string] $Name)
    [void] (New-DarkLabel $Card $Label 18 $Y 330 22 $FontUI $ColInk)
    [void] (New-DarkLabel $Card $Sub 18 ($Y + 22) 330 20 $FontSmall $ColDim)
    return (New-FrivoSwitch -Theme $ChromeTheme -Parent $Card -X 362 -Y ($Y + 8) -Name $Name)
}

[void] (New-DarkLabel $viewSettings 'WINDOW' 30 50 380 16 $FontCaps $ColFaint)
$cardClose = New-Card $viewSettings 24 70 422 72
$swKeep = New-SwitchRow $cardClose 14 ('Keep {0} running when I close this' -f $AppName) `
    'It stays in the tray. Quit from the tray icon.' 'Keep running when closed'

[void] (New-DarkLabel $viewSettings 'STARTUP' 30 156 380 16 $FontCaps $ColFaint)
$cardStart = New-Card $viewSettings 24 176 422 128
$swStartup = New-SwitchRow $cardStart 14 ('Start {0} when I sign in' -f $AppName) `
    'In the tray, ready for phones and other PCs.' 'Start when I sign in'
[void] (New-Divider $cardStart 18 64 386)
$swAutoOpen = New-SwitchRow $cardStart 78 'Open it in my browser when it starts' `
    'Once Frivo is ready.' 'Open in my browser when it starts'

$needsFirewallRule = $lanUrl -and -not (Test-FrivoFirewallRule)
$helpY = 318
if ($needsFirewallRule) {
    [void] (New-DarkLabel $viewSettings 'NETWORK ACCESS' 30 318 380 16 $FontCaps $ColFaint)
    $cardFirewall = New-Card $viewSettings 24 338 422 64
    [void] (New-DarkLabel $cardFirewall 'Other devices need port 5000 open.' 18 21 250 22 $FontSmall $ColDim)
    $btnFirewall = New-FlatButton $cardFirewall 'Open port 5000' 274 14 130 36
    $btnFirewall.Font = $FontUI
    $helpY = 416
} else {
    $btnFirewall = $null
}

[void] (New-DarkLabel $viewSettings 'TROUBLESHOOTING' 30 $helpY 380 16 $FontCaps $ColFaint)
$cardHelp = New-Card $viewSettings 24 ($helpY + 20) 422 62

$btnLog = New-FlatButton $cardHelp 'View server log' 16 13 187 36
$btnData = New-FlatButton $cardHelp 'Open settings folder' 219 13 187 36
$btnLog.Font = $FontUI
$btnData.Font = $FontUI

# ---------- tray ----------
# Use $notify because PowerShell variable names are case-insensitive and
# $Tray is a switch parameter.
$notify = New-Object System.Windows.Forms.NotifyIcon
$notify.Text = $AppName
if (Test-Path -LiteralPath $IconPath) {
    try { $notify.Icon = New-Object System.Drawing.Icon($IconPath) } catch { }
}
$trayMenu = New-Object System.Windows.Forms.ContextMenuStrip
$miOpen  = $trayMenu.Items.Add(('Open {0}' -f $AppName))
$miShow  = $trayMenu.Items.Add('Show launcher')
[void] $trayMenu.Items.Add('-')
$miQuit  = $trayMenu.Items.Add(('Stop {0} and quit' -f $AppName))
$notify.ContextMenuStrip = $trayMenu
# CHANGED (1.8.0): no tray icon in app mode; the app has its own.
$notify.Visible = -not $script:appMode

$script:quitting     = $false
$script:balloonShown = $false
$script:autoOpenDone = $false

# ==================================================================
# Behaviour
# ==================================================================

function Open-Dashboard {
    try { Start-Process $localUrl } catch { }
}

# NEW (1.8.0): app mode opens the app instead of this window.
function Test-AppRunning {
    $path = [string] $script:settings.appPath
    if (-not $path) { return $false }
    try {
        $name = [System.IO.Path]::GetFileNameWithoutExtension($path)
        foreach ($p in @(Get-Process -Name $name -ErrorAction SilentlyContinue)) {
            try { if ($p.Path -and $p.Path -ieq $path) { return $true } } catch { }
        }
    } catch { }
    return $false
}

function Open-App {
    param([switch] $Hidden)
    try {
        if ($Hidden) {
            Start-Process -FilePath $script:settings.appPath -ArgumentList '--hidden' | Out-Null
        } else {
            # Already running: the app's single-instance lock brings its
            # window forward instead of opening a second one.
            Start-Process -FilePath $script:settings.appPath | Out-Null
        }
    } catch {
        try { Add-Content -LiteralPath $LauncherLog -Value ('{0} could not open the Frivo app: {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $_.Exception.Message) } catch { }
    }
}

function Show-Launcher {
    if ($script:appMode) {   # NEW (1.8.0)
        if ($script:state -notin @('running', 'starting')) { Start-Server }
        Open-App
        return
    }

    # A desktop or Start Menu shortcut may be clicked while Frivo is already
    # running from the sign-in tray entry. Restore that same window instead
    # of silently leaving the person at the notification icon.
    $form.ShowInTaskbar = $true
    $form.Show()
    if ($form.WindowState -eq [System.Windows.Forms.FormWindowState]::Minimized) {
        $form.WindowState = [System.Windows.Forms.FormWindowState]::Normal
    }
    $form.BringToFront()
    $form.Activate()
    # Windows can deny a background process the foreground once. Raising
    # TopMost only for this activation gets the requested window in front
    # without making Frivo permanently stay above other apps.
    $form.TopMost = $true
    $form.TopMost = $false
}

function Show-UpdateResult {
    <#
        NEW (updates): after an in-app update the watcher starts a fresh
        launcher in the tray. Say once what happened, so an update that
        restarted Frivo while you were away does not go unexplained — and
        so a failed one says why, in the one place still on screen when the
        browser could not reconnect.
    #>
    if ($script:appMode) { return }   # NEW (1.8.0): the app says it instead
    try {
        $programData = if ($env:ProgramData) { $env:ProgramData } else { 'C:\ProgramData' }
        $path = [System.IO.Path]::Combine($programData, 'Frivo', 'Updates', 'status.json')
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { return }
        $s = [System.IO.File]::ReadAllText($path) | ConvertFrom-Json
        $id = [string] $s.id
        if (-not $id -or $id -eq $script:settings.lastUpdateNotice) { return }
        if ([string] $s.state -notin @('done', 'failed')) { return }
        $when = [DateTime]::Parse([string] $s.updated_utc).ToUniversalTime()
        if (([DateTime]::UtcNow - $when).TotalMinutes -gt 15) { return }

        $script:settings.lastUpdateNotice = $id
        Save-LauncherSettings
        $icon = if ([string] $s.state -eq 'done') { 'Info' } else { 'Warning' }
        $title = if ([string] $s.state -eq 'done') { $AppName } else { ('{0} update did not finish' -f $AppName) }
        $notify.ShowBalloonTip(6000, $title, [string] $s.message, [System.Windows.Forms.ToolTipIcon]::$icon)
    } catch { }
}

function Update-Status {
    $up = Test-ServerUp

    if ($up) {
        $script:state = 'running'
    } elseif ($script:state -eq 'running') {
        # It was up and no longer is — either stopped elsewhere or crashed.
        $script:state = 'stopped'
    } elseif ($script:state -eq 'starting') {
        if ($script:serverProc -and $script:serverProc.HasExited) {
            $script:state = 'failed'
            $script:failReason = ('{0} stopped right after starting. The server log usually says why.' -f $AppName)
        }
    }

    switch ($script:state) {
        'running' {
            Set-StatusPill 'Running' $ColSignal   # CHANGED (1.8.0)
            $btnOpen.Enabled = $true
            $btnOpen.Text = ('Open {0}' -f $AppName)
            $btnPower.Text = ('Stop {0}' -f $AppName)
            $btnPower.Enabled = $true
            $hintLbl.Text = ''
        }
        'starting' {
            Set-StatusPill 'Starting…' $ColWarn   # CHANGED (1.8.0)
            $btnOpen.Enabled = $false
            $btnPower.Enabled = $false
            $hintLbl.Text = 'The first start after installing can take a few extra seconds.'
        }
        'stopped' {
            Set-StatusPill 'Stopped' $ColFaint   # CHANGED (1.8.0)
            $btnOpen.Enabled = $true
            $btnOpen.Text = ('Start {0}' -f $AppName)
            $btnPower.Enabled = $false
            $hintLbl.Text = ''
        }
        'failed' {
            Set-StatusPill 'Not running' $ColAccent   # CHANGED (1.8.0)
            $btnOpen.Enabled = $true
            $btnOpen.Text = ('Start {0}' -f $AppName)
            $btnPower.Enabled = $false
            $hintLbl.Text = $script:failReason
        }
    }

    # CHANGED (1.8.0): never in app mode, where the app is the window.
    if ($script:state -eq 'running' -and $script:settings.openBrowser -and -not $script:appMode -and -not $script:autoOpenDone) {
        $script:autoOpenDone = $true
        Open-Dashboard
    }
}

$btnOpen.Add_Click({
    if ($script:state -eq 'running') {
        Open-Dashboard
    } else {
        Start-Server
        Update-Status
    }
})

$btnPower.Add_Click({
    Stop-Server
    Update-Status
})

$copy1.Add_Click({
    try { [System.Windows.Forms.Clipboard]::SetText($localUrl); $copy1.Text = 'Copied' } catch { }
})
if ($btnQr) { $btnQr.Add_Click({ Show-QrCode }) }   # NEW (1.8.0)
if ($copy2) {
    $copy2.Add_Click({
        try { [System.Windows.Forms.Clipboard]::SetText($lanUrl); $copy2.Text = 'Copied' } catch { }
    })
}

$btnSettings.Add_Click({
    # CHANGED (1.8.0): switches
    Set-FrivoSwitch $swKeep ($script:settings.closeAction -eq 'keep')
    Set-FrivoSwitch $swStartup (Test-StartupEnabled)
    Set-FrivoSwitch $swAutoOpen ([bool] $script:settings.openBrowser)
    $viewMain.Visible = $false
    $viewSettings.Visible = $true
})

$btnBack.Add_Click({
    $viewSettings.Visible = $false
    $viewMain.Visible = $true
})

$swKeep.Tag.OnChange = {
    param([bool] $on)
    $script:settings.closeAction = if ($on) { 'keep' } else { 'stop' }
    Save-LauncherSettings
}
$swStartup.Tag.OnChange = {
    param([bool] $on)
    if (-not (Set-StartupEnabled $on)) {
        Set-FrivoSwitch $swStartup (Test-StartupEnabled)
        [System.Windows.Forms.MessageBox]::Show(
            'The sign-in setting could not be changed.',
            $AppName,
            [System.Windows.Forms.MessageBoxButtons]::OK,
            [System.Windows.Forms.MessageBoxIcon]::Warning) | Out-Null
    }
}
$swAutoOpen.Tag.OnChange = {
    param([bool] $on)
    $script:settings.openBrowser = $on
    Save-LauncherSettings
}
if ($btnFirewall) {
    $btnFirewall.Add_Click({
        $btnFirewall.Enabled = $false
        $btnFirewall.Text = 'Opening…'
        [System.Windows.Forms.Application]::DoEvents()
        if (Enable-FrivoFirewallRule) {
            $btnFirewall.Text = 'Port is open'
            [System.Windows.Forms.MessageBox]::Show(
                'Other devices on your private network can now connect to Frivo.',
                $AppName,
                [System.Windows.Forms.MessageBoxButtons]::OK,
                [System.Windows.Forms.MessageBoxIcon]::Information) | Out-Null
        } else {
            $btnFirewall.Enabled = $true
            $btnFirewall.Text = 'Try again'
            [System.Windows.Forms.MessageBox]::Show(
                'Windows could not open port 5000. Approve the administrator prompt, then try again.',
                $AppName,
                [System.Windows.Forms.MessageBoxButtons]::OK,
                [System.Windows.Forms.MessageBoxIcon]::Warning) | Out-Null
        }
    })
}

$btnLog.Add_Click({
    if (Test-Path -LiteralPath $ServerLog) {
        Start-Process 'notepad.exe' -ArgumentList ('"{0}"' -f $ServerLog)
    } else {
        [System.Windows.Forms.MessageBox]::Show(
            'No server log has been written yet.',
            $AppName,
            [System.Windows.Forms.MessageBoxButtons]::OK,
            [System.Windows.Forms.MessageBoxIcon]::Information) | Out-Null
    }
})
$btnData.Add_Click({
    if (Test-Path -LiteralPath $DataDir) {
        Start-Process 'explorer.exe' -ArgumentList ('"{0}"' -f $DataDir)
    }
})

$miOpen.Add_Click({ Open-Dashboard })
$miShow.Add_Click({ Show-Launcher })
$miQuit.Add_Click({
    $script:quitting = $true
    Stop-Server
    $form.Close()
    # In tray mode the message loop runs without a form, so closing the
    # form alone would leave it spinning.
    [System.Windows.Forms.Application]::Exit()
})
$notify.Add_DoubleClick({ Show-Launcher })

$form.Add_FormClosing({
    param($s, $e)
    if ($script:quitting) { return }
    if ($e.CloseReason -ne [System.Windows.Forms.CloseReason]::UserClosing) { return }

    if ($script:settings.closeAction -eq 'keep' -and $script:state -in @('running', 'starting')) {
        # The window goes away; the server and tray icon stay.
        $e.Cancel = $true
        $form.Hide()
        if (-not $script:balloonShown) {
            $script:balloonShown = $true
            try {
                $notify.ShowBalloonTip(2500, $AppName,
                    ('{0} is still running. Right-click the tray icon to stop it.' -f $AppName),
                    [System.Windows.Forms.ToolTipIcon]::Info)
            } catch { }
        }
    } else {
        $script:quitting = $true
        Stop-Server
    }
})

$form.Add_FormClosed({
    $notify.Visible = $false
    $notify.Dispose()
    if ($script:quitting) { [System.Windows.Forms.Application]::Exit() }
})

# NEW (1.7.0): follows an in-app update itself. The update watcher asks the
# launcher to close (Local\FrivoLauncherQuit), but when that didn't reach
# it, the launcher stayed open saying "Stopped" after setup stopped the
# server, and because a launcher was still running, nothing started Frivo
# again. Now the launcher reads the updater's status.json too:
#   installing             close, so setup can replace the files and start
#                          a fresh Frivo afterwards
#   done or failed, and    if the server is down, start it again here
#   this launcher is
#   still open
# Only updates that started while this launcher was running count, so an
# old status.json can't close a launcher that's just been opened.
$script:updateTick = 0
function Watch-UpdateStatus {
    $script:updateTick++
    if ($script:updateTick % 2) { return }   # every other tick: about every 2.4 s
    try {
        if (-not (Test-Path -LiteralPath $UpdateStatusPath -PathType Leaf)) { return }
        $s = [System.IO.File]::ReadAllText($UpdateStatusPath) | ConvertFrom-Json
    } catch { return }   # mid-replace; looked at again shortly
    $id = [string] $s.id
    if (-not $id) { return }
    $started = [DateTime]::MinValue
    try { $started = ([DateTime]::Parse([string] $s.started_utc)).ToUniversalTime() } catch { return }
    if ($started -lt $script:launcherStartedUtc.AddSeconds(-5)) { return }
    if ([DateTime]::UtcNow - $started -gt [TimeSpan]::FromMinutes(60)) { return }
    $state = [string] $s.state
    if ($state -eq 'installing' -and -not $script:updateHandled[$id + ':quit']) {
        $script:updateHandled[$id + ':quit'] = $true
        try { Add-Content -LiteralPath $LauncherLog -Value ('{0} update {1} installing: closing' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $id) } catch { }
        [void] $quitSignal.Set()   # handled just below, the same way the watcher's request is
    } elseif ($state -in @('done', 'failed') -and $s.restart -eq $true -and
              $script:state -in @('stopped', 'failed') -and -not $script:updateHandled[$id + ':start']) {
        $script:updateHandled[$id + ':start'] = $true
        try { Add-Content -LiteralPath $LauncherLog -Value ('{0} update {1} {2}: starting the server again' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $id, $state) } catch { }
        Start-Server
    }
}

# Reset the Copy buttons and poll the server.
$script:appModeTick = 0   # NEW (1.8.0)
$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 1200
$timer.Add_Tick({
    Update-Status
    try { Watch-UpdateStatus } catch { }   # NEW (1.7.0)
    if ($copy1.Text -eq 'Copied') { $copy1.Text = 'Copy' }
    if ($copy2 -and $copy2.Text -eq 'Copied') { $copy2.Text = 'Copy' }
    Update-PairingCode   # NEW (1.8.0)
    # A second launcher was started — bring this one forward instead.
    if ($showSignal.WaitOne(0)) {
        [void] $showSignal.Reset()
        Show-Launcher
    }
    # NEW (1.8.0): a second launcher started in the background: just make
    # sure the server is running.
    if ($startSignal.WaitOne(0)) {
        [void] $startSignal.Reset()
        if ($script:state -notin @('running', 'starting')) { Start-Server; Update-Status }
    }
    # NEW (1.8.0): the Frivo app's Stop or Quit: stop the server and leave.
    if ($stopSignal.WaitOne(0)) {
        [void] $stopSignal.Reset()
        try { Add-Content -LiteralPath $LauncherLog -Value ('{0} stop asked for by the Frivo app' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')) } catch { }
        $script:quitting = $true
        $timer.Stop()
        Stop-Server
        $notify.Visible = $false
        $form.Close()
        [System.Windows.Forms.Application]::Exit()
        return
    }
    # NEW (1.8.0): the app was set to another PC, or uninstalled, while this
    # launcher ran without a tray icon. Bring the icon back so this Frivo can
    # still be found and stopped.
    $script:appModeTick++
    if (-not ($script:appModeTick % 5)) {
        Read-LauncherSettings
        $nowAppMode = Test-AppMode
        if ($script:appMode -and -not $nowAppMode) { $notify.Visible = $true }
        # And the other way: the app was just set to run Frivo on this PC
        # while this launcher had its window or tray icon. The app takes over.
        if ($nowAppMode -and -not $script:appMode) {
            $notify.Visible = $false
            $form.Hide()
        }
        $script:appMode = $nowAppMode
    }
    # NEW (updates): an update is about to replace Frivo's files. Leave
    # without stopping the server — setup stops it, and the watcher starts
    # Frivo again afterwards.
    if ($quitSignal.WaitOne(0)) {
        [void] $quitSignal.Reset()
        $script:quitting = $true
        $timer.Stop()
        $notify.Visible = $false
        $form.Close()
        [System.Windows.Forms.Application]::Exit()
    }
})
$timer.Start()

# ==================================================================
# Go
# ==================================================================

Start-Server
Update-Status
Show-UpdateResult   # NEW (updates)

if ($script:appMode) {
    # NEW (1.8.0): no window and no tray icon. Opens the app unless it's
    # already open (it usually is: it's what started this launcher). From
    # the sign-in entry or after an update it opens in the tray, not on top
    # of everything.
    if (-not (Test-AppRunning)) { Open-App -Hidden:$Tray }
    [System.Windows.Forms.Application]::Run()
} elseif ($Tray) {
    # Started at sign-in: no window, just the tray icon and the server.
    [System.Windows.Forms.Application]::Run()
    # Run() returns when Application.Exit() is called — via the form path
    # below this never runs, so quit through the tray menu ends it here.
} else {
    [System.Windows.Forms.Application]::Run($form)
}

try { $instanceLock.ReleaseMutex() } catch { }

} catch {
    $reason = $_.Exception.Message
    $where  = $_.ScriptStackTrace
    try {
        Add-Content -LiteralPath $LauncherLog -Value (
            "{0}`r`n{1}`r`n{2}`r`n----" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $reason, $where)
    } catch { }
    try {
        Add-Type -AssemblyName System.Windows.Forms
        [System.Windows.Forms.MessageBox]::Show(
            ("Frivo could not start.`r`n`r`n{0}`r`n`r`nDetails were saved to:`r`n{1}" -f $reason, $LauncherLog),
            'Frivo',
            [System.Windows.Forms.MessageBoxButtons]::OK,
            [System.Windows.Forms.MessageBoxIcon]::Error) | Out-Null
    } catch { }
    exit 1
}
