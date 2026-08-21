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
if (-not $createdMutex) {
    [void] $showSignal.Set()
    exit
}

# ==================================================================
# Settings
# ==================================================================

$script:settings = @{
    closeAction = 'keep'    # keep | stop — what closing the window does
    openBrowser = $false    # open the dashboard once the server is up
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
            'profile=private', 'remoteip=localsubnet', 'protocol=TCP', 'localport=5000'
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

$ColBg      = [System.Drawing.Color]::FromArgb(13, 17, 23)     # --bg
$ColSurface = [System.Drawing.Color]::FromArgb(22, 27, 34)     # --surface
$ColCard    = [System.Drawing.Color]::FromArgb(28, 35, 45)     # --surface-2
$ColHair    = [System.Drawing.Color]::FromArgb(42, 50, 62)
$ColInk     = [System.Drawing.Color]::FromArgb(232, 238, 247)  # --ink
$ColDim     = [System.Drawing.Color]::FromArgb(154, 163, 178)
$ColFaint   = [System.Drawing.Color]::FromArgb(110, 119, 134)
$ColAccent  = [System.Drawing.Color]::FromArgb(250, 47, 47)    # --accent
$ColAccentH = [System.Drawing.Color]::FromArgb(255, 82, 82)
$ColSignal  = [System.Drawing.Color]::FromArgb(62, 207, 109)   # --signal
$ColWarn    = [System.Drawing.Color]::FromArgb(240, 166, 60)   # --warn

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
    Set-Rounded $p 18
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
        $b.FlatAppearance.BorderSize = 1
        $b.FlatAppearance.BorderColor = $ColHair
        $b.FlatAppearance.MouseOverBackColor = [System.Drawing.Color]::FromArgb(50, 61, 76)
        $b.FlatAppearance.MouseDownBackColor = [System.Drawing.Color]::FromArgb(24, 30, 39)
    }
    Set-Rounded $b 14
    $Parent.Controls.Add($b)
    return $b
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
$logo = New-Object System.Windows.Forms.PictureBox
$logo.Location = New-Object System.Drawing.Point(28, 22)
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

$titleLbl = New-DarkLabel $form $AppName 78 15 250 38 $FontBig $ColInk

$statusDot = New-Object System.Windows.Forms.Panel
$statusDot.Location = New-Object System.Drawing.Point(82, 56)
$statusDot.Size = New-Object System.Drawing.Size(9, 9)
$statusDot.BackColor = $ColWarn
Set-Rounded $statusDot 9
$form.Controls.Add($statusDot)

$statusLbl = New-DarkLabel $form 'Starting…' 98 53 330 18 $FontSmall $ColDim

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
$hostnameWorks = Test-LocalHostnameWorks
$localUrl = if ($hostnameWorks) { 'https://{0}:{1}' -f $Hostname, $Port } else { 'https://localhost:{0}' -f $Port }
$lanIp    = Get-LanIp
$lanUrl   = if ($lanIp) { 'https://{0}:{1}' -f $lanIp, $Port } else { $null }

$card1 = New-Card $viewMain 24 10 422 78
[void] (New-DarkLabel $card1 'ON THIS PC' 18 14 380 14 $FontCaps $ColFaint)
[void] (New-DarkLabel $card1 $localUrl 18 34 300 24 $FontMid $ColInk)
$copy1 = New-FlatButton $card1 'Copy' 336 30 68 32
$copy1.Font = $FontUI

$card2 = New-Card $viewMain 24 98 422 78
[void] (New-DarkLabel $card2 'OTHER DEVICES ON YOUR NETWORK' 18 14 380 14 $FontCaps $ColFaint)
if ($lanUrl) {
    [void] (New-DarkLabel $card2 $lanUrl 18 34 300 24 $FontMid $ColInk)
    $copy2 = New-FlatButton $card2 'Copy' 336 30 68 32
    $copy2.Font = $FontUI
} else {
    [void] (New-DarkLabel $card2 'No network connection detected.' 18 36 380 20 $FontUI $ColDim)
    $copy2 = $null
}

$noteText = ("{0} works on this PC. Other devices use the address above." -f $Hostname)
$noteLbl = New-DarkLabel $viewMain $noteText 28 188 414 54 $FontSmall $ColDim

