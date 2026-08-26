# Frivo

Frivo is a local Windows dashboard for conversational AI, voice output,
profiles, private speech transcription through Evora, and VRChat integration
through FrivOSC. It runs on your computer and opens in your web browser.

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

## VRChat with FrivOSC

[FrivOSC](https://github.com/Friday7352/FrivOSC) is Frivo's optional VRChat
companion. It connects Frivo to VRChat over OSC, so replies can appear in your
chatbox and VRChat's own mute button can drive Frivo's dictation.

VRChat only speaks OSC to `127.0.0.1`. It will not send to another computer and
will not listen to one, so Frivo cannot reach it across a network no matter how
it is configured. FrivOSC solves this by running on the PC you play VRChat on,
where that traffic already is, and talking to Frivo over the network instead.
FrivOSC only makes outgoing connections, so there is nothing to forward, no
port to open on either computer, and no VRChat launch options.

FrivOSC is a separate application and is not included in Frivo:

1. Download `FrivOSCSetup.exe` from the
   [latest FrivOSC release](https://github.com/Friday7352/FrivOSC/releases/latest)
   and install it **on the computer you play VRChat on**. If that is also the
   computer running Frivo, install it there.
2. During setup, enter the address you use to open Frivo, and use **Test**.
   Leave the default when Frivo runs on the same computer; otherwise use that
   computer's address, such as `https://192.168.1.50:5000`. This is the one
   thing FrivOSC cannot work out for itself — it can be changed later in the
   FrivOSC window.
3. In VRChat, enable OSC in the Options menu.
4. In Frivo, open **Settings** > **VRChat** and turn on **VRChat OSC**.

**FrivOSC** appears in Frivo's sidebar beside Evora once the feature is on.
Click it to see whether it is connected and to reach these settings:

* **VRChat OSC** — the master switch for everything below.
* **Follow VRChat mute** — unmuting in VRChat starts dictation and muting stops
  it. The microphone button still overrides this at any time.
* **Unmute when I send** — opens the VRChat microphone if you are muted, so a
  spoken reply is not delivered into a closed mic. It never mutes you.

Turn on the **Chatbox** switch beside the message box when you want replies sent
to the chatbox.

### Worth knowing

VRChat chatbox messages are limited to 144 characters. Frivo pages longer
messages automatically and spaces them out to avoid VRChat's spam protection.
Anyone who can see your VRChat chatbox can see these messages.

OSC is UDP, so VRChat never confirms delivery. FrivOSC reports what it sent, not
what arrived.

The microphone options press VRChat's mute key rather than setting a state,
because VRChat exposes no way to set one. That means they depend on **Options >
Voice > Toggle Voice** being on, which is VRChat's default. With it off, VRChat
treats the mute key as push-to-talk and FrivOSC will say so in its log rather
than silently doing nothing.

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
