# Frivo

Frivo is a local Windows dashboard for conversational AI, voice output,
profiles, private speech transcription through Evora, VRChat chatbox messages
over OSC, and optional OSC-based mute-synced dictation. It runs on your
computer and opens in your web browser.

## Screenshots

### Dashboard

![Frivo dashboard](docs/screenshots/dashboard.png)

### Launcher

![Frivo launcher](docs/screenshots/launcher.png)

### Settings

![Frivo settings](docs/screenshots/settings.png)

### New profile

![Create a new Frivo profile](docs/screenshots/newProfile.png)

## Download and install

1. Download `FrivoSetup.exe` from the latest GitHub release.
2. Double-click it and approve the Windows permission prompt.
3. Follow the Frivo setup screens. The default installation location is
   recommended.
4. When setup finishes, leave **Launch Frivo now** selected to open Frivo.

The first setup may download Python and Frivo's required libraries, so an
internet connection is needed while installing. Frivo is supported on
Windows 10 and Windows 11.

## First-time setup

Open Frivo from the desktop or Start Menu shortcut, then select **Open
Frivo** in the small Frivo window. In the dashboard, open **Settings** and
save your API keys.

* **OpenAI API key** — required for the default chat experience.
* **ElevenLabs API key** — required only when **Speak** is enabled.

If you do not have an ElevenLabs key, turn **Speak** off. Frivo can still
return text replies with an OpenAI key. If Speak is on without an ElevenLabs
key, Frivo shows a helpful error and does not send the message.

API providers may charge for their services. You are responsible for your
own OpenAI and ElevenLabs accounts, usage, and costs.

## Local Ollama models

If you prefer not to use OpenAI for chat and translation, Frivo can use a
locally hosted Ollama model instead. Install and run Ollama, then select
**Ollama (local)** in **Settings** > **Providers** and choose your model.
An OpenAI API key is not required when chat and translation use Ollama.

## Local transcription with Evora

