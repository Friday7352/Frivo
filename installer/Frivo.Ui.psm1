# Frivo — shared window styling
# ------------------------------------------------------------------
# The dark surfaces and red accent from static/style.css, as WinForms
# helpers. Used by the installer and the uninstaller so every Frivo
# window looks like the same product.
#
# The calling script loads WinForms; tests can provide stubs instead.

$script:GdiReady = $false
if ($env:OS -eq 'Windows_NT') {
    try {
        Add-Type -Namespace FrivoNative -Name Gdi -MemberDefinition @'
[DllImport("gdi32.dll")]
public static extern IntPtr CreateRoundRectRgn(int l, int t, int r, int b, int w, int h);
'@ -ErrorAction Stop
        $script:GdiReady = $true
    } catch {
        # Already loaded from a previous import, or unavailable — in either
        # case fall through to the type probe below.
        $script:GdiReady = ($null -ne ('FrivoNative.Gdi' -as [type]))
    }
}

$script:DwmReady = $false
if ($env:OS -eq 'Windows_NT') {
    try {
        Add-Type -Namespace FrivoNative -Name Dwm -MemberDefinition @'
[DllImport("dwmapi.dll")]
public static extern int DwmSetWindowAttribute(IntPtr hwnd, int attribute, ref int value, int valueSize);
'@ -ErrorAction Stop
        $script:DwmReady = $true
    } catch {
        $script:DwmReady = ($null -ne ('FrivoNative.Dwm' -as [type]))
    }
}

$script:TaskbarReady = $false
if ($env:OS -eq 'Windows_NT') {
    try {
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
        PROPVARIANT pv = new PROPVARIANT();
        pv.vt = 31; // VT_LPWSTR
        pv.pointerValue = Marshal.StringToCoTaskMemUni(value);
        return pv;
    }
    public void Clear() { if (pointerValue != IntPtr.Zero) Marshal.FreeCoTaskMem(pointerValue); }
}
[DllImport("shell32.dll", CharSet = CharSet.Unicode)]
public static extern int SetCurrentProcessExplicitAppUserModelID(string appID);
[DllImport("shell32.dll")]
public static extern int SHGetPropertyStoreForWindow(IntPtr hwnd, ref Guid riid, out IPropertyStore propertyStore);
public static void SetWindowIdentity(IntPtr hwnd, string appId, string iconResource) {
    SetCurrentProcessExplicitAppUserModelID(appId);
    Guid iid = typeof(IPropertyStore).GUID;
    IPropertyStore store;
    if (SHGetPropertyStoreForWindow(hwnd, ref iid, out store) < 0 || store == null) return;
    PROPERTYKEY appIdKey = new PROPERTYKEY { fmtid = new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"), pid = 5 };
    PROPERTYKEY iconKey = new PROPERTYKEY { fmtid = new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"), pid = 3 };
    PROPVARIANT id = PROPVARIANT.FromString(appId);
    PROPVARIANT icon = PROPVARIANT.FromString(iconResource);
    try { store.SetValue(ref appIdKey, ref id); store.SetValue(ref iconKey, ref icon); store.Commit(); }
    finally { id.Clear(); icon.Clear(); }
}
'@ -ErrorAction Stop
        $script:TaskbarReady = $true
    } catch {
        $script:TaskbarReady = ($null -ne ('FrivoNative.Taskbar' -as [type]))
    }
}