$btnOpen = New-FlatButton $viewMain ('Open {0}' -f $AppName) 24 252 422 46 -Primary $true

$btnSettings = New-FlatButton $viewMain 'Settings' 24 310 205 38
$btnPower    = New-FlatButton $viewMain ('Stop {0}' -f $AppName) 241 310 205 38

$hintLbl = New-DarkLabel $viewMain '' 28 364 414 36 $FontSmall $ColFaint
$hintLbl.TextAlign = 'TopCenter'

# ---------- settings view ----------
# [string] first: in Windows PowerShell 5.1 a bare [char] on the left of +
# is treated as a number and the script dies trying to convert the text.
$btnBack = New-FlatButton $viewSettings ([string][char]0x2190 + '  Back') 24 4 90 32
$btnBack.Font = $FontUI

[void] (New-DarkLabel $viewSettings 'WHEN I CLOSE THIS WINDOW' 30 52 380 16 $FontCaps $ColFaint)
$cardClose = New-Card $viewSettings 24 74 422 104

$radioKeep = New-Object System.Windows.Forms.RadioButton
$radioKeep.Location = New-Object System.Drawing.Point(18, 14)
$radioKeep.Size = New-Object System.Drawing.Size(390, 24)
$radioKeep.Text = ('Keep {0} running in the background' -f $AppName)
$radioKeep.ForeColor = $ColInk
$radioKeep.BackColor = [System.Drawing.Color]::Transparent
$cardClose.Controls.Add($radioKeep)

[void] (New-DarkLabel $cardClose ('Keeps {0} running in the notification area.' -f $AppName) 42 40 354 22 $FontSmall $ColDim)

$radioStop = New-Object System.Windows.Forms.RadioButton
$radioStop.Location = New-Object System.Drawing.Point(18, 58)
$radioStop.Size = New-Object System.Drawing.Size(390, 24)
$radioStop.Text = ('Stop {0}' -f $AppName)
$radioStop.ForeColor = $ColInk
$radioStop.BackColor = [System.Drawing.Color]::Transparent
$cardClose.Controls.Add($radioStop)

[void] (New-DarkLabel $cardClose 'Stops the server and closes Frivo.' 42 82 354 20 $FontSmall $ColDim)

[void] (New-DarkLabel $viewSettings 'STARTUP' 30 192 380 16 $FontCaps $ColFaint)
$cardStart = New-Card $viewSettings 24 214 422 104

$chkStartup = New-Object System.Windows.Forms.CheckBox
$chkStartup.Location = New-Object System.Drawing.Point(18, 14)
$chkStartup.Size = New-Object System.Drawing.Size(390, 24)
$chkStartup.Text = ('Start {0} when I sign in to Windows' -f $AppName)
$chkStartup.ForeColor = $ColInk
$chkStartup.BackColor = [System.Drawing.Color]::Transparent
$cardStart.Controls.Add($chkStartup)

[void] (New-DarkLabel $cardStart 'Starts Frivo in the notification area.' 42 40 354 22 $FontSmall $ColDim)

$chkAutoOpen = New-Object System.Windows.Forms.CheckBox
$chkAutoOpen.Location = New-Object System.Drawing.Point(18, 58)
$chkAutoOpen.Size = New-Object System.Drawing.Size(390, 24)
$chkAutoOpen.Text = 'Open the dashboard in my browser automatically'
$chkAutoOpen.ForeColor = $ColInk
$chkAutoOpen.BackColor = [System.Drawing.Color]::Transparent
$cardStart.Controls.Add($chkAutoOpen)

[void] (New-DarkLabel $cardStart 'Opens Frivo in your browser after launch.' 42 82 354 20 $FontSmall $ColDim)

$needsFirewallRule = $lanUrl -and -not (Test-FrivoFirewallRule)
$helpY = 336
if ($needsFirewallRule) {
    [void] (New-DarkLabel $viewSettings 'NETWORK ACCESS' 30 336 380 16 $FontCaps $ColFaint)
    $cardFirewall = New-Card $viewSettings 24 358 422 64
    [void] (New-DarkLabel $cardFirewall 'Other devices need port 5000 open.' 18 13 250 22 $FontSmall $ColDim)
    $btnFirewall = New-FlatButton $cardFirewall 'Open port 5000' 274 14 130 36
    $btnFirewall.Font = $FontUI
    $helpY = 440
} else {
    $btnFirewall = $null
}

