# Frivo 1.6.1

## Free voices load on every PC

On some PCs the free voices failed with "Load model from ...\voices\piper\kristin\model.onnx failed: system error number 13". Setup runs as an administrator, and newer versions of Python unpack files so that only that account can read them. Frivo, running as you, then wasn't allowed to load its own voices.

- Voices, voices you add, the voice library and the built-in AI are now unpacked so they take their permissions from the Frivo folder.
- Setup (install, update and Repair) resets the permissions on the voices folder, which fixes PCs that already have the problem.
- If it still happens, the error says which folder and how to fix it, instead of the raw error number.

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

- **One panel.** The chips, the box and the switches are one card. Voice and language are grouped on the left; style, AI model, length, volume and VRChat on the right, each group with thin dividers, and the dropdowns marked with an arrow. On a phone the groups stack.
- **Only typing in the box.** The box has the mic and Send, plus a small tag icon when the voice acts tags out. Auto-send, Speak and Chatbox are real switches in a row underneath, with their names, and **Suggest tags** sits next to them. A switch that's on also gets a small dot; status messages sit at the right end.
- **The cursor starts at the beginning.** It no longer appears after "Say something…".
- **Quieter chips.** The voice, language, style, length and volume chips above the box have no outlines.
- **No more labels under replies.** "Cleaned up without AI", "Auto tags" and the like are a small dot by the reply's time. The words show in the line that appears when you point at the reply, with the details on hover.
- **Changing a tag.** Click a tag in your message to get suggestions and a box to type any tag of your own; matching tags are listed as you type. Arrows choose, Enter takes it, and a new tag is kept with your tags.


## A new voice menu

- **Short rows.** Each voice shows its name, a green dot when it's free, a star for Favorites, a play button for a sample, and the "…" menu.
- **Details when selected.** The voice in use opens to show its language, gender, who speaks it (ElevenLabs, Frivo, Windows, or one you added), whether it uses credits, and how it takes voice tags (v4 ready, tags). Arrow keys open the details of the row they're on.
- **One Filters menu.** Language, gender and type are in one Filters button, with a count of how many are on and a Clear button.
- **Tabs instead of headings.** All, Favorites and Free replace the long section headings. Sorting is the small arrows icon beside the tabs.
- **Tidier footer.** How many voices are showing, Hidden (when you've hidden a type), Browse free, and Add voice.