function Get-FrivoTheme {
    <#
        One object with every colour and font, so a window never invents
        its own shade of anything.
    #>
    return [pscustomobject] @{
        Bg      = [System.Drawing.Color]::FromArgb(13, 17, 23)     # --bg
        Surface = [System.Drawing.Color]::FromArgb(22, 27, 34)     # --surface
        Card    = [System.Drawing.Color]::FromArgb(28, 35, 45)     # --surface-2
        CardHi  = [System.Drawing.Color]::FromArgb(50, 61, 76)     # --surface-4
        CardLo  = [System.Drawing.Color]::FromArgb(24, 30, 39)
        Hair    = [System.Drawing.Color]::FromArgb(42, 50, 62)
        Ink     = [System.Drawing.Color]::FromArgb(232, 238, 247)  # --ink
        Dim     = [System.Drawing.Color]::FromArgb(154, 163, 178)
        Faint   = [System.Drawing.Color]::FromArgb(110, 119, 134)
        Accent  = [System.Drawing.Color]::FromArgb(250, 47, 47)    # --accent
        AccentH = [System.Drawing.Color]::FromArgb(255, 82, 82)
        AccentP = [System.Drawing.Color]::FromArgb(216, 31, 31)
        Signal  = [System.Drawing.Color]::FromArgb(62, 207, 109)   # --signal
        Warn    = [System.Drawing.Color]::FromArgb(240, 166, 60)   # --warn
        # Standard Segoe UI is available on every supported Windows release;
        # it also renders more consistently in Windows PowerShell than the
        # Variable font family on older Windows 10 builds.
        FontUI    = New-Object System.Drawing.Font('Segoe UI', 10.5)
        FontSmall = New-Object System.Drawing.Font('Segoe UI', 9.25)
        FontCaps  = New-Object System.Drawing.Font('Segoe UI Semibold', 8.25)
        FontMid   = New-Object System.Drawing.Font('Segoe UI Semibold', 12)
        FontBig   = New-Object System.Drawing.Font('Segoe UI Semibold', 19)
        FontBtn   = New-Object System.Drawing.Font('Segoe UI Semibold', 10.5)
    }
}

function Set-FrivoRounded {
    param($Control, [int] $Radius = 12)
    if (-not $script:GdiReady) { return }
    $handler = {
        param($s, $e)
        $rgn = [FrivoNative.Gdi]::CreateRoundRectRgn(0, 0, $s.Width + 1, $s.Height + 1, $Radius, $Radius)
        $s.Region = [System.Drawing.Region]::FromHrgn($rgn)
    }.GetNewClosure()
    $Control.Add_Resize($handler)
    & $handler $Control $null
}

function Set-FrivoWindowChrome {
    <# Keeps the native Windows caption buttons while applying Frivo's dark chrome. #>
    param(
        [Parameter(Mandatory)] $Form,
        [Parameter(Mandatory)] $Theme
    )
    if (-not $script:DwmReady) { return }
    $apply = {
        try {
            $dark = 1
            [void] [FrivoNative.Dwm]::DwmSetWindowAttribute($Form.Handle, 20, [ref] $dark, 4)
            $caption = $Theme.Bg.ToArgb()
            $text = $Theme.Ink.ToArgb()
            $border = $Theme.Hair.ToArgb()
            # These colour attributes are available on current Windows 10/11;
            # unsupported versions simply ignore them.
            [void] [FrivoNative.Dwm]::DwmSetWindowAttribute($Form.Handle, 35, [ref] $caption, 4)
            [void] [FrivoNative.Dwm]::DwmSetWindowAttribute($Form.Handle, 36, [ref] $text, 4)
            [void] [FrivoNative.Dwm]::DwmSetWindowAttribute($Form.Handle, 34, [ref] $border, 4)
        } catch { }
    }.GetNewClosure()
    $handler = { & $apply }.GetNewClosure()
    $Form.Add_HandleCreated($handler)
    if ($Form.IsHandleCreated) { & $apply }
}

function Set-FrivoTaskbarIcon {
    param(
        [Parameter(Mandatory)] $Form,
        [Parameter(Mandatory)] [string] $IconPath,
        [string] $AppId = 'Frivo.Desktop'
    )
    if (-not $script:TaskbarReady -or -not (Test-Path -LiteralPath $IconPath)) { return }
    $resource = $IconPath + ',0'
    $apply = { try { [FrivoNative.Taskbar]::SetWindowIdentity($Form.Handle, $AppId, $resource) } catch { } }.GetNewClosure()
    $handler = { & $apply }.GetNewClosure()
    $Form.Add_HandleCreated($handler)
    if ($Form.IsHandleCreated) { & $apply }
}