[void] (New-DarkLabel $viewSettings 'TROUBLESHOOTING' 30 $helpY 380 16 $FontCaps $ColFaint)
$cardHelp = New-Card $viewSettings 24 ($helpY + 22) 422 62

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
$notify.Visible = $true

$script:quitting     = $false
$script:balloonShown = $false
$script:autoOpenDone = $false

# ==================================================================
# Behaviour
# ==================================================================

function Open-Dashboard {
    try { Start-Process $localUrl } catch { }
}

function Show-Launcher {
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
            $statusDot.BackColor = $ColSignal
            $statusLbl.Text = 'Running'
            $btnOpen.Enabled = $true
            $btnOpen.Text = ('Open {0}' -f $AppName)
            $btnPower.Text = ('Stop {0}' -f $AppName)
            $btnPower.Enabled = $true
            $hintLbl.Text = ''
        }
        'starting' {
            $statusDot.BackColor = $ColWarn
            $statusLbl.Text = 'Starting…'
            $btnOpen.Enabled = $false
            $btnPower.Enabled = $false
            $hintLbl.Text = 'The first start after installing can take a few extra seconds.'
        }
        'stopped' {
            $statusDot.BackColor = $ColFaint
            $statusLbl.Text = 'Stopped'
            $btnOpen.Enabled = $true
            $btnOpen.Text = ('Start {0}' -f $AppName)
            $btnPower.Enabled = $false
            $hintLbl.Text = ''
        }
        'failed' {
            $statusDot.BackColor = $ColAccent
            $statusLbl.Text = 'Not running'
            $btnOpen.Enabled = $true
            $btnOpen.Text = ('Start {0}' -f $AppName)
            $btnPower.Enabled = $false
            $hintLbl.Text = $script:failReason
        }
    }

    if ($script:state -eq 'running' -and $script:settings.openBrowser -and -not $script:autoOpenDone) {
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
if ($copy2) {
    $copy2.Add_Click({
        try { [System.Windows.Forms.Clipboard]::SetText($lanUrl); $copy2.Text = 'Copied' } catch { }
    })
}

$btnSettings.Add_Click({
    $radioKeep.Checked   = ($script:settings.closeAction -eq 'keep')
    $radioStop.Checked   = ($script:settings.closeAction -eq 'stop')
    $chkStartup.Checked  = Test-StartupEnabled
    $chkAutoOpen.Checked = [bool] $script:settings.openBrowser
    $viewMain.Visible = $false
    $viewSettings.Visible = $true
})

$btnBack.Add_Click({
    $viewSettings.Visible = $false
    $viewMain.Visible = $true
})

$radioKeep.Add_CheckedChanged({
    if ($radioKeep.Checked) { $script:settings.closeAction = 'keep'; Save-LauncherSettings }
})
$radioStop.Add_CheckedChanged({
    if ($radioStop.Checked) { $script:settings.closeAction = 'stop'; Save-LauncherSettings }
})
$chkStartup.Add_CheckedChanged({
    if (-not (Set-StartupEnabled $chkStartup.Checked)) {
        [System.Windows.Forms.MessageBox]::Show(
            'The sign-in setting could not be changed.',
            $AppName,
            [System.Windows.Forms.MessageBoxButtons]::OK,
            [System.Windows.Forms.MessageBoxIcon]::Warning) | Out-Null
    }
})
$chkAutoOpen.Add_CheckedChanged({
    $script:settings.openBrowser = $chkAutoOpen.Checked
    Save-LauncherSettings
})
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

# Reset the Copy buttons and poll the server.
$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 1200
$timer.Add_Tick({
    Update-Status
    if ($copy1.Text -eq 'Copied') { $copy1.Text = 'Copy' }
    if ($copy2 -and $copy2.Text -eq 'Copied') { $copy2.Text = 'Copy' }
    # A second launcher was started — bring this one forward instead.
    if ($showSignal.WaitOne(0)) {
        [void] $showSignal.Reset()
        Show-Launcher
    }
})
$timer.Start()

# ==================================================================
# Go
# ==================================================================

Start-Server
Update-Status

if ($Tray) {
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
