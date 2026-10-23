# Frivo 1.4.0

Frivo now updates itself. When a newer version is released, an **Update
available** chip appears at the bottom of the sidebar. Click it to see
what's new, then choose **Update now**. Frivo downloads the new installer,
checks it against the fingerprint GitHub publishes, installs it on the PC
Frivo runs on, and restarts. The page reloads into the new version.
Settings, profiles and API keys are kept.

This works from any device, including a browser on another computer, and
it doesn't ask for permission. Setup adds a **Frivo Updater** task to Task
Scheduler that does the installing. It only installs `FrivoSetup.exe` from
Frivo's own GitHub releases, and only once the file matches.

**Settings > About Frivo** shows the version, has **Check for updates**,
and has a switch for the automatic check: a few seconds after Frivo starts,
then every six hours. **Earlier versions** goes back to an older release
the same way. Going back keeps your settings, and you can update again at
any time.

Install this version with `FrivoSetup.exe` once. That's the last installer
you need to download by hand: 1.4.0 is the first version that can update
itself, so it's also the oldest one that **Earlier versions** offers.