function New-FrivoForm {
    param(
        [Parameter(Mandatory)] $Theme,
        [string] $Title,
        [int] $Width, [int] $Height,
        [string] $IconPath
    )
    $f = New-Object System.Windows.Forms.Form
    $f.Text            = $Title
    $f.ClientSize      = New-Object System.Drawing.Size($Width, $Height)
    $f.StartPosition   = 'CenterScreen'
    $f.FormBorderStyle = 'FixedDialog'
    $f.MaximizeBox     = $false
    $f.MinimizeBox     = $false
    $f.TopMost         = $false
    $f.AutoScaleMode   = 'Dpi'
    $f.BackColor       = $Theme.Bg
    $f.Font            = $Theme.FontUI
    Set-FrivoWindowChrome -Form $f -Theme $Theme
    # Show above the setup container the first time, then immediately release
    # TopMost so the user can put any other window in front as normal.
    $bringForwardOnce = {
        param($sender, $eventArgs)
        $window = $sender
        $window.TopMost = $true
        $window.Activate()
        $releaseTimer = New-Object System.Windows.Forms.Timer
        $releaseTimer.Interval = 450
        $release = {
            $releaseTimer.Stop()
            $releaseTimer.Dispose()
            $window.TopMost = $false
        }.GetNewClosure()
        $releaseTimer.Add_Tick($release)
        $releaseTimer.Start()
    }.GetNewClosure()
    $f.Add_Shown($bringForwardOnce)
    if ($IconPath -and (Test-Path -LiteralPath $IconPath)) {
        try { $f.Icon = New-Object System.Drawing.Icon($IconPath) } catch { }
        Set-FrivoTaskbarIcon -Form $f -IconPath $IconPath -AppId 'Frivo.Setup'
    }
    return $f
}