[Evora](https://github.com/Friday7352/Evora) is Frivo's optional private,
local transcription service. It converts audio to text on your own computer
or another Windows PC on your local network. Frivo can then translate that
text with the provider you selected, such as Ollama or OpenAI.

Evora is a separate application and is not included in Frivo:

1. Download `EvoraSetup.exe` from the
   [latest Evora release](https://github.com/Friday7352/Evora/releases/latest).
2. Install and start Evora. If it runs on another computer, allow private
   network access during setup.
3. In Frivo, open **Settings** > **Providers** > **Transcription** and enter
   the address shown by the Evora launcher.
4. Use `http://evora.local:9000` when both applications run on the same PC.
   For another computer, use Evora's displayed network address, such as
   `http://192.168.x.x:9000`.

Evora can use a supported NVIDIA GPU for faster transcription and otherwise
runs on the CPU. No cloud transcription account or API key is required.

## Recommended audio routing: Voicemeeter

Frivo works without Voicemeeter, but Voicemeeter and its virtual audio cables
are recommended when using Frivo's listening features or sending Frivo's
spoken replies into VRChat.

Use a dedicated virtual cable for the program or game you want Frivo to
listen to, then select that cable as Frivo's listening input. This lets
Frivo hear that source without also capturing your microphone, other apps,
or the rest of your system audio.

For VRChat voice output, route Frivo's spoken audio to the virtual output you
use for VRChat, then select the matching virtual input as VRChat's microphone.
The exact device names depend on your Voicemeeter setup. Frivo does not
install or configure Voicemeeter for you.

## Everyday use

The Frivo window starts and monitors the local server. It shows the address
for this computer and provides these controls:

* **Open Frivo** opens the dashboard in your browser.
* **Settings** controls whether Frivo stays running after the window closes,
  starts with Windows, and opens automatically in your browser.
* **Stop Frivo** stops the local server.

The desktop and Start Menu shortcuts open the Frivo window. If Frivo is
already running in the notification area, using a shortcut brings that window
back.

On the same computer, the dashboard is normally available at:

    https://frivo.local:5000

## VRChat OSC chatbox

Frivo can send replies to the VRChat chatbox through OSC. It does not control
your avatar or send messages until you enable it.

1. In VRChat, enable and configure OSC in the Options menu.
2. In Frivo, open **Settings** > **VRChat chatbox**.
3. Enter the LAN address of the PC running VRChat. Use `127.0.0.1` when
   VRChat and Frivo run on the same PC.
4. Leave the default port as `9000` unless your VRChat OSC configuration uses
   another port, then use **Test**.
5. Turn on the **Chatbox** switch beside the message box when you want replies
   sent to the chatbox.

VRChat chatbox messages are limited to 144 characters. Frivo automatically
pages longer messages and spaces them out to avoid VRChat's spam protection.
Anyone who can see your VRChat chatbox may see these messages. OSC uses UDP,
so delivery cannot be confirmed by Frivo.

If VRChat runs on another PC, that PC must allow inbound UDP traffic on the
chosen OSC port (normally UDP 9000).

## OSC controls (mute-synced dictation)

A separate, optional feature — nothing here affects the chatbox above, or
anything else about the app, unless you turn it on. With it off, Frivo behaves
exactly as it always has.

When enabled, Frivo listens for the avatar parameters VRChat itself sends out
— specifically `MuteSelf`, the built-in parameter tracking your mic mute
state — and uses it to keep dictation in sync with VRChat: dictation
auto-disables the moment you mute, and auto-enables when you unmute. Clicking
the mic button always still works exactly as it always has — it isn't locked
out or overridden by this, it's just no longer the only way dictation turns on
or off.

1. In VRChat, enable OSC in the Options menu (the same setting the chatbox
   feature above needs).
2. In Frivo, open **Settings** > **OSC controls** and turn on **Mute-synced
   dictation**.
3. Leave **Listen port** at `9001` unless your VRChat OSC configuration uses
   another port for its output.

If VRChat and Frivo run on the **same PC**, that's everything — VRChat sends
to `127.0.0.1:9001` by default and Frivo is already listening there. No
firewall rule is needed, since the traffic never leaves the machine.

### VRChat and Frivo on different PCs

Nothing extra needs to run on the VRChat PC. VRChat can send its OSC output
straight to another machine, set once as a launch option.

1. In Steam, right-click **VRChat** → **Properties** → **Launch Options**,
   and enter:

       --osc=9000:192.168.1.50:9001

   Replace `192.168.1.50` with the Frivo server's LAN address. The format is
   `--osc=inPort:sendIP:outPort` — the first port is what VRChat listens on
   (leave it at `9000`, that's what the chatbox feature sends to), and the
   middle value is where VRChat sends its output.

2. Restart VRChat so the launch option takes effect.

The firewall is handled by the installer — its Frivo rule covers the OSC
listener as well as the dashboard, so there is nothing to open by hand. If
Frivo is running from source rather than installed, allow inbound UDP 9001
once from an elevated prompt:

    netsh advfirewall firewall add rule name="Frivo OSC in" dir=in action=allow protocol=UDP localport=9001

**One caveat:** VRChat has a single OSC output destination, so this sends
*all* of its output to the Frivo server instead of to `127.0.0.1`. If you run
other OSC apps on the VRChat PC — face tracking, avatar tools, VRCOSC — they
stop receiving data, because it's no longer going to that machine. If that
applies to you, either point VRChat at an OSC router that fans out to both,
or use the bundled relay described below.

### Optional: the bundled relay

`app/osc_relay.py` is an alternative for the case above — when you want
VRChat's output to reach the Frivo server *and* stay available to local OSC
apps. Leave VRChat's output pointed at `127.0.0.1` as normal, and run the
relay on the VRChat PC to copy that traffic onward:

    python osc_relay.py --target 192.168.1.50

Or double-click **Start-OSC-Relay.bat**, which prompts for the address. It
needs only Python itself — no `pip install`, none of Frivo's other
requirements — so `osc_relay.py` can be copied to a VRChat PC on its own.

Most people won't need this. The launch option above is simpler and runs
nothing extra.

**The relay needs only Python itself** — no `pip install`, none of Frivo's
other requirements. It imports nothing outside the standard library, because
the PC running VRChat usually isn't the one with Frivo's dependencies set up.
Copying `osc_relay.py` on its own to a VRChat PC with any Python 3 install is
enough; it doesn't read your config, doesn't need API keys, and doesn't touch
`%APPDATA%\Frivo`. All it does is forward UDP packets byte-for-byte.

## Other devices on your network

During setup, you can allow connections from other devices on your private
network. The Frivo window then shows a network address such as:

    https://192.168.x.x:5000

Only enable this on a network you trust. A phone or another computer may show
a certificate warning on its first visit because Frivo's local certificate is
trusted only on the PC where Frivo was installed.

If you skipped this option during setup, use the Frivo launcher Settings to
open the firewall port later.

## Privacy and saved data

Frivo keeps its data on your PC in:

    %APPDATA%\Frivo\

This includes your settings, saved profiles, local usage record, generated
audio cache, and API keys. API keys are stored in `config.json` in plain text
for the signed-in Windows account. Do not share that file or upload it to
GitHub.

This repository intentionally excludes keys, preferences, logs, certificates,
and generated audio.

## Uninstalling

Open **Settings** > **Apps** > **Installed apps**, choose **Frivo**, and
select **Uninstall**.

Running a newer Frivo setup also detects an existing installation and offers:

- **Update** — refreshes Frivo's program files while retaining the existing
  Python environment. Dependencies are only installed when `requirements.txt`
  has changed.
- **Repair** — rebuilds the program files and Python environment while keeping
  your saved settings.
- **Uninstall** — removes Frivo from the setup wizard.

The uninstaller removes Frivo, its shortcuts, its Windows startup entry, the
Frivo firewall rule, its local address and certificate. It asks whether to
also remove Frivo's saved API keys and preferences. Leave that option
unchecked if you plan to reinstall later.

## Troubleshooting

If installation fails, the setup log is saved here:

    %TEMP%\Frivo-Setup.log

The Frivo launcher also includes buttons to open its server log and settings
folder.

## Building from source

For development, clone this repository and run `Install.bat` to use the
source setup wizard. To create a new public single-file installer,
double-click `Build-Installer.bat` in the project folder. It builds the
installer and, if needed, installs Inno Setup automatically.

The finished installer is written to `dist\FrivoSetup.exe`.
