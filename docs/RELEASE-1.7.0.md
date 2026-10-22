# Frivo 1.7.0

## The Frivo app (new)

Frivo in its own window for Windows, with a tray icon and no browser tab. It's a separate download, `FrivoApp-Setup-1.0.0.exe`, from the app's releases (tagged `app-v1.0.0`). The first time it opens, it asks where Frivo runs:

- **On this PC.** Frivo runs in the background and the app is its window, so there's only one thing to open. Frivo's launcher stays out of sight: the Frivo shortcuts, starting with Windows, and Frivo coming back after an update all open the app instead. If Frivo isn't installed yet, the app downloads its setup from GitHub, checks it, and runs it.
- **On another PC.** Type the address shown in Frivo's launcher on that PC. The first time, the app shows Frivo's certificate and asks you to trust it, then only accepts that one at that address.

What else it does:

- **Same Frivo.** The app shows Frivo's own pages, so every Frivo update shows up in it straight away. The app only updates itself when its own parts change, and asks before restarting to do it.
- **Settings › App** (only in the app): where Frivo runs, the network address for phones, Stop Frivo, Start with Windows, what closing the window does, and the app's own updates. The same things are on the tray icon's menu.
- **Closing the window** keeps Frivo running in the tray, so phones and other devices stay connected. **Quit** in the tray stops it. You can change this.
- **When Frivo drops out**, the app says so and reconnects by itself, including through an in-app Frivo update.
- **Nothing changes for browsers and phones.** In a browser on Windows, Settings › Updates offers the app, once, with a way to hide it.
- **Existing installs** just add the app. It finds the Frivo that's already here and uses it; settings, profiles, saved replies, voices and keys stay where they are.

**For the launcher:** a new *app mode*. When the app runs Frivo on this PC, the launcher has no window or tray icon, opens the app wherever it used to show itself, and stops Frivo when the app asks. Uninstall the app, or point it at another PC, and the launcher is back to its own window and tray icon.

**Launch Frivo now**, at the end of setup, starts Frivo as you rather than as administrator. Frivo started that way used to run as administrator until you signed out, and nothing else (a new launcher, or now the app) could stop it.

## The built-in AI cleans up after itself

- **No more locked folder.** The built-in AI's engine could keep running after Frivo was closed, crashed or was stopped by an update. It then held its files open, so the folder couldn't be deleted ("open in another program") and the AI couldn't be downloaded again. On Windows the engine now always stops when Frivo does. Frivo also stops one left over from before when it starts, and setup, the launcher's Stop and the uninstaller stop it too.
- **Uninstalling removes it.** The engine and models (gigabytes) are deleted when Frivo is uninstalled, even if you keep your settings.
- **Download again**, next to Test, replaces the engine and the model, for when the AI won't start.
- **Remove says when it can't.** If a file is still in use, it says so, instead of reporting that the AI was removed when it wasn't.

## Choose where Frivo keeps its big files

**Settings › Storage** (new): pick a folder for each of these, on the PC Frivo runs on:

- **Built-in AI:** the engine and its models.
- **Voices you add:** from Browse free voices or Add a voice.
- **Saved replies.**
- **Reply audio.**

How it works:

- **Picking a folder:** each row shows the folder, how much it uses and the drive's free space. **Change…** opens a folder picker for that PC: drives, folders and **Make folder**. Frivo keeps the files in a subfolder of the one you pick (`builtin_ai`, `voices`, `saved`, `audio_cache`), never loose in it.
- **Moving:** what's already there is moved, with progress. Frivo switches over once the copy is complete, and only then deletes the old copy. If anything fails, nothing changes.
- **Already-used folders:** if Frivo's files are already in that folder (from an earlier install, say), it asks first and can use them instead of moving.
- **Back to Frivo's folder** puts everything back. If a picked drive isn't plugged in when Frivo starts, Frivo says so and uses its own folder until it's back.
- **What stays put:** settings, profiles and keys stay in Frivo's own folder. Backups never bring another PC's folders with them.
- **Uninstalling** also removes the built-in AI from a picked folder. If you delete your settings, it removes Frivo's subfolders there too, never anything else in the folder.
- **Ollama's models:** Storage explains how to move them on the Ollama PC (OLLAMA_MODELS).

## Frivo comes back after an in-app update

The launcher could stay open saying **Stopped** after an update, and Frivo wasn't started again. The update watcher asks the launcher to close before setup replaces the files. When that request didn't reach it, the launcher stayed open, and because a launcher was still running, nothing restarted Frivo.

The launcher now follows the update itself. It closes when the update starts installing, and if it's somehow still open when the update finishes, it starts the server again.

## A cleaner message box

- **One panel.** The chips, the box and the switches are one card. Voice and language are grouped on the left; AI model, length, volume and VRChat on the right, each group with thin dividers, and the dropdowns marked with an arrow. On a phone the groups stack.
- **Only typing in the box.** The box has the mic and Send, plus a small tag icon when the voice acts tags out. Auto-send, Speak and Chatbox are real switches in a row underneath, with their names, and **Suggest tags** sits next to them. Status messages sit at the right end.
- **The cursor starts at the beginning.** It no longer appears after "Say something…".
- **Quieter chips.** The voice, language, length and volume chips above the box have no outlines, and the length and volume chips keep their size, so "125 words" doesn't push the others over.
- **No style chip.** The profile decides how replies are written (Reply, Clean up, Word for word), so the chip that repeated it is gone. Change it in the profile, or in Settings › Replies.
- **No more labels under replies.** "Cleaned up without AI", "Auto tags" and the like are a small dot by the reply's time. The words show in the line that appears when you point at the reply, with the details on hover.
- **Changing a tag.** Click a tag in your message to get suggestions and a box to type any tag of your own; matching tags are listed as you type. Arrows choose, Enter takes it, and a new tag is kept with your tags.

## A new voice menu

- **Short rows.** Each voice shows its name, a green dot when it's free, a star for Favorites, a play button for a sample, and the "…" menu.
- **Details when selected.** The voice in use opens to show its language, gender, who speaks it (ElevenLabs, Frivo, Windows, or one you added), whether it uses credits, and how it takes voice tags (v4 ready, tags). Arrow keys open the details of the row they're on.
- **One Filters menu.** Language, gender and type are in one Filters button, with a count of how many are on and a Clear button.
- **Tabs instead of headings.** All, Favorites and Free replace the long section headings. Sorting is the small arrows icon beside the tabs.
- **Tidier footer.** How many voices are showing, Hidden (when you've hidden a type), Browse free, and Add voice.