function Get-FrivoImage {
    <#
        Loads an image WITHOUT holding the file open.

        Image.FromFile keeps a lock on the file for the lifetime of the
        image, so a window showing a logo from the install folder stops
        that folder being deleted — which is how the uninstaller came to
        report "Remove static [FAILED]".

        FromStream alone is not enough either: GDI+ keeps reading from the
        stream lazily, so the stream has to outlive the image. Copying into
        a new Bitmap gives an image that owns its pixels outright, so both
        the file and the stream can be released immediately.
    #>
    param([string] $Path)
    if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $null }
    $stream = $null
    $loaded = $null
    try {
        # The comma matters: it passes the byte array as one argument
        # instead of splatting it into many.
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

function New-FrivoHeader {
    <#
        The logo + title + subtitle block every Frivo window opens with.
        Returns the subtitle label so callers can update it per page.
    #>
    param(
        [Parameter(Mandatory)] $Theme,
        [Parameter(Mandatory)] $Form,
        [string] $Title,
        [string] $Subtitle,
        [string] $LogoPngPath
    )
    $logo = New-Object System.Windows.Forms.PictureBox
    $logo.Location = New-Object System.Drawing.Point(28, 22)
    $logo.Size = New-Object System.Drawing.Size(36, 36)
    $logo.SizeMode = 'Zoom'
    $logo.BackColor = [System.Drawing.Color]::Transparent
    if ($LogoPngPath -and (Test-Path -LiteralPath $LogoPngPath)) {
        $logo.Image = Get-FrivoImage $LogoPngPath
    }
    $Form.Controls.Add($logo)

    # Extra height prevents descenders such as g and y from clipping under
    # Windows PowerShell's GDI text renderer.
    $t = New-FrivoLabel -Theme $Theme -Parent $Form -Text $Title -X 78 -Y 15 -W 470 -H 38 -Font $Theme.FontBig -Color $Theme.Ink
    $s = New-FrivoLabel -Theme $Theme -Parent $Form -Text $Subtitle -X 80 -Y 54 -W 470 -H 17 -Font $Theme.FontSmall -Color $Theme.Dim
    return [pscustomobject] @{ Logo = $logo; Title = $t; Subtitle = $s }
}

function New-FrivoCard {
    param(
        [Parameter(Mandatory)] $Theme,
        [Parameter(Mandatory)] $Parent,
        [int] $X, [int] $Y, [int] $W, [int] $H
    )
    $p = New-Object System.Windows.Forms.Panel
    $p.Location = New-Object System.Drawing.Point($X, $Y)
    $p.Size = New-Object System.Drawing.Size($W, $H)
    $p.BackColor = $Theme.Surface
    Set-FrivoRounded $p 18
    $Parent.Controls.Add($p)
    return $p
}

function New-FrivoLabel {
    param(
        [Parameter(Mandatory)] $Theme,
        [Parameter(Mandatory)] $Parent,
        [string] $Text,
        [int] $X, [int] $Y, [int] $W, [int] $H,
        $Font, $Color
    )
    $l = New-Object System.Windows.Forms.Label
    $l.Location = New-Object System.Drawing.Point($X, $Y)
    $l.Size = New-Object System.Drawing.Size($W, $H)
    $l.Text = $Text
    if ($Font)  { $l.Font = $Font }
    if ($Color) { $l.ForeColor = $Color } else { $l.ForeColor = $Theme.Ink }
    $l.BackColor = [System.Drawing.Color]::Transparent
    $Parent.Controls.Add($l)
    return $l
}

function New-FrivoButton {
    param(
        [Parameter(Mandatory)] $Theme,
        [Parameter(Mandatory)] $Parent,
        [string] $Text,
        [int] $X, [int] $Y, [int] $W, [int] $H,
        [bool] $Primary = $false
    )
    $b = New-Object System.Windows.Forms.Button
    $b.Location = New-Object System.Drawing.Point($X, $Y)
    $b.Size = New-Object System.Drawing.Size($W, $H)
    $b.Text = $Text
    $b.FlatStyle = 'Flat'
    $b.Font = $Theme.FontBtn
    $b.FlatAppearance.BorderSize = 0
    $b.Cursor = [System.Windows.Forms.Cursors]::Hand
    if ($Primary) {
        $b.BackColor = $Theme.Accent
        $b.ForeColor = [System.Drawing.Color]::White
        $b.FlatAppearance.MouseOverBackColor = $Theme.AccentH
        $b.FlatAppearance.MouseDownBackColor = $Theme.AccentP
    } else {
        $b.BackColor = $Theme.Card
        $b.ForeColor = $Theme.Ink
        $b.FlatAppearance.BorderSize = 1
        $b.FlatAppearance.BorderColor = $Theme.Hair
        $b.FlatAppearance.MouseOverBackColor = $Theme.CardHi
        $b.FlatAppearance.MouseDownBackColor = $Theme.CardLo
    }
    Set-FrivoRounded $b 14
    $Parent.Controls.Add($b)
    return $b
}

function New-FrivoCheck {
    param(
        [Parameter(Mandatory)] $Theme,
        [Parameter(Mandatory)] $Parent,
        [string] $Text,
        [int] $X, [int] $Y, [int] $W,
        [bool] $Checked = $false
    )
    $c = New-Object System.Windows.Forms.CheckBox
    $c.Location = New-Object System.Drawing.Point($X, $Y)
    $c.Size = New-Object System.Drawing.Size($W, 22)
    $c.Text = $Text
    $c.Checked = $Checked
    $c.ForeColor = $Theme.Ink
    $c.BackColor = [System.Drawing.Color]::Transparent
    $c.Font = $Theme.FontUI
    $Parent.Controls.Add($c)
    return $c
}

function New-FrivoRadio {
    param(
        [Parameter(Mandatory)] $Theme,
        [Parameter(Mandatory)] $Parent,
        [string] $Text,
        [int] $X, [int] $Y, [int] $W,
        [bool] $Checked = $false
    )
    $r = New-Object System.Windows.Forms.RadioButton
    $r.Location = New-Object System.Drawing.Point($X, $Y)
    $r.Size = New-Object System.Drawing.Size($W, 22)
    $r.Text = $Text
    $r.Checked = $Checked
    $r.ForeColor = $Theme.Ink
    $r.BackColor = [System.Drawing.Color]::Transparent
    $r.Font = $Theme.FontUI
    $Parent.Controls.Add($r)
    return $r
}

function New-FrivoTextBox {
    param(
        [Parameter(Mandatory)] $Theme,
        [Parameter(Mandatory)] $Parent,
        [int] $X, [int] $Y, [int] $W, [int] $H,
        [switch] $Multiline
    )
    $frame = New-Object System.Windows.Forms.Panel
    $frame.Location = New-Object System.Drawing.Point($X, $Y)
    $frame.Size = New-Object System.Drawing.Size($W, $H)
    $frame.BackColor = $Theme.Card
    Set-FrivoRounded $frame 12
    $Parent.Controls.Add($frame)

    $innerY = if ($Multiline) { 9 } else { 3 }
    $innerHeight = if ($Multiline) { $H - 18 } else { $H - 6 }
    $t = New-Object System.Windows.Forms.TextBox
    $t.Location = [System.Drawing.Point]::new(12, $innerY)
    $t.Size = [System.Drawing.Size]::new(($W - 24), $innerHeight)
    $t.BackColor = $Theme.Card
    $t.ForeColor = $Theme.Ink
    $t.BorderStyle = 'None'
    $t.Font = $Theme.FontUI
    if ($Multiline) {
        $t.Multiline = $true
        $t.ReadOnly = $true
        # Native WinForms scrollbars ignore theming and appear bright white.
        # This view follows the current status automatically instead.
        $t.ScrollBars = 'None'
    }
    $frame.Controls.Add($t)
    return $t
}

function New-FrivoProgress {
    <#
        A progress bar drawn from panels, because the native control paints
        Windows-green and ignores BackColor. Returns an object whose
        SetValue(0..100) moves the red fill.
    #>
    param(
        [Parameter(Mandatory)] $Theme,
        [Parameter(Mandatory)] $Parent,
        [int] $X, [int] $Y, [int] $W, [int] $H = 10
    )
    $track = New-Object System.Windows.Forms.Panel
    $track.Location = New-Object System.Drawing.Point($X, $Y)
    $track.Size = New-Object System.Drawing.Size($W, $H)
    $track.BackColor = $Theme.Card
    Set-FrivoRounded $track 10
    $Parent.Controls.Add($track)

    $fill = New-Object System.Windows.Forms.Panel
    $fill.Location = New-Object System.Drawing.Point(0, 0)
    $fill.Size = New-Object System.Drawing.Size(0, $H)
    $fill.BackColor = $Theme.Accent
    Set-FrivoRounded $fill 10
    $track.Controls.Add($fill)

    $bar = [pscustomobject] @{ Track = $track; Fill = $fill; Width = $W; Value = 0 }
    $bar | Add-Member -MemberType ScriptMethod -Name SetValue -Value {
        param([int] $Percent)
        $p = [Math]::Min(100, [Math]::Max(0, $Percent))
        $this.Value = $p
        $this.Fill.Size = New-Object System.Drawing.Size([int]($this.Width * $p / 100), $this.Fill.Size.Height)
    }
    return $bar
}

Export-ModuleMember -Function Get-FrivoImage, Get-FrivoTheme, Set-FrivoRounded, New-FrivoForm, New-FrivoHeader,
    New-FrivoCard, New-FrivoLabel, New-FrivoButton, New-FrivoCheck, New-FrivoRadio,
    New-FrivoTextBox, New-FrivoProgress, Set-FrivoWindowChrome, Set-FrivoTaskbarIcon
